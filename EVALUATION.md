# VerEval evaluation guide

## Protocol and reproducibility

The latest appendix specifies **evidence-based mode for every main-table result**:
the judge receives the question, model prediction and verified ground truth,
**without video frames**. The judge is a fixed local Qwen3-VL-32B, temperature 0,
1,024-token output cap, and a deterministic seed. The numerical seed and exact
model checkpoint revision are not specified in the supplied manuscript.

Each answer uses three calls:

1. Fact scorer: factual errors, hallucinations, key entities and omissions.
2. Logic scorer: question understanding and logical/spatio-temporal coherence.
3. Consistency scorer: question/answer/evidence plus BOTH previous scores and reasons.

Final value is `0.9 * consistency + 0.1 * logic` in [0,1]; reports also expose
the 0–100 equivalent. Fact is diagnostic and is **not** averaged in separately.
The prompts are an executable English transcription/adaptation of the appendix
rubrics, with JSON framing, explicit evidence mode and prompt-injection defenses.
Original PDF-extracted wording is retained in `provenance/scoring-prompts.txt`.
This newly written implementation is not the historical evaluation harness;
using a different judge, checkpoint or prompt may change the results.

The optional `frames` mode sends ordered still images with timestamps. It is a
sampled-frame video-aware variant, not the main-table protocol and not full-video
decoding. Report it separately. Optional reference_text is additional evidence;
leave it absent when matching the paper's QA-only evidence-based inputs.

## Install

Python 3.9+; a modern Python 3.11+ is preferable on macOS for an OpenSSL-backed
HTTPS stack.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Input

Use the released `data/test.json` as benchmark. Predictions may be a JSON array
or JSONL; each object needs:

```json
{"question_id": "1_L1.1_05272d09", "prediction": "健康护理"}
```

Legacy keys `id` and `generated` are also accepted, matching the existing
`ocr_nolayout_gpt-5_2_20260330_scores.json` structure. The old score fields are
ignored when re-evaluating. `answer` is never treated as the prediction.

IDs are joined strictly, not by row order or approximate question matching.
Duplicate IDs, unknown IDs, contradictory questions or video names are errors.
Missing predictions require `--allow-partial`; a partial result is clearly
marked in the summary. Empty-string predictions are passed to the judge as
empty answers, not silently dropped.

### Old L2.5 / L3.3 IDs

Add `--legacy-ids` **only for pre-swap prediction files**:

- `2_L2.5_some_original_suffix` → `3_L3.3_some_original_suffix`
- `3_L3.3_some_original_suffix` → `2_L2.5_some_original_suffix`

All suffix components remain unchanged. Current benchmark IDs are never swapped.
An accidental double swap fails strict matching.

## vLLM service

On your GPU server, serve your chosen checkpoint under an explicit model name:

```bash
vllm serve /path/to/Qwen3-VL-32B \
  --served-model-name vereval-judge --host 127.0.0.1 --port 8000
```

Select model revision, tensor-parallel size and memory options for your hardware.
Do not expose an unauthenticated server to the public internet. The scoring
client uses the service's `/v1/chat/completions` endpoint.

First validate without issuing requests:

```bash
python -m vereval --benchmark data/test.json --predictions predictions.jsonl \
  --backend vllm --base-url http://localhost:8000/v1 --model vereval-judge \
  --evidence-mode evidence_based --temperature 0 --max-tokens 1024 --seed 42 \
  --output outputs/vllm-run --dry-run
```

Remove `--dry-run` to score. Here **42 is an explicit example seed, not a claimed
historical seed**. The full test split requires 4,173 successful judge calls,
plus any retries. If the service requires authentication, set `VLLM_API_KEY`
in your environment; an unauthenticated local service uses `EMPTY`.

For the supplied old-ID predictions:

```bash
python -m vereval --benchmark data/test.json \
  --predictions ../data/ocr_nolayout_gpt-5_2_20260330_scores.json \
  --legacy-ids --backend vllm --model vereval-judge \
  --temperature 0 --max-tokens 1024 --seed 42 --output outputs/ocr-diagnostic
```

This remains an **OCR-only/no-layout diagnostic**, not a video-model main-table
entry. Do not mix it into the manuscript leaderboard.

## OpenAI service

Set `OPENAI_API_KEY` through your shell/secret manager. Never place it in source,
a prediction file, the website or a committed .env file.

```bash
python -m vereval --benchmark data/test.json --predictions predictions.jsonl \
  --backend openai --model YOUR_OPENAI_JUDGE \
  --evidence-mode evidence_based --output outputs/openai-run --workers 4
```

Replace the placeholder with a Chat Completions-capable model available to your
account. OpenAI runs are a **different-judge evaluation**, not a reproduction of
the Qwen3-VL-32B main table. Model-specific temperature/seed/token/JSON settings
are omitted unless you set them, because not all models support the same options.
`--max-tokens` maps to `max_completion_tokens` for OpenAI and `max_tokens` for
vLLM. `--json-mode` requests JSON object output only if your endpoint supports it.
Custom compatible gateways can use `--base-url` and `--api-key-env ENV_NAME`.
This client does not implement Azure-specific deployment/authentication.

## Optional video-frame evidence

Install FFmpeg and use a vision-capable judge. Eight frames at width 1280 is an
example sampling configuration, **not a paper-mandated value**:

```bash
python scripts/prepare_frames.py --benchmark data/test.json \
  --video-dir ../huggingface/test --output outputs/evidence-8frames \
  --num-frames 8 --width 1280

python -m vereval --benchmark data/test.json --predictions predictions.jsonl \
  --backend vllm --model vereval-judge --evidence-mode frames \
  --evidence outputs/evidence-8frames/evidence.json --output outputs/frame-run
```

Configure the vLLM server's multimodal limits to accept the number of images per
request. The sampler writes each video's frames once; all questions on that
video reference the same files. It refuses to overwrite an existing directory.

Manual manifest format (keys are corrected IDs, frame paths relative to manifest):

```json
{
  "1_L1.1_05272d09": {
    "frames": ["video/frame000.jpg", "video/frame001.jpg"],
    "frame_timestamps": [0.5, 1.5]
  }
}
```

Frames are base64-encoded into every judge call; they are not assumed to exist
on the remote server. Frame mode requires frames for every submitted question.
For main-table evidence-based mode, omit the manifest entirely.

## Reliability and outputs

- SDK transport retries: `--api-retries`; malformed-score retries:
  `--schema-retries`; request timeout: `--timeout`.
- Scores must be finite and in [0,1] with a nonempty reason. NaN, infinity, boolean
  scores, malformed/truncated responses are not silently accepted or clamped.
- Failed samples are recorded as errors, **not zero scores**; a run with failures
  returns exit status 1. Fix the issue and rerun the same command with `--resume`.
- Successful rows are flushed/fsynced incrementally to `scores.jsonl`.
  Resume skips them only if the model, URL, decoding parameters, prompts,
  benchmark, predictions, evidence and hashes agree. Changed inputs require a
  new output directory. Do not run two processes into the same output directory.
- `run.json`: configuration and prompt/run hashes, no API key.
- `scores.jsonl`: QA IDs, all three scores/reasons, raw judge text, usage,
  timestamps and fingerprints. After retrying errors it may contain historical
  failed attempts; `summary.json` includes only the latest attempt in that run.
- `summary.json`: successful/failed/missing counts, coverage, per-task and
  per-level scores, micro average and task macro average. Never interpret a
  partial-run score as a complete benchmark result.
- Exact reproducibility also depends on endpoint/checkpoint pinning and serving
  configuration; a fixed seed alone cannot guarantee it.

## Tests and sources

```bash
python -m unittest discover -s tests -v
```

The tests use the real OpenAI SDK with an in-process mock HTTP transport:
3-stage dependencies, field formats, retries, score validation, strict alignment,
legacy suffix preservation, dry-run, resume invalidation and failed-run status.
They make no external calls and consume no model credits.

[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) ·
[vLLM compatible-server documentation](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) ·
[Paper judge setup](provenance/acl_appendix.tex).
