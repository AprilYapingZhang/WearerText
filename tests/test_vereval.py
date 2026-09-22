import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from vereval.runner import align, canonical_id, parse_judgment, score_answer, summarize, main, add_evidence


def truth(qid="2_L2.5_suffix_with_underscores"):
    return dict(question_id=qid, task_id=qid.split("_")[1], level=int(qid[0]),
                question="Is this a suitable venue?", answer="Yes, the sign supports that.",
                video_path="example.mp4")


SETTINGS = dict(model="test-judge", backend="vllm", evidence_mode="evidence_based",
                schema_retries=1, json_mode=True, max_tokens=300)


class MockJudge:
    def __init__(self, invalid_first=False, fail=False):
        self.requests = []
        self.invalid_first = invalid_first
        self.fail = fail

    def handle(self, request):
        self.requests.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer TEST_TOKEN"
        if self.fail:
            return httpx.Response(503, json={"error": {"message": "test failure"}})
        body = self.requests[-1]
        prompt = body["messages"][0]["content"]
        stage = "consistency" if "# Consistency" in prompt else "logic" if "# Logic" in prompt else "fact"
        if stage == "consistency":
            payload = json.loads(body["messages"][1]["content"][0]["text"])
            assert payload["fact_judgment"] == {"score": 0.1, "reason": "fact reason"}
            assert payload["logic_judgment"] == {"score": 0.6, "reason": "logic reason"}
        content = json.dumps(dict(score={"fact": 0.1, "logic": 0.6, "consistency": 0.8}[stage], reason=stage + " reason"))
        if self.invalid_first and len(self.requests) == 1:
            content = '{"score": "NaN", "reason": "invalid"}'
        return httpx.Response(200, json=dict(id="mock", object="chat.completion", created=0, model="test-judge",
            choices=[dict(index=0, finish_reason="stop", message=dict(role="assistant", content=content))],
            usage=dict(prompt_tokens=10, completion_tokens=10, total_tokens=20)))

    def client(self, **kwargs):
        kwargs.update(api_key="TEST_TOKEN", http_client=httpx.Client(transport=httpx.MockTransport(self.handle)))
        return OpenAI(**kwargs)


class AlignmentTests(unittest.TestCase):
    def test_legacy_swap_preserves_suffix(self):
        self.assertEqual(canonical_id("3_L3.3_suffix_with_underscores", True), truth()["question_id"])
        self.assertEqual(canonical_id("2_L2.5_suffix_with_underscores", True), "3_L3.3_suffix_with_underscores")
        self.assertEqual(canonical_id(truth()["question_id"]), truth()["question_id"])

    def test_strict_alignment_and_old_fields(self):
        row = truth()
        jobs, missing = align([row], [dict(id="3_L3.3_suffix_with_underscores", generated="yes", question=row["question"])], legacy=True)
        self.assertFalse(missing)
        self.assertEqual(jobs[0]["answer"], row["answer"])
        self.assertEqual(jobs[0]["task_id"], "L2.5")
        for bad in [dict(question="different"), dict(video_path="wrong.mp4"), dict(id="1_L1.1_unknown")]:
            pred = dict(id=row["question_id"], generated="yes")
            pred.update(bad)
            with self.assertRaises(ValueError):
                align([row], [pred])
        with self.assertRaises(ValueError):
            align([row], [dict(id=row["question_id"], answer="Not a prediction")])
        pred = dict(id=row["question_id"], generated="")
        with self.assertRaises(ValueError):
            align([row], [pred, pred])
        with self.assertRaises(ValueError):
            align([row, truth("1_L1.1_second")], [pred])
        self.assertEqual(len(align([row, truth("1_L1.1_second")], [pred], allow_partial=True)[1]), 1)

    def test_invalid_scores(self):
        for value in ("NaN", "Infinity", -0.1, 1.01, True, None):
            with self.assertRaises((ValueError, TypeError)):
                parse_judgment(json.dumps(dict(score=value, reason="x")))
        for raw in ('[]', '{}', '{"score": 0.5, "reason": ""}', 'not json'):
            with self.assertRaises((ValueError, KeyError)):
                parse_judgment(raw)
        self.assertEqual(parse_judgment('```json\n{"score":"0.50","reason":"ok"}\n```')["score"], 0.5)


class PipelineTests(unittest.TestCase):
    def test_three_calls_dependency_and_weight(self):
        judge = MockJudge(invalid_first=True)
        job = dict(truth(), prediction="yes", input_question_id=truth()["question_id"])
        with judge.client(base_url="http://mock/v1", max_retries=0) as client:
            result = score_answer(job, client.chat.completions.create, SETTINGS)
        self.assertEqual(len(judge.requests), 4)
        self.assertEqual(result["vereval_100"], 78.0)
        self.assertEqual(judge.requests[0]["max_tokens"], 300)
        summary = summarize([result, dict(status="error")], 3)
        self.assertEqual(summary["micro_average"], 78.0)
        self.assertEqual((summary["failed"], summary["missing"], summary["complete"]), (1, 1, False))

    def test_openai_wire_format_with_frames(self):
        judge = MockJudge()
        job = dict(truth(), prediction="yes", input_question_id=truth()["question_id"],
                   frame_urls=["data:image/png;base64,TEST"], frame_timestamps=[0.5])
        settings = dict(SETTINGS, backend="openai", evidence_mode="frames")
        with judge.client(base_url="https://mock/v1", max_retries=0) as client:
            score_answer(job, client.chat.completions.create, settings)
        self.assertEqual(judge.requests[0]["max_completion_tokens"], 300)
        self.assertNotIn("max_tokens", judge.requests[0])
        self.assertEqual(judge.requests[0]["messages"][1]["content"][1]["type"], "image_url")
        self.assertEqual(len(judge.requests), 3)

    def test_evidence_required_and_timestamps(self):
        with self.assertRaises(ValueError):
            add_evidence([truth()], None, "frames")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps({truth()["question_id"]: {"frame_timestamps": [1], "frames": []}}))
            with self.assertRaises(ValueError):
                add_evidence([truth()], path, "evidence_based")

    def test_cli_dry_run_resume_fingerprints_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp)
            benchmark, predictions = root / "bench.json", root / "pred.jsonl"
            benchmark.write_text(json.dumps([truth()]))
            predictions.write_text(json.dumps(dict(question_id=truth()["question_id"], prediction="yes")) + "\n")
            flags = ["--benchmark", str(benchmark), "--predictions", str(predictions), "--backend", "vllm", "--model", "test-judge",
                     "--base-url", "http://mock/v1", "--output", str(root / "run"), "--api-retries", "0"]
            with patch("openai.OpenAI") as mocked:
                self.assertEqual(main(flags + ["--dry-run"]), 0)
                mocked.assert_not_called()
                self.assertFalse((root / "run").exists())
            judge = MockJudge()
            with patch("openai.OpenAI", judge.client):
                self.assertEqual(main(flags), 0)
                self.assertEqual(main(flags + ["--resume"]), 0)
                self.assertEqual(len(judge.requests), 3)
                with self.assertRaises(ValueError):
                    main(flags + ["--resume", "--temperature", "0"])
                predictions.write_text(json.dumps(dict(question_id=truth()["question_id"], prediction="changed")))
                with self.assertRaises(ValueError):
                    main(flags + ["--resume"])
            with patch("openai.OpenAI", MockJudge(fail=True).client):
                self.assertEqual(main(flags + ["--output", str(root / "error")]), 1)
                report = json.loads((root / "error/summary.json").read_text())
                self.assertEqual(report["failed"], 1)
                self.assertIsNone(report["micro_average"])


if __name__ == "__main__":
    unittest.main()
