## What changed

Describe the user-visible or architecture-level change in 2-6 bullets.

## Render evidence

For changes that touch the HTML/CSS -> PPTX conversion path, include:

- Source render(s):
- Candidate render(s) (LibreOffice and/or Graph):
- Diff evidence (heatmap or score summary):
- Notes on expected lossy behavior (if any):

If conversion fidelity is not relevant, state why.

## Validation

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pyright`
- [ ] `pytest -m "not integration"`
