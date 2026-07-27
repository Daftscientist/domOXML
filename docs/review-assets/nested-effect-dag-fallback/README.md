# Nested effect graph fallback evidence

The source shape contains a named `type="tree"` effect graph with one named sibling branch. The
branch applies a red outer shadow to the shape fill and intentionally excludes the yellow source
line. PowerPoint executes that graph; LibreOffice ignores it, retains the line, and omits the
shadow. domOXML therefore retains the exact graph in the PowerPoint branch and supplies the
authoritative Graph pixels as one slide-owned fallback for incompatible renderers.

| Boundary | Global | Regional | Focused | Structural |
|---|---:|---:|---:|---:|
| Original PowerPoint/Graph -> original LibreOffice | 0.969880 | 0.784314 | 0.500793 | 0.930213 |
| Original PowerPoint/Graph -> normalized HTML | 0.999441 | 0.999216 | 0.996078 | 0.962278 |
| Original PowerPoint/Graph -> rebuilt PowerPoint/Graph | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| Original PowerPoint/Graph -> rebuilt LibreOffice fallback | 0.996624 | 0.986405 | 0.964622 | 0.968708 |
| normalized HTML cycle 1 -> cycle 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

Coverage reports the native slide background beneath one full-slide rasterized/noneditable visual,
with the source graph attached. Regenerated packages must contain the exact tree/container names,
effect order, shadow values, source reference, fallback marker, and core package relationships.

Files:

- `source-graph.png`: authoritative original PowerPoint/Graph render.
- `source-libreoffice.png`: original LibreOffice render showing the compatibility failure.
- `reverse-html.png` / `reverse-html-diff.png`: normalized-HTML render and diff.
- `rebuilt-graph.png` / `source-vs-rebuilt-graph-diff.png`: retained native graph in PowerPoint.
- `rebuilt-libreoffice.png` / `source-vs-rebuilt-libreoffice-diff.png`: selected fallback in LibreOffice.
