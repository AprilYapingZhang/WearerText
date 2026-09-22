# Release provenance

Scientific source: the supplied `WearerText_EMNLP2026_CameraReady/` LaTeX
directory. Historical commented-out content is not treated as current.

- `main-acl.tex`: title, active 14-author list, affiliations, abstract.
- `tab-task-definitions.tex`: final 13 task names/IDs, definitions and examples.
- `exp-main-results-tab.tex`: all 20 main-table models and every reported score.
- `sec_dataset_construc.tex`: MAH-V and the VerEval formula.
- `acl_appendix.tex`: full-benchmark statistics, test/train split, judge protocol,
  prompts and ethical/release conditions.
- `*_score_prompt.pdf`, `scoring-prompts.txt`: original rubric figures and
  PDF-extracted text, retained alongside the executable implementation.

Website figures come only from the currently referenced `figure1.pdf`,
`figure_methods.pdf`, and `Fig7_failure_case_0526.pdf`. Older statistics graphics
elsewhere in the source tree use obsolete task definitions; the website instead
shows the current appendix's tabulated statistics.

## Recompiled paper

The source directory's `main-acl.pdf` is an obsolete anonymous
EmbodiedTextBench draft. The released `assets/WearerText.pdf` was built afresh
from the current LaTeX with pdfLaTeX/BibTeX (17 pages).

The only compilation shim declares U+FF0C (full-width comma in the author list)
as a normal comma. No manuscript content or original source file was modified.
The build retains a nonfatal source warning about an unresolved PDF footnote
destination; the title, named authors, bibliography and current content render.
This is a supplied project manuscript, not a claim of conference publication.

To rebuild on a machine with TeX Live and latexmk:

```bash
python scripts/build_paper.py --source ../WearerText_EMNLP2026_CameraReady
```

All build auxiliary files are created in a temporary directory.
