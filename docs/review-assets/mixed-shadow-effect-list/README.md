# Mixed shadow effect-list review evidence

This bundle records the bidirectional `mixed-shadow-effect-list` capability at the commit that
introduced it. The fixture combines one CSS outer shadow and one CSS inset shadow on the same
shape.

## Forward and reverse scores

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice | 0.992 | 0.967 | 0.853 | 0.978 |
| Microsoft Graph | 0.992799 | 0.970196 | 0.865415 | 0.982236 |
| Normalized reverse HTML | 0.996 | 0.980 | 0.910 | 0.996 |
| Second-cycle convergence | 1.000 | 1.000 | 1.000 | 1.000 |

The package contains one schema-ordered `a:effectLst` with `a:innerShdw` followed by
`a:outerShdw`, one guarded private effect-intent payload, and one shape-owned portable picture.
The native metadata shape is hidden only while the exact picture is present in the PowerPoint
choice, preventing transparent fallback pixels from double-painting the native outer shadow.

## Mutation

`mutation-double-paint-graph.png` removes only `hidden="1"` from the native shape while retaining
the same effect list and portable picture. Microsoft Graph then visibly paints both shadows and
drops to:

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Graph double-paint mutation | 0.984866 | 0.916340 | 0.729412 | 0.980844 |

This mutation demonstrates that the hidden native component is required for exact PowerPoint
display, not merely package bookkeeping. Removing the portable fallback through Canvas IR rebuilds
the native shape without `hidden="1"`, so the editable effect list remains independently usable.

## Files

- `source.png`: Chromium source render.
- `forward-libreoffice.png`: aligned LibreOffice candidate.
- `forward-libreoffice-diff.png`: LibreOffice diff.
- `forward-graph.png`: aligned Microsoft Graph candidate.
- `forward-graph-diff.png`: Microsoft Graph diff.
- `reverse-html.png`: normalized HTML render.
- `reverse-html-diff.png`: normalized HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two diff.
- `mutation-double-paint-graph.png`: rejected Graph double-paint mutation.
- `mutation-double-paint-graph-diff.png`: mutation diff.
