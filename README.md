# WearerText

**WearerText** is a benchmark for evaluating **wearer-centered scene text understanding in real-world AI-glasses videos**.

Unlike conventional videos recorded with viewfinder feedback, AI-glasses videos are passively captured from the wearer's first-person perspective. Natural head movement often makes text off-center, fragmented, blurred, or only briefly visible. Models must therefore do more than recognize text: they must identify the relevant textual evidence, align it with the wearer's changing viewpoint, and reason according to the wearer's goal.

## Dataset Overview

WearerText contains:

- **1,101** real-world AI-glasses videos
- **15,336** question–answer pairs
- **13** tasks
- Videos recorded at **30 FPS**, with durations of **5–10 seconds**
- Real-world scenarios covering:
  - Shopping centers
  - Transportation hubs
  - Tourist destinations
- Chinese, English, and mixed Chinese–English content

The dataset is divided into video-disjoint training and test sets:

| Split | Videos | QA Pairs |
|---|---:|---:|
| Train | 994 | 13,945 |
| Test | 107 | 1,391 |
| **Total** | **1,101** | **15,336** |

## Task Hierarchy

WearerText organizes its 13 tasks into a three-level diagnostic hierarchy:

### L1: Text Perception

Evaluates whether a model can recognize and localize unstable or briefly visible text in dynamic AI-glasses videos.

- Dynamic Text Recognition
- Dynamic Text Localization

### L2: Contextual Understanding

Evaluates whether a model can identify and interpret relevant text within the wearer's surrounding visual context.

- Query-Guided Text Extraction
- Confirmation
- Cross-Lingual Understanding
- Situated Semantic Interpretation
- Wearer-Centered Situational Inference

### L3: Wearer-Grounded Reasoning

Evaluates reasoning over temporal text evidence, viewpoint trajectories, and wearer goals.

- History-Conditioned Intent Inference
- Action-Trajectory Intent Prediction
- Structured Text Synthesis
- Spatio-Temporal Navigation Reasoning
- Goal-Oriented Comparison
- Viewpoint Trajectory Description

The hierarchy is progressive rather than strictly independent: higher-level tasks often depend on perception and grounding capabilities assessed at lower levels.

## Dataset Construction

WearerText was collected by eight consenting research-team volunteers using RayNeo AI glasses. Collection was intent-driven rather than based on scripted actions: participants selected genuine activities in text-rich shopping, transportation, and tourism environments.

We introduce **MAH-V**, a Multi-Agent–Hybrid Verification pipeline following a:

> **Generate → Verify → Refine → Human Validate**

workflow. Candidate QA pairs undergo factual, logical, and consistency checking, followed by correction or rejection by three expert annotators. Final acceptance requires a two-out-of-three majority decision.

## Evaluation

For open-ended answer evaluation, we introduce **VerEval**, a verified-evidence evaluation framework that measures:

- Factual consistency with verified video-derived evidence
- Compatibility with spatio-temporal constraints
- Logical consistency of the predicted answer

VerEval supports both evidence-based and video-aware evaluation modes. The evidence-based mode enables scalable evaluation without repeatedly processing the full video, while the video-aware mode provides stronger direct visual grounding.

Experiments with 20 recent multimodal large language models show that WearerText remains challenging, particularly for wearer-view alignment, structured text synthesis, viewpoint-trajectory understanding, and goal-oriented text reasoning.

## Privacy and Intended Use

All recording participants provided informed consent. Third-party faces were automatically blurred and subsequently checked through manual frame-level inspection.

WearerText is intended exclusively for **academic and non-commercial research**. Attempts to reverse anonymization or identify individuals are strictly prohibited.

## Release

The dataset, evaluation code, MAH-V and VerEval configurations, and prompt templates will be made available in this repository.
