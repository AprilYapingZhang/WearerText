"""Three-stage scoring with strict alignment, resumable output and explicit evidence."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from .prompts import PROMPTS, VERSION


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_rows(path):
    text = Path(path).read_text(encoding="utf-8")
    rows = json.loads(text) if text.lstrip().startswith("[") else [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Expected a JSON array or JSONL objects")
    return rows


def canonical_id(qid, legacy=False):
    if not isinstance(qid, str) or not re.fullmatch(r"[123]_L[123]\.\d+_.+", qid):
        raise ValueError(f"Invalid question ID: {qid!r}")
    level, task, suffix = qid.split("_", 2)
    if level != task[1]:
        raise ValueError(f"Level/task mismatch: {qid}")
    if legacy:
        task = {"L2.5": "L3.3", "L3.3": "L2.5"}.get(task, task)
    return f"{task[1]}_{task}_{suffix}"


def align(benchmark, predictions, legacy=False, allow_partial=False):
    truth = {}
    for row in benchmark:
        qid = canonical_id(row["question_id"])
        if qid in truth:
            raise ValueError(f"Duplicate benchmark ID: {qid}")
        if row["task_id"] != qid.split("_")[1] or str(row["level"]) != qid[0]:
            raise ValueError(f"Inconsistent benchmark metadata: {qid}")
        truth[qid] = row
    jobs, seen = [], set()
    for pred in predictions:
        raw_id = pred.get("question_id", pred.get("id"))
        if "question_id" in pred and "id" in pred and pred["question_id"] != pred["id"]:
            raise ValueError("Conflicting id and question_id")
        qid = canonical_id(raw_id, legacy)
        if qid in seen or qid not in truth:
            raise ValueError(f"Duplicate or unknown prediction ID: {qid}")
        seen.add(qid)
        gt = truth[qid]
        if "question" in pred and pred["question"] != gt["question"]:
            raise ValueError(f"Question text mismatch: {qid}")
        for key in ("video_path", "video"):
            if key in pred and Path(pred[key]).name != Path(gt["video_path"]).name:
                raise ValueError(f"Video mismatch: {qid}")
        candidate = pred.get("prediction", pred.get("generated"))
        if "prediction" in pred and "generated" in pred and pred["prediction"] != pred["generated"]:
            raise ValueError(f"Conflicting prediction/generated: {qid}")
        if not isinstance(candidate, str):
            raise ValueError(f"Missing string prediction/generated: {qid}; 'answer' is ground truth, not prediction")
        jobs.append(dict(gt, prediction=candidate, input_question_id=raw_id))
    missing = sorted(set(truth) - seen)
    if not jobs:
        raise ValueError("No predictions to evaluate")
    if missing and not allow_partial:
        raise ValueError(f"Missing {len(missing)} / {len(truth)} predictions; use --allow-partial explicitly")
    return jobs, missing


def parse_judgment(raw):
    if not isinstance(raw, str):
        raise ValueError("No text response from judge")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict) or isinstance(result.get("score"), bool):
        raise ValueError("Judge must return an object with numeric score and reason")
    score = float(result["score"])
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Score must be finite and in [0,1]")
    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Missing nonempty scoring reason")
    return dict(score=score, reason=reason)


def score_answer(job, create, settings):
    evidence = dict(question=job["question"], ground_truth=job["answer"],
                    answer=job["prediction"], evidence_mode=settings["evidence_mode"],
                    reference_text=job.get("reference_text", ""),
                    frame_timestamps_seconds=job.get("frame_timestamps", []))
    judgments = {}
    for stage in ("fact", "logic", "consistency"):
        inputs = dict(evidence)
        if stage == "consistency":
            inputs["fact_judgment"] = {k: judgments["fact"][k] for k in ("score", "reason")}
            inputs["logic_judgment"] = {k: judgments["logic"][k] for k in ("score", "reason")}
        content = [{"type": "text", "text": json.dumps(inputs, ensure_ascii=False)}]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in job.get("frame_urls", []))
        messages = [{"role": "system", "content": PROMPTS[stage]}, {"role": "user", "content": content}]
        kwargs = dict(model=settings["model"], messages=messages)
        if settings.get("json_mode"):
            kwargs["response_format"] = {"type": "json_object"}
        if settings.get("temperature") is not None:
            kwargs["temperature"] = settings["temperature"]
        if settings.get("seed") is not None:
            kwargs["seed"] = settings["seed"]
        if settings.get("max_tokens"):
            key = "max_tokens" if settings["backend"] == "vllm" else "max_completion_tokens"
            kwargs[key] = settings["max_tokens"]
        last_error = None
        for attempt in range(settings["schema_retries"] + 1):
            response = create(**kwargs)  # Transport retries belong to the OpenAI SDK.
            raw = response.choices[0].message.content
            try:
                judgment = parse_judgment(raw)
                if response.choices[0].finish_reason not in (None, "stop"):
                    raise ValueError("Judge response truncated or filtered")
                judgment.update(raw=raw, response_id=response.id,
                                usage=response.usage.model_dump() if response.usage else None)
                judgments[stage] = judgment
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_error = exc
                if attempt == settings["schema_retries"]:
                    raise ValueError(f"{stage}: invalid response after {attempt + 1} attempts: {exc}") from exc
                kwargs["messages"] = messages + [{"role": "assistant", "content": raw or ""},
                    {"role": "user", "content": "Return valid JSON with score in [0,1] and a nonempty reason. Correct the formatting; use the same evidence."}]
        if stage not in judgments:
            raise ValueError(str(last_error))
    value = 0.9 * judgments["consistency"]["score"] + 0.1 * judgments["logic"]["score"]
    return dict(question_id=job["question_id"], input_question_id=job["input_question_id"],
                task_id=job["task_id"], level=job["level"], video_path=job["video_path"],
                question=job["question"], ground_truth=job["answer"], prediction=job["prediction"],
                status="ok", judgments=judgments, vereval=round(value, 10),
                vereval_100=round(value * 100, 8))


def summarize(results, expected):
    good = [r for r in results if r["status"] == "ok"]
    def avg(rows):
        return round(sum(r["vereval_100"] for r in rows) / len(rows), 6) if rows else None
    by_task = {key: dict(count=sum(r["task_id"] == key for r in good),
                         score=avg([r for r in good if r["task_id"] == key]))
               for key in sorted({r["task_id"] for r in good})}
    by_level = {str(key): dict(count=sum(r["level"] == key for r in good),
                              score=avg([r for r in good if r["level"] == key]))
                for key in sorted({r["level"] for r in good})}
    return dict(formula="0.9 * consistency + 0.1 * logic", scale="0–100",
                expected=expected, successful=len(good), failed=sum(r["status"] != "ok" for r in results),
                missing=expected - len(results), complete=len(good) == expected,
                coverage=len(good) / expected if expected else 0,
                micro_average=avg(good), task_macro_average=(
                    round(sum(t["score"] for t in by_task.values()) / len(by_task), 6) if by_task else None),
                by_task=by_task, by_level=by_level,
                note="Failed/missing rows are excluded, never silently zero-filled. Partial runs are not leaderboard-comparable.")


def add_evidence(jobs, manifest_path, mode):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
    for job in jobs:
        item = manifest.get(job["question_id"], {})
        job["reference_text"] = item.get("reference_text", "")
        if not isinstance(job["reference_text"], str):
            raise ValueError("reference_text must be a string")
        urls, hashes = [], []
        frames = item.get("frames", [])
        if mode == "evidence_based" and frames:
            raise ValueError("Frames supplied in evidence_based mode; choose --evidence-mode frames")
        if mode == "frames" and not frames:
            raise ValueError(f"No frames supplied for {job['question_id']}")
        for name in frames:
            path = (manifest_path.parent / name).resolve()
            mime = mimetypes.guess_type(path.name)[0]
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                raise ValueError(f"Unsupported frame format: {path}")
            content = path.read_bytes()
            hashes.append(hashlib.sha256(content).hexdigest())
            urls.append(f"data:{mime};base64," + base64.b64encode(content).decode())
        times = item.get("frame_timestamps", [])
        if times and (len(times) != len(frames) or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in times) or times != sorted(times)):
            raise ValueError(f"Invalid frame timestamps: {job['question_id']}")
        job["frame_urls"], job["frame_hashes"], job["frame_timestamps"] = urls, hashes, times


def output_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/run"))
    parser.add_argument("--backend", choices=("openai", "vllm"), required=True)
    parser.add_argument("--model", required=True, help="Exact judge model ID exposed by the service")
    parser.add_argument("--base-url", help="API endpoint ending in /v1")
    parser.add_argument("--api-key-env", help="Environment variable name, never the secret itself")
    parser.add_argument("--legacy-ids", action="store_true", help="Swap old L2.5/L3.3 and update level; preserve entire suffix")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--evidence-mode", choices=("evidence_based", "frames"), default="evidence_based")
    parser.add_argument("--evidence", type=Path, help="JSON keyed by corrected question_id: reference_text and/or ordered frame paths")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--api-retries", type=int, default=2)
    parser.add_argument("--schema-retries", type=int, default=2)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--seed", type=int, help="Fixed decoding seed, if supported by the judge endpoint")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--json-mode", action="store_true", help="Only for servers supporting response_format=json_object")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate coverage and evidence without requests or output writes")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.timeout <= 0 or min(args.api_retries, args.schema_retries) < 0:
        parser.error("Workers/timeout must be positive and retries nonnegative")
    if args.max_tokens is not None and args.max_tokens < 1:
        parser.error("--max-tokens must be positive")
    if args.temperature is not None and (not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2):
        parser.error("--temperature must be a finite number in [0,2]")
    base_url = args.base_url or ("http://localhost:8000/v1" if args.backend == "vllm" else "https://api.openai.com/v1")
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("Use an HTTP(S) base URL without credentials/query/fragment")
    benchmark = load_rows(args.benchmark)
    jobs, missing = align(benchmark, load_rows(args.predictions), args.legacy_ids, args.allow_partial)
    add_evidence(jobs, args.evidence, args.evidence_mode)
    settings = dict(backend=args.backend, model=args.model, base_url=base_url,
                    evidence_mode=args.evidence_mode, temperature=args.temperature, seed=args.seed,
                    max_tokens=args.max_tokens, json_mode=args.json_mode,
                    schema_retries=args.schema_retries, api_retries=args.api_retries, timeout=args.timeout,
                    prompt_version=VERSION, prompt_hash=digest(PROMPTS))
    if args.evidence_mode == "evidence_based":
        print("Evidence-based mode: question, prediction and verified ground truth; no video frames (the main-table input protocol).", file=sys.stderr)
    for job in jobs:
        job["fingerprint"] = digest(dict(settings=settings, sample={k: v for k, v in job.items() if k != "frame_urls"}))
    if args.dry_run:
        print(json.dumps(dict(predictions=len(jobs), benchmark=len(benchmark), missing=len(missing),
                              evidence_mode=args.evidence_mode, calls_without_retries=3 * len(jobs)), indent=2))
        return 0
    key_name = args.api_key_env or ("VLLM_API_KEY" if args.backend == "vllm" else "OPENAI_API_KEY")
    key = os.environ.get(key_name, "EMPTY" if args.backend == "vllm" else "")
    if not key:
        raise ValueError(f"Set {key_name} before calling the service")
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "scores.jsonl"
    cached = {}
    if log_path.exists():
        if not args.resume:
            raise ValueError(f"Output exists: {log_path}. Choose a new directory or --resume")
        # Refuse corrupt/truncated JSONL instead of silently losing completed work.
        for row in load_rows(log_path):
            if row.get("status") == "ok":
                cached[row["question_id"]] = row
    config_path = args.output / "run.json"
    run_fingerprint = digest(dict(settings=settings, benchmark=digest(benchmark), missing=missing,
                                  samples=sorted(j["fingerprint"] for j in jobs)))
    if config_path.exists():
        old = json.loads(config_path.read_text())
        if not args.resume or old["run_fingerprint"] != run_fingerprint:
            raise ValueError("Run configuration, predictions, evidence or prompts changed; choose a new output directory")
    elif args.resume and log_path.exists():
        raise ValueError("Cannot resume scores without their run.json provenance")
    output_json(config_path, dict(settings=settings, run_fingerprint=run_fingerprint,
                missing_ids=missing, expected=len(benchmark), submitted=len(jobs)))
    from openai import OpenAI
    results, pending = [], []
    for job in jobs:
        prev = cached.get(job["question_id"])
        if prev and prev.get("fingerprint") == job["fingerprint"]:
            results.append(prev)
        else:
            pending.append(job)
    print(f"Scoring {len(pending)} answers; reusing {len(results)}; {len(missing)} missing", flush=True)
    with OpenAI(api_key=key, base_url=base_url, timeout=args.timeout, max_retries=args.api_retries) as client:
        with log_path.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(score_answer, j, client.chat.completions.create, settings): j for j in pending}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # SDK exceptions can include request details; never persist credentials.
                    result = dict(question_id=job["question_id"], task_id=job["task_id"], level=job["level"],
                                  status="error", error_type=type(exc).__name__,
                                  error=str(exc).replace(key, "[REDACTED]")[:2000])
                result["fingerprint"] = job["fingerprint"]
                result["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                results.append(result)
                print(f"[{len(results)}/{len(jobs)}] {job['question_id']}: {result['status']}", flush=True)
    summary = summarize(results, len(benchmark))
    output_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
