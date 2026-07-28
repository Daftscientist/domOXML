# Mixed shadow owned-fallback review evidence

This bundle records the bidirectional `mixed-shadow-owned-fallback` capability. The fixture
combines two CSS outer shadows and one inset shadow, a repeated effect-list slot that cannot be
represented exactly by one schema-valid DrawingML `effectLst`.

## Forward and reverse scores

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| LibreOffice | 0.990628 | 0.959739 | 0.823363 | 0.974742 |
| Microsoft Graph | 0.991522 | 0.963660 | 0.839716 | 0.981218 |
| Normalized reverse HTML | 0.995467 | 0.978824 | 0.901544 | 0.996361 |
| Second-cycle convergence | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

The generated package contains a hidden editable native shape with one `a:innerShdw` and one
`a:outerShdw`, plus a visible shape-owned picture containing the exact Chromium paint. Typed
effect intent retains all three CSS layers, authored order, signed spread, and the explicit
`schema_subset` projection. Reverse import accepts that intent only while the emitted native
subset is unchanged.

## Counterfactual

`native-subset-graph.png` removes the exact picture and exposes only the legal native effect list.
PowerPoint then loses the red outer layer and the visible inset:

| Render | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Graph native-subset only | 0.983598 | 0.934902 | 0.792908 | 0.970829 |

This proves the exact layer is required for visible parity. The native subset remains an editable
base and a freshness witness; editing it invalidates stale exact intent on reverse import.

## Files

- `source.png`: Chromium source render.
- `forward-libreoffice.png`: aligned LibreOffice candidate.
- `forward-libreoffice-diff.png`: LibreOffice diff.
- `forward-graph.png`: aligned Microsoft Graph candidate.
- `forward-graph-diff.png`: Microsoft Graph diff.
- `reverse-html.png`: normalized HTML render.
- `reverse-html-diff.png`: normalized HTML diff.
- `convergence-diff.png`: cycle-one versus cycle-two diff.
- `native-subset-graph.png`: rejected native-subset-only Graph render.
- `native-subset-graph-diff.png`: counterfactual diff.
