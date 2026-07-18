# Representative PPTX corpus

These unmodified external decks exercise package shapes that isolated HTML fixtures do not.
Every case pins its source revision, source URL, SHA-256 digest, license, package contract,
reverse assertions, and either renderer floors or an explicit visual exclusion.

The first four seed files come from
[`aiden0z/pptx-renderer`](https://github.com/aiden0z/pptx-renderer) at commit
`68cb570940fb28d5c4628f31d1365016c4483521` under Apache-2.0. The redistributed license is in
[`LICENSE.pptx-renderer`](LICENSE.pptx-renderer).

The soft-edge/effects deck comes from
[`iOfficeAI/OfficeCLI`](https://github.com/iOfficeAI/OfficeCLI) at commit
`c402d04892b1db5e3824054d7e62f191514bf21b` under Apache-2.0. Its redistributed license is in
[`LICENSE.OfficeCLI`](LICENSE.OfficeCLI). Its slide 5 baseline deliberately records the remaining
ellipse text-rectangle debt while pinning all three native soft-edge radii and their visual falloff.

The default PowerPoint table-style contract was cross-checked against the pinned repository's
`src/renderer/predefinedTableStyles.ts`; domOXML's Python implementation is independently written
and limited to the style proven by the external fixture.

Run the merge-blocking LibreOffice gates:

```bash
uv run python scripts/real_deck_check.py --require-backend
```

Run the same source-PPTX versus round-trip-PPTX comparison through Microsoft PowerPoint:

```bash
uv run python scripts/real_deck_check.py --backend both --require-backend
```
