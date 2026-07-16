# Shared Capability And OOXML Inventory

This inventory owns format-independent capabilities used by PPTX now and reusable by future DOCX,
XLSX, PDF, image, and HTML adapters. Presentation-specific package behavior belongs in
[`inventory-pptx.md`](inventory-pptx.md).

## Status Model

Status is capability-level, not element-level:

| Status | Meaning |
|---|---|
| Verified native | native semantic mapping has executable structural and visual evidence in both directions |
| Native, one-way | native mapping exists but only one direction has executable capability evidence |
| Partial | a meaningful subset maps natively; other variants use fallback or remain gaps |
| Decomposed | several editable primitives reproduce one source feature |
| Layered | raster/image layers provide the current visual path |
| Preserve only | source XML/data is retained, but current alternate-format visual output is incomplete |
| Gap | no adequate mapping or verified parity path exists yet |
| Unit only | implementation has focused tests but lacks an atomic bidirectional visual fixture |

Visual parity, semantic editability, preservation, and direction are separate facts. “Partial” is
never permission for visible approximation: unhandled variants should move through the layered
backend described in [`architecture.md`](architecture.md).

Forward conversion now emits a typed coverage record for every captured visual. Representation is
`native`, `decomposed`, `hybrid`, `layered`, `element_layer`, `approximated`, or `failed`;
editability, source retention, output count, and raster area are recorded independently. Capability
manifests place explicit ceilings on every lossy representation. Applying this same record to PPTX
ingest and attached preservation is still roadmap work.

## Current Shared Capability Matrix

Audited on **2026-07-16**. `cap:*` refers to a manifest below `capabilities/pptx/`; “both” means the
runner executes HTML -> PPTX -> HTML -> PPTX with configured visual and structural floors.

| Family | Current forward path | Current reverse path | Evidence | Main remaining work |
|---|---|---|---|---|
| OPC packages and relationships | Native | Native | unit + 4 real decks | full XSD/Open XML validation, strict packages, alternate content, general extension re-emission beyond attached charts |
| Units, page boxes, identity, and fixed layout | Native, canonical ordered scene with slide-scoped IDs/provenance | Native, canonical ordered scene with recovered IDs/provenance | `cap:interleaved-order` + `cap:node-identity` (both) + broad tests | exact group reconstruction and preservation ownership beyond charts |
| Solid colors and alpha | Native | Native | fidelity corpus + integration | complete color models/transforms and theme-token preservation on forward output |
| Theme colors and font schemes | Partial; attached chart re-emission restores its ambient source theme | Partial/native read | unit + chart real deck | general forward scheme references, complete style matrix, script fonts, deck-level source-theme policy |
| Rectangles, rounded rectangles, ellipses | Native | Native | integration | adversarial transform/effect combinations |
| Preset shapes | Partial | Partial | `cap:preset-shapes` (both) | remaining curved/formula presets and adjustment handles |
| Custom paths | Partial/native one-way | Partial | `cap:custom-path` (forward) | arcs/shorthand/multipath, guide formulas, connector structure, bidirectional fixture |
| Connectors | Partial | Partial | unit only | routing, attachment sites, arrows, bent/curved parity, forward/reverse re-emission |
| Groups and stacking | Gap for authored groups; flat output | Native read then flattened | unit only | canonical interleaved z-order, group authoring, nested transforms, stable grouping |
| Solid and no fill | Native | Native | integration | explicit atomic bidirectional fixture |
| Linear/radial gradients | Native subset | Native subset | fidelity corpus | every gradient form, transforms/stops, renderer calibration, theme-aware stops |
| Picture fills and crop | Native | Native | `cap:picture-crop` (both) | tile/contain/position variants, image effects, adversarial crop/transform cases |
| Pattern fills | Partial | Partial | `cap:pattern-fills` (both) | full preset set, renderer portability, native-vs-layer selection |
| Uniform strokes | Native | Native | `cap:borders` (both) | compound/alignment strokes and broader color models |
| Per-side borders | Decomposed | Native as component shapes | `cap:borders` (both) | rounded nonuniform borders without approximation; grouping/source relation |
| Dash, cap, and join | Partial/native | Partial/native | unit + `cap:borders` | complete preset semantics and renderer parity |
| Arrowheads and gradient strokes | Gap/partial | Partial | unit only | visible HTML arrows, forward authoring, round-trip fixture |
| Outer shadow | Partial/native | Native | `cap:effects` (forward) | exact blur/spread/scale/color behavior and reverse gate |
| Inner shadow | Element layer | Native read | `cap:effects` (forward) | portable native/hybrid policy and PowerPoint-calibrated proof |
| Glow | Partial/native | Partial CSS | `cap:effects` (forward) | halo calibration, compound effects, reverse gate |
| Blur, soft edge, reflection | Layered forward | Partial CSS/preserve | unit only | minimal hybrid layers, exact bounds, stable round trips |
| Other effect-list constructs | Layered/gap | Preserve only | unit only | effect containers/order, preset shadow, fill overlay, visual fallback and re-emission |
| Basic text runs | Native | Native | `cap:text-rich-runs` (both) | language/script coverage and font portability |
| Decoration, caps, and spacing | Partial/native | Partial/native | `cap:text-decorations` (both) | complete underline/strike/baseline/RTL/vertical text variants |
| Paragraph layout and body properties | Partial/native | Partial/native | `cap:body-props` (both) | tabs, complete inheritance, vertical/RTL, overflow and exact autofit parameters |
| Bullets and numbering | Partial/native | Partial/native | `cap:bullets-spacing` (both) | all numbering schemes, bullet font/color/size, restart and nested edge cases |
| Hyperlinks and slide targets | Native | Native | `cap:hyperlink` (both) | action types, tooltip/history, security policy, non-HTTP relationships |
| Multi-column text | Partial/native | Partial/native | `cap:body-props` (both) | balanced-vs-sequential policy, overflow and renderer parity |
| Text warp/WordArt | Gap/layer path not proven | Gap | unit model absent | IR, native DrawingML mapping, layered fallback and round-trip corpus |
| Fonts and embedding | Partial/native | Partial/native | unit/integration + real deck | licensing states, malformed fonts, Graph limitation, substitutions, script faces |
| Raster images | Native | Native | integration | effects, linked images, color transforms, metadata/accessibility |
| SVG vectors | Native SVG extension + PNG fallback | Native read | `cap:svg-vector` (forward) | preserve SVG extension through reverse re-emission; bidirectional fixture |
| Audio and video | Layered/not authored natively | Native read | unit only | native authoring, posters/playback, HTML/PPTX parity and real-deck evidence |
| Tables | Native subset | Native subset | `cap:table` (both) + real deck | complete styles/inheritance, borders, layout, nested content and adversarial cases |
| Charts | Attached source re-emission only; authored charts remain a gap | Attached preserve; normalized HTML remains nonvisual | `cap:chart-preservation` (reverse) + real-deck PPTX visual gate | shared chart/data IR, HTML rendering/layer, and native chart authoring |
| Unknown visual extensions | Element layer on HTML input | Preserve only on PPTX input | unit only | universal renderer-backed reverse layers and attached preservation payloads |
| Fidelity metrics | global/regional/structural plus typed forward representation coverage | global/regional/structural | CI + tests | reverse coverage records, object-aware segmentation, typography/color metrics, layer/editability ratchets |
| Repeated round trips | one cycle for 14 bidirectional fixtures | 14 bidirectional fixtures plus reverse-first chart preservation | capability runner | configurable multi-cycle convergence and broader source-format preservation gates |

## Shared Work Remaining For PPTX

The dependency order is:

1. Complete group ownership/reconstruction and extend the chart-owned preservation contract to all
   preserved visuals; slide-scoped IDs, active provenance, and chart graph ownership are implemented.
2. Universal native/decomposed/hybrid/layered planner in both directions.
3. Geometry, group, connector, and z-order completeness.
4. Theme-aware paint, strokes, effects, and renderer calibration.
5. Deep text layout, inheritance, autofit, lists, vertical/RTL, and WordArt.
6. Complete tables, shared chart/data models, SVG/media, and asset handling.
7. Strict/transitional packages, alternate content, extension lists, and schema validation.
8. Object-aware fidelity and repeated-round-trip convergence ratchets.

<!-- BEGIN GENERATED SCHEMA INVENTORY -->
## ECMA-376 Schema Surface

Generated by `scripts/generate_spec_inventories.py` from the official ECMA-376 5th edition Part 4 Transitional XSDs. The source archives are SHA-256 pinned in the generator.

This `shared` partition contains **1123 qualified element names**, **1677 named declarations**, **630 named complex types**, and **23 namespaces**. Repeated declarations of one QName are combined and retain every declared type.

This appendix is a discovery checklist, not an implementation percentage. One user-facing capability often uses several elements, and one element can participate in unrelated capabilities. Runtime status belongs in the curated tables above and in executable fixtures.

Official standard: <https://ecma-international.org/publications-and-standards/standards/ecma-376/>

### Namespace Legend

| Prefix | Namespace |
|---|---|
| `c` | `http://schemas.openxmlformats.org/drawingml/2006/chart` |
| `cdr` | `http://schemas.openxmlformats.org/drawingml/2006/chartDrawing` |
| `dgm` | `http://schemas.openxmlformats.org/drawingml/2006/diagram` |
| `lc` | `http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas` |
| `a` | `http://schemas.openxmlformats.org/drawingml/2006/main` |
| `pic` | `http://schemas.openxmlformats.org/drawingml/2006/picture` |
| `xdr` | `http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing` |
| `wp` | `http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing` |
| `b` | `http://schemas.openxmlformats.org/officeDocument/2006/bibliography` |
| `ac` | `http://schemas.openxmlformats.org/officeDocument/2006/characteristics` |
| `cp` | `http://schemas.openxmlformats.org/officeDocument/2006/custom-properties` |
| `ds` | `http://schemas.openxmlformats.org/officeDocument/2006/customXml` |
| `vt` | `http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes` |
| `ep` | `http://schemas.openxmlformats.org/officeDocument/2006/extended-properties` |
| `m` | `http://schemas.openxmlformats.org/officeDocument/2006/math` |
| `r` | `http://schemas.openxmlformats.org/officeDocument/2006/relationships` |
| `s` | `http://schemas.openxmlformats.org/officeDocument/2006/sharedTypes` |
| `sl` | `http://schemas.openxmlformats.org/schemaLibrary/2006/main` |
| `xvml` | `urn:schemas-microsoft-com:office:excel` |
| `o` | `urn:schemas-microsoft-com:office:office` |
| `pvml` | `urn:schemas-microsoft-com:office:powerpoint` |
| `wvml` | `urn:schemas-microsoft-com:office:word` |
| `v` | `urn:schemas-microsoft-com:vml` |

### Elements

| QName | Declared type(s) | Source XSD |
|---|---|---|
| `a:accent1` | `CT_Color` | `dml-main.xsd` |
| `a:accent2` | `CT_Color` | `dml-main.xsd` |
| `a:accent3` | `CT_Color` | `dml-main.xsd` |
| `a:accent4` | `CT_Color` | `dml-main.xsd` |
| `a:accent5` | `CT_Color` | `dml-main.xsd` |
| `a:accent6` | `CT_Color` | `dml-main.xsd` |
| `a:ahLst` | `CT_AdjustHandleList` | `dml-main.xsd` |
| `a:ahPolar` | `CT_PolarAdjustHandle` | `dml-main.xsd` |
| `a:ahXY` | `CT_XYAdjustHandle` | `dml-main.xsd` |
| `a:alpha` | `CT_PositiveFixedPercentage` | `dml-main.xsd` |
| `a:alphaBiLevel` | `CT_AlphaBiLevelEffect` | `dml-main.xsd` |
| `a:alphaCeiling` | `CT_AlphaCeilingEffect` | `dml-main.xsd` |
| `a:alphaFloor` | `CT_AlphaFloorEffect` | `dml-main.xsd` |
| `a:alphaInv` | `CT_AlphaInverseEffect` | `dml-main.xsd` |
| `a:alphaMod` | `CT_AlphaModulateEffect`<br>`CT_PositivePercentage` | `dml-main.xsd` |
| `a:alphaModFix` | `CT_AlphaModulateFixedEffect` | `dml-main.xsd` |
| `a:alphaOff` | `CT_FixedPercentage` | `dml-main.xsd` |
| `a:alphaOutset` | `CT_AlphaOutsetEffect` | `dml-main.xsd` |
| `a:alphaRepl` | `CT_AlphaReplaceEffect` | `dml-main.xsd` |
| `a:anchor` | `CT_Point3D` | `dml-main.xsd` |
| `a:arcTo` | `CT_Path2DArcTo` | `dml-main.xsd` |
| `a:audioCd` | `CT_AudioCD` | `dml-main.xsd` |
| `a:audioFile` | `CT_AudioFile` | `dml-main.xsd` |
| `a:avLst` | `CT_GeomGuideList` | `dml-main.xsd` |
| `a:backdrop` | `CT_Backdrop` | `dml-main.xsd` |
| `a:band1H` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:band1V` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:band2H` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:band2V` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:bevel` | `CT_Bevel`<br>`CT_LineJoinBevel` | `dml-main.xsd` |
| `a:bevelB` | `CT_Bevel` | `dml-main.xsd` |
| `a:bevelT` | `CT_Bevel` | `dml-main.xsd` |
| `a:bgClr` | `CT_Color` | `dml-main.xsd` |
| `a:bgFillStyleLst` | `CT_BackgroundFillStyleList` | `dml-main.xsd` |
| `a:biLevel` | `CT_BiLevelEffect` | `dml-main.xsd` |
| `a:bldChart` | `CT_AnimationChartBuildProperties` | `dml-main.xsd` |
| `a:bldDgm` | `CT_AnimationDgmBuildProperties` | `dml-main.xsd` |
| `a:blend` | `CT_BlendEffect` | `dml-main.xsd` |
| `a:blip` | `CT_Blip` | `dml-main.xsd` |
| `a:blipFill` | `CT_BlipFillProperties` | `dml-main.xsd` |
| `a:blue` | `CT_Percentage` | `dml-main.xsd` |
| `a:blueMod` | `CT_Percentage` | `dml-main.xsd` |
| `a:blueOff` | `CT_Percentage` | `dml-main.xsd` |
| `a:blur` | `CT_BlurEffect` | `dml-main.xsd` |
| `a:bodyPr` | `CT_TextBodyProperties` | `dml-main.xsd` |
| `a:bottom` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:br` | `CT_TextLineBreak` | `dml-main.xsd` |
| `a:buAutoNum` | `CT_TextAutonumberBullet` | `dml-main.xsd` |
| `a:buBlip` | `CT_TextBlipBullet` | `dml-main.xsd` |
| `a:buChar` | `CT_TextCharBullet` | `dml-main.xsd` |
| `a:buClr` | `CT_Color` | `dml-main.xsd` |
| `a:buClrTx` | `CT_TextBulletColorFollowText` | `dml-main.xsd` |
| `a:buFont` | `CT_TextFont` | `dml-main.xsd` |
| `a:buFontTx` | `CT_TextBulletTypefaceFollowText` | `dml-main.xsd` |
| `a:buNone` | `CT_TextNoBullet` | `dml-main.xsd` |
| `a:buSzPct` | `CT_TextBulletSizePercent` | `dml-main.xsd` |
| `a:buSzPts` | `CT_TextBulletSizePoint` | `dml-main.xsd` |
| `a:buSzTx` | `CT_TextBulletSizeFollowText` | `dml-main.xsd` |
| `a:camera` | `CT_Camera` | `dml-main.xsd` |
| `a:cell3D` | `CT_Cell3D` | `dml-main.xsd` |
| `a:chart` | `CT_AnimationChartElement` | `dml-main.xsd` |
| `a:chExt` | `CT_PositiveSize2D` | `dml-main.xsd` |
| `a:chOff` | `CT_Point2D` | `dml-main.xsd` |
| `a:close` | `CT_Path2DClose` | `dml-main.xsd` |
| `a:clrChange` | `CT_ColorChangeEffect` | `dml-main.xsd` |
| `a:clrFrom` | `CT_Color` | `dml-main.xsd` |
| `a:clrMap` | `CT_ColorMapping` | `dml-main.xsd` |
| `a:clrRepl` | `CT_ColorReplaceEffect` | `dml-main.xsd` |
| `a:clrScheme` | `CT_ColorScheme` | `dml-main.xsd` |
| `a:clrTo` | `CT_Color` | `dml-main.xsd` |
| `a:cNvCxnSpPr` | `CT_NonVisualConnectorProperties` | `dml-main.xsd` |
| `a:cNvGraphicFramePr` | `CT_NonVisualGraphicFrameProperties` | `dml-main.xsd` |
| `a:cNvGrpSpPr` | `CT_NonVisualGroupDrawingShapeProps` | `dml-main.xsd` |
| `a:cNvPicPr` | `CT_NonVisualPictureProperties` | `dml-main.xsd` |
| `a:cNvPr` | `CT_NonVisualDrawingProps` | `dml-main.xsd` |
| `a:cNvSpPr` | `CT_NonVisualDrawingShapeProps` | `dml-main.xsd` |
| `a:comp` | `CT_ComplementTransform` | `dml-main.xsd` |
| `a:cont` | `CT_EffectContainer` | `dml-main.xsd` |
| `a:contourClr` | `CT_Color` | `dml-main.xsd` |
| `a:cpLocks` | `CT_ContentPartLocking` | `dml-main.xsd` |
| `a:cs` | `CT_TextFont` | `dml-main.xsd` |
| `a:cubicBezTo` | `CT_Path2DCubicBezierTo` | `dml-main.xsd` |
| `a:custClr` | `CT_CustomColor` | `dml-main.xsd` |
| `a:custClrLst` | `CT_CustomColorList` | `dml-main.xsd` |
| `a:custDash` | `CT_DashStopList` | `dml-main.xsd` |
| `a:custGeom` | `CT_CustomGeometry2D` | `dml-main.xsd` |
| `a:cxn` | `CT_ConnectionSite` | `dml-main.xsd` |
| `a:cxnLst` | `CT_ConnectionSiteList` | `dml-main.xsd` |
| `a:cxnSp` | `CT_GvmlConnector` | `dml-main.xsd` |
| `a:cxnSpLocks` | `CT_ConnectorLocking` | `dml-main.xsd` |
| `a:defPPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:defRPr` | `CT_TextCharacterProperties` | `dml-main.xsd` |
| `a:dgm` | `CT_AnimationDgmElement` | `dml-main.xsd` |
| `a:dk1` | `CT_Color` | `dml-main.xsd` |
| `a:dk2` | `CT_Color` | `dml-main.xsd` |
| `a:ds` | `CT_DashStop` | `dml-main.xsd` |
| `a:duotone` | `CT_DuotoneEffect` | `dml-main.xsd` |
| `a:ea` | `CT_TextFont` | `dml-main.xsd` |
| `a:effect` | `CT_EffectProperties`<br>`CT_EffectReference` | `dml-main.xsd` |
| `a:effectDag` | `CT_EffectContainer` | `dml-main.xsd` |
| `a:effectLst` | `CT_EffectList` | `dml-main.xsd` |
| `a:effectRef` | `CT_StyleMatrixReference` | `dml-main.xsd` |
| `a:effectStyle` | `CT_EffectStyleItem` | `dml-main.xsd` |
| `a:effectStyleLst` | `CT_EffectStyleList` | `dml-main.xsd` |
| `a:end` | `CT_AudioCDTime` | `dml-main.xsd` |
| `a:endCxn` | `CT_Connection` | `dml-main.xsd` |
| `a:endParaRPr` | `CT_TextCharacterProperties` | `dml-main.xsd` |
| `a:ext` | `CT_OfficeArtExtension`<br>`CT_PositiveSize2D` | `dml-main.xsd` |
| `a:extLst` | `CT_OfficeArtExtensionList` | `dml-main.xsd` |
| `a:extraClrScheme` | `CT_ColorSchemeAndMapping` | `dml-main.xsd` |
| `a:extraClrSchemeLst` | `CT_ColorSchemeList` | `dml-main.xsd` |
| `a:extrusionClr` | `CT_Color` | `dml-main.xsd` |
| `a:fgClr` | `CT_Color` | `dml-main.xsd` |
| `a:fill` | `CT_FillEffect`<br>`CT_FillProperties` | `dml-main.xsd` |
| `a:fillOverlay` | `CT_FillOverlayEffect` | `dml-main.xsd` |
| `a:fillRect` | `CT_RelativeRect` | `dml-main.xsd` |
| `a:fillRef` | `CT_StyleMatrixReference` | `dml-main.xsd` |
| `a:fillStyleLst` | `CT_FillStyleList` | `dml-main.xsd` |
| `a:fillToRect` | `CT_RelativeRect` | `dml-main.xsd` |
| `a:firstCol` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:firstRow` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:flatTx` | `CT_FlatText` | `dml-main.xsd` |
| `a:fld` | `CT_TextField` | `dml-main.xsd` |
| `a:fmtScheme` | `CT_StyleMatrix` | `dml-main.xsd` |
| `a:folHlink` | `CT_Color` | `dml-main.xsd` |
| `a:font` | `CT_FontCollection`<br>`CT_SupplementalFont` | `dml-main.xsd` |
| `a:fontRef` | `CT_FontReference` | `dml-main.xsd` |
| `a:fontScheme` | `CT_FontScheme` | `dml-main.xsd` |
| `a:gamma` | `CT_GammaTransform` | `dml-main.xsd` |
| `a:gd` | `CT_GeomGuide` | `dml-main.xsd` |
| `a:gdLst` | `CT_GeomGuideList` | `dml-main.xsd` |
| `a:glow` | `CT_GlowEffect` | `dml-main.xsd` |
| `a:gradFill` | `CT_GradientFillProperties` | `dml-main.xsd` |
| `a:graphic` | `CT_GraphicalObject` | `dml-main.xsd` |
| `a:graphicData` | `CT_GraphicalObjectData` | `dml-main.xsd` |
| `a:graphicFrame` | `CT_GvmlGraphicalObjectFrame` | `dml-main.xsd` |
| `a:graphicFrameLocks` | `CT_GraphicalObjectFrameLocking` | `dml-main.xsd` |
| `a:gray` | `CT_GrayscaleTransform` | `dml-main.xsd` |
| `a:grayscl` | `CT_GrayscaleEffect` | `dml-main.xsd` |
| `a:green` | `CT_Percentage` | `dml-main.xsd` |
| `a:greenMod` | `CT_Percentage` | `dml-main.xsd` |
| `a:greenOff` | `CT_Percentage` | `dml-main.xsd` |
| `a:gridCol` | `CT_TableCol` | `dml-main.xsd` |
| `a:grpFill` | `CT_GroupFillProperties` | `dml-main.xsd` |
| `a:grpSp` | `CT_GvmlGroupShape` | `dml-main.xsd` |
| `a:grpSpLocks` | `CT_GroupLocking` | `dml-main.xsd` |
| `a:grpSpPr` | `CT_GroupShapeProperties` | `dml-main.xsd` |
| `a:gs` | `CT_GradientStop` | `dml-main.xsd` |
| `a:gsLst` | `CT_GradientStopList` | `dml-main.xsd` |
| `a:headEnd` | `CT_LineEndProperties` | `dml-main.xsd` |
| `a:header` | `xsd:string` | `dml-main.xsd` |
| `a:headers` | `CT_Headers` | `dml-main.xsd` |
| `a:highlight` | `CT_Color` | `dml-main.xsd` |
| `a:hlink` | `CT_Color` | `dml-main.xsd` |
| `a:hlinkClick` | `CT_Hyperlink` | `dml-main.xsd` |
| `a:hlinkHover` | `CT_Hyperlink` | `dml-main.xsd` |
| `a:hlinkMouseOver` | `CT_Hyperlink` | `dml-main.xsd` |
| `a:hsl` | `CT_HSLEffect` | `dml-main.xsd` |
| `a:hslClr` | `CT_HslColor` | `dml-main.xsd` |
| `a:hue` | `CT_PositiveFixedAngle` | `dml-main.xsd` |
| `a:hueMod` | `CT_PositivePercentage` | `dml-main.xsd` |
| `a:hueOff` | `CT_Angle` | `dml-main.xsd` |
| `a:innerShdw` | `CT_InnerShadowEffect` | `dml-main.xsd` |
| `a:insideH` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:insideV` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:inv` | `CT_InverseTransform` | `dml-main.xsd` |
| `a:invGamma` | `CT_InverseGammaTransform` | `dml-main.xsd` |
| `a:lastCol` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:lastRow` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:latin` | `CT_TextFont` | `dml-main.xsd` |
| `a:left` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:lightRig` | `CT_LightRig` | `dml-main.xsd` |
| `a:lin` | `CT_LinearShadeProperties` | `dml-main.xsd` |
| `a:ln` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnB` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnBlToTr` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnDef` | `CT_DefaultShapeDefinition` | `dml-main.xsd` |
| `a:lnL` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnR` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnRef` | `CT_StyleMatrixReference` | `dml-main.xsd` |
| `a:lnSpc` | `CT_TextSpacing` | `dml-main.xsd` |
| `a:lnStyleLst` | `CT_LineStyleList` | `dml-main.xsd` |
| `a:lnT` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnTlToBr` | `CT_LineProperties` | `dml-main.xsd` |
| `a:lnTo` | `CT_Path2DLineTo` | `dml-main.xsd` |
| `a:lstStyle` | `CT_TextListStyle` | `dml-main.xsd` |
| `a:lt1` | `CT_Color` | `dml-main.xsd` |
| `a:lt2` | `CT_Color` | `dml-main.xsd` |
| `a:lum` | `CT_LuminanceEffect`<br>`CT_Percentage` | `dml-main.xsd` |
| `a:lumMod` | `CT_Percentage` | `dml-main.xsd` |
| `a:lumOff` | `CT_Percentage` | `dml-main.xsd` |
| `a:lvl1pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl2pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl3pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl4pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl5pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl6pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl7pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl8pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:lvl9pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:majorFont` | `CT_FontCollection` | `dml-main.xsd` |
| `a:masterClrMapping` | `CT_EmptyElement` | `dml-main.xsd` |
| `a:minorFont` | `CT_FontCollection` | `dml-main.xsd` |
| `a:miter` | `CT_LineJoinMiterProperties` | `dml-main.xsd` |
| `a:moveTo` | `CT_Path2DMoveTo` | `dml-main.xsd` |
| `a:neCell` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:noAutofit` | `CT_TextNoAutofit` | `dml-main.xsd` |
| `a:noFill` | `CT_NoFillProperties` | `dml-main.xsd` |
| `a:norm` | `CT_Vector3D` | `dml-main.xsd` |
| `a:normAutofit` | `CT_TextNormalAutofit` | `dml-main.xsd` |
| `a:nvCxnSpPr` | `CT_GvmlConnectorNonVisual` | `dml-main.xsd` |
| `a:nvGraphicFramePr` | `CT_GvmlGraphicFrameNonVisual` | `dml-main.xsd` |
| `a:nvGrpSpPr` | `CT_GvmlGroupShapeNonVisual` | `dml-main.xsd` |
| `a:nvPicPr` | `CT_GvmlPictureNonVisual` | `dml-main.xsd` |
| `a:nvSpPr` | `CT_GvmlShapeNonVisual` | `dml-main.xsd` |
| `a:nwCell` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:objectDefaults` | `CT_ObjectStyleDefaults` | `dml-main.xsd` |
| `a:off` | `CT_Point2D` | `dml-main.xsd` |
| `a:outerShdw` | `CT_OuterShadowEffect` | `dml-main.xsd` |
| `a:overrideClrMapping` | `CT_ColorMapping` | `dml-main.xsd` |
| `a:p` | `CT_TextParagraph` | `dml-main.xsd` |
| `a:path` | `CT_Path2D`<br>`CT_PathShadeProperties` | `dml-main.xsd` |
| `a:pathLst` | `CT_Path2DList` | `dml-main.xsd` |
| `a:pattFill` | `CT_PatternFillProperties` | `dml-main.xsd` |
| `a:pic` | `CT_GvmlPicture` | `dml-main.xsd` |
| `a:picLocks` | `CT_PictureLocking` | `dml-main.xsd` |
| `a:pos` | `CT_AdjPoint2D` | `dml-main.xsd` |
| `a:pPr` | `CT_TextParagraphProperties` | `dml-main.xsd` |
| `a:prstClr` | `CT_PresetColor` | `dml-main.xsd` |
| `a:prstDash` | `CT_PresetLineDashProperties` | `dml-main.xsd` |
| `a:prstGeom` | `CT_PresetGeometry2D` | `dml-main.xsd` |
| `a:prstShdw` | `CT_PresetShadowEffect` | `dml-main.xsd` |
| `a:prstTxWarp` | `CT_PresetTextShape` | `dml-main.xsd` |
| `a:pt` | `CT_AdjPoint2D` | `dml-main.xsd` |
| `a:quadBezTo` | `CT_Path2DQuadBezierTo` | `dml-main.xsd` |
| `a:quickTimeFile` | `CT_QuickTimeFile` | `dml-main.xsd` |
| `a:r` | `CT_RegularTextRun` | `dml-main.xsd` |
| `a:rect` | `CT_GeomRect` | `dml-main.xsd` |
| `a:red` | `CT_Percentage` | `dml-main.xsd` |
| `a:redMod` | `CT_Percentage` | `dml-main.xsd` |
| `a:redOff` | `CT_Percentage` | `dml-main.xsd` |
| `a:reflection` | `CT_ReflectionEffect` | `dml-main.xsd` |
| `a:relOff` | `CT_RelativeOffsetEffect` | `dml-main.xsd` |
| `a:right` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:rot` | `CT_SphereCoords` | `dml-main.xsd` |
| `a:round` | `CT_LineJoinRound` | `dml-main.xsd` |
| `a:rPr` | `CT_TextCharacterProperties` | `dml-main.xsd` |
| `a:rtl` | `CT_Boolean` | `dml-main.xsd` |
| `a:sat` | `CT_Percentage` | `dml-main.xsd` |
| `a:satMod` | `CT_Percentage` | `dml-main.xsd` |
| `a:satOff` | `CT_Percentage` | `dml-main.xsd` |
| `a:scene3d` | `CT_Scene3D` | `dml-main.xsd` |
| `a:schemeClr` | `CT_SchemeColor` | `dml-main.xsd` |
| `a:scrgbClr` | `CT_ScRgbColor` | `dml-main.xsd` |
| `a:seCell` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:shade` | `CT_PositiveFixedPercentage` | `dml-main.xsd` |
| `a:snd` | `CT_EmbeddedWAVAudioFile` | `dml-main.xsd` |
| `a:softEdge` | `CT_SoftEdgesEffect` | `dml-main.xsd` |
| `a:solidFill` | `CT_SolidColorFillProperties` | `dml-main.xsd` |
| `a:sp` | `CT_GvmlShape` | `dml-main.xsd` |
| `a:sp3d` | `CT_Shape3D` | `dml-main.xsd` |
| `a:spAutoFit` | `CT_TextShapeAutofit` | `dml-main.xsd` |
| `a:spcAft` | `CT_TextSpacing` | `dml-main.xsd` |
| `a:spcBef` | `CT_TextSpacing` | `dml-main.xsd` |
| `a:spcPct` | `CT_TextSpacingPercent` | `dml-main.xsd` |
| `a:spcPts` | `CT_TextSpacingPoint` | `dml-main.xsd` |
| `a:spDef` | `CT_DefaultShapeDefinition` | `dml-main.xsd` |
| `a:spLocks` | `CT_ShapeLocking` | `dml-main.xsd` |
| `a:spPr` | `CT_ShapeProperties` | `dml-main.xsd` |
| `a:srcRect` | `CT_RelativeRect` | `dml-main.xsd` |
| `a:srgbClr` | `CT_SRgbColor` | `dml-main.xsd` |
| `a:st` | `CT_AudioCDTime` | `dml-main.xsd` |
| `a:stCxn` | `CT_Connection` | `dml-main.xsd` |
| `a:stretch` | `CT_StretchInfoProperties` | `dml-main.xsd` |
| `a:style` | `CT_ShapeStyle` | `dml-main.xsd` |
| `a:swCell` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:sx` | `CT_Ratio` | `dml-main.xsd` |
| `a:sy` | `CT_Ratio` | `dml-main.xsd` |
| `a:sym` | `CT_TextFont` | `dml-main.xsd` |
| `a:sysClr` | `CT_SystemColor` | `dml-main.xsd` |
| `a:t` | `xsd:string` | `dml-main.xsd` |
| `a:tab` | `CT_TextTabStop` | `dml-main.xsd` |
| `a:tableStyle` | `CT_TableStyle` | `dml-main.xsd` |
| `a:tableStyleId` | `s:ST_Guid` | `dml-main.xsd` |
| `a:tabLst` | `CT_TextTabStopList` | `dml-main.xsd` |
| `a:tailEnd` | `CT_LineEndProperties` | `dml-main.xsd` |
| `a:tbl` | `CT_Table` | `dml-main.xsd` |
| `a:tblBg` | `CT_TableBackgroundStyle` | `dml-main.xsd` |
| `a:tblGrid` | `CT_TableGrid` | `dml-main.xsd` |
| `a:tblPr` | `CT_TableProperties` | `dml-main.xsd` |
| `a:tblStyle` | `CT_TableStyle` | `dml-main.xsd` |
| `a:tblStyleLst` | `CT_TableStyleList` | `dml-main.xsd` |
| `a:tc` | `CT_TableCell` | `dml-main.xsd` |
| `a:tcBdr` | `CT_TableCellBorderStyle` | `dml-main.xsd` |
| `a:tcPr` | `CT_TableCellProperties` | `dml-main.xsd` |
| `a:tcStyle` | `CT_TableStyleCellStyle` | `dml-main.xsd` |
| `a:tcTxStyle` | `CT_TableStyleTextStyle` | `dml-main.xsd` |
| `a:theme` | `CT_OfficeStyleSheet` | `dml-main.xsd` |
| `a:themeElements` | `CT_BaseStyles` | `dml-main.xsd` |
| `a:themeManager` | `CT_EmptyElement` | `dml-main.xsd` |
| `a:themeOverride` | `CT_BaseStylesOverride` | `dml-main.xsd` |
| `a:tile` | `CT_TileInfoProperties` | `dml-main.xsd` |
| `a:tileRect` | `CT_RelativeRect` | `dml-main.xsd` |
| `a:tint` | `CT_PositiveFixedPercentage`<br>`CT_TintEffect` | `dml-main.xsd` |
| `a:tl2br` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:top` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:tr` | `CT_TableRow` | `dml-main.xsd` |
| `a:tr2bl` | `CT_ThemeableLineStyle` | `dml-main.xsd` |
| `a:txBody` | `CT_TextBody` | `dml-main.xsd` |
| `a:txDef` | `CT_DefaultShapeDefinition` | `dml-main.xsd` |
| `a:txSp` | `CT_GvmlTextShape` | `dml-main.xsd` |
| `a:uFill` | `CT_TextUnderlineFillGroupWrapper` | `dml-main.xsd` |
| `a:uFillTx` | `CT_TextUnderlineFillFollowText` | `dml-main.xsd` |
| `a:uLn` | `CT_LineProperties` | `dml-main.xsd` |
| `a:uLnTx` | `CT_TextUnderlineLineFollowText` | `dml-main.xsd` |
| `a:up` | `CT_Vector3D` | `dml-main.xsd` |
| `a:useSpRect` | `CT_GvmlUseShapeRectangle` | `dml-main.xsd` |
| `a:videoFile` | `CT_VideoFile` | `dml-main.xsd` |
| `a:wavAudioFile` | `CT_EmbeddedWAVAudioFile` | `dml-main.xsd` |
| `a:wholeTbl` | `CT_TablePartStyle` | `dml-main.xsd` |
| `a:xfrm` | `CT_GroupTransform2D`<br>`CT_Transform2D`<br>`CT_TransformEffect` | `dml-main.xsd` |
| `ac:additionalCharacteristics` | `CT_AdditionalCharacteristics` | `shared-additionalCharacteristics.xsd` |
| `ac:characteristic` | `CT_Characteristic` | `shared-additionalCharacteristics.xsd` |
| `b:AbbreviatedCaseNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:AlbumTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Artist` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Author` | `CT_AuthorType`<br>`CT_NameOrCorporateType` | `shared-bibliography.xsd` |
| `b:BookAuthor` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:BookTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Broadcaster` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:BroadcastTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:CaseNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:ChapterNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:City` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Comments` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Compiler` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Composer` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Conductor` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:ConferenceName` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Corporate` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Counsel` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:CountryRegion` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Court` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Day` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:DayAccessed` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Department` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Director` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Distributor` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Edition` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Editor` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:First` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Guid` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Institution` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:InternetSiteTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Interviewee` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Interviewer` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Inventor` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Issue` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:JournalName` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Last` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:LCID` | `s:ST_Lang` | `shared-bibliography.xsd` |
| `b:Medium` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Middle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Month` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:MonthAccessed` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:NameList` | `CT_NameListType` | `shared-bibliography.xsd` |
| `b:NumberVolumes` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Pages` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:PatentNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Performer` | `CT_NameOrCorporateType` | `shared-bibliography.xsd` |
| `b:PeriodicalTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Person` | `CT_PersonType` | `shared-bibliography.xsd` |
| `b:ProducerName` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:ProductionCompany` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:PublicationTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Publisher` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:RecordingNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:RefOrder` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Reporter` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:ShortTitle` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Source` | `CT_SourceType` | `shared-bibliography.xsd` |
| `b:Sources` | `CT_Sources` | `shared-bibliography.xsd` |
| `b:SourceType` | `ST_SourceType` | `shared-bibliography.xsd` |
| `b:StandardNumber` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:StateProvince` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Station` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Tag` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Theater` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:ThesisType` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Title` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Translator` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Type` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:URL` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Version` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Volume` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:Writer` | `CT_NameType` | `shared-bibliography.xsd` |
| `b:Year` | `s:ST_String` | `shared-bibliography.xsd` |
| `b:YearAccessed` | `s:ST_String` | `shared-bibliography.xsd` |
| `c:applyToEnd` | `CT_Boolean` | `dml-chart.xsd` |
| `c:applyToFront` | `CT_Boolean` | `dml-chart.xsd` |
| `c:applyToSides` | `CT_Boolean` | `dml-chart.xsd` |
| `c:area3DChart` | `CT_Area3DChart` | `dml-chart.xsd` |
| `c:areaChart` | `CT_AreaChart` | `dml-chart.xsd` |
| `c:auto` | `CT_Boolean` | `dml-chart.xsd` |
| `c:autoTitleDeleted` | `CT_Boolean` | `dml-chart.xsd` |
| `c:autoUpdate` | `CT_Boolean` | `dml-chart.xsd` |
| `c:axId` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:axPos` | `CT_AxPos` | `dml-chart.xsd` |
| `c:backWall` | `CT_Surface` | `dml-chart.xsd` |
| `c:backward` | `CT_Double` | `dml-chart.xsd` |
| `c:bandFmt` | `CT_BandFmt` | `dml-chart.xsd` |
| `c:bandFmts` | `CT_BandFmts` | `dml-chart.xsd` |
| `c:bar3DChart` | `CT_Bar3DChart` | `dml-chart.xsd` |
| `c:barChart` | `CT_BarChart` | `dml-chart.xsd` |
| `c:barDir` | `CT_BarDir` | `dml-chart.xsd` |
| `c:baseTimeUnit` | `CT_TimeUnit` | `dml-chart.xsd` |
| `c:bubble3D` | `CT_Boolean` | `dml-chart.xsd` |
| `c:bubbleChart` | `CT_BubbleChart` | `dml-chart.xsd` |
| `c:bubbleScale` | `CT_BubbleScale` | `dml-chart.xsd` |
| `c:bubbleSize` | `CT_NumDataSource` | `dml-chart.xsd` |
| `c:builtInUnit` | `CT_BuiltInUnit` | `dml-chart.xsd` |
| `c:cat` | `CT_AxDataSource` | `dml-chart.xsd` |
| `c:catAx` | `CT_CatAx` | `dml-chart.xsd` |
| `c:chart` | `CT_Chart`<br>`CT_RelId` | `dml-chart.xsd` |
| `c:chartObject` | `CT_Boolean` | `dml-chart.xsd` |
| `c:chartSpace` | `CT_ChartSpace` | `dml-chart.xsd` |
| `c:clrMapOvr` | `a:CT_ColorMapping` | `dml-chart.xsd` |
| `c:crossAx` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:crossBetween` | `CT_CrossBetween` | `dml-chart.xsd` |
| `c:crosses` | `CT_Crosses` | `dml-chart.xsd` |
| `c:crossesAt` | `CT_Double` | `dml-chart.xsd` |
| `c:custSplit` | `CT_CustSplit` | `dml-chart.xsd` |
| `c:custUnit` | `CT_Double` | `dml-chart.xsd` |
| `c:data` | `CT_Boolean` | `dml-chart.xsd` |
| `c:date1904` | `CT_Boolean` | `dml-chart.xsd` |
| `c:dateAx` | `CT_DateAx` | `dml-chart.xsd` |
| `c:delete` | `CT_Boolean` | `dml-chart.xsd` |
| `c:depthPercent` | `CT_DepthPercent` | `dml-chart.xsd` |
| `c:dispBlanksAs` | `CT_DispBlanksAs` | `dml-chart.xsd` |
| `c:dispEq` | `CT_Boolean` | `dml-chart.xsd` |
| `c:dispRSqr` | `CT_Boolean` | `dml-chart.xsd` |
| `c:dispUnits` | `CT_DispUnits` | `dml-chart.xsd` |
| `c:dispUnitsLbl` | `CT_DispUnitsLbl` | `dml-chart.xsd` |
| `c:dLbl` | `CT_DLbl` | `dml-chart.xsd` |
| `c:dLblPos` | `CT_DLblPos` | `dml-chart.xsd` |
| `c:dLbls` | `CT_DLbls` | `dml-chart.xsd` |
| `c:doughnutChart` | `CT_DoughnutChart` | `dml-chart.xsd` |
| `c:downBars` | `CT_UpDownBar` | `dml-chart.xsd` |
| `c:dPt` | `CT_DPt` | `dml-chart.xsd` |
| `c:dropLines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:dTable` | `CT_DTable` | `dml-chart.xsd` |
| `c:errBars` | `CT_ErrBars` | `dml-chart.xsd` |
| `c:errBarType` | `CT_ErrBarType` | `dml-chart.xsd` |
| `c:errDir` | `CT_ErrDir` | `dml-chart.xsd` |
| `c:errValType` | `CT_ErrValType` | `dml-chart.xsd` |
| `c:evenFooter` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:evenHeader` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:explosion` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:ext` | `CT_Extension` | `dml-chart.xsd` |
| `c:externalData` | `CT_ExternalData` | `dml-chart.xsd` |
| `c:extLst` | `CT_ExtensionList` | `dml-chart.xsd` |
| `c:f` | `xsd:string` | `dml-chart.xsd` |
| `c:firstFooter` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:firstHeader` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:firstSliceAng` | `CT_FirstSliceAng` | `dml-chart.xsd` |
| `c:floor` | `CT_Surface` | `dml-chart.xsd` |
| `c:fmtId` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:formatCode` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:formatting` | `CT_Boolean` | `dml-chart.xsd` |
| `c:forward` | `CT_Double` | `dml-chart.xsd` |
| `c:gapDepth` | `CT_GapAmount` | `dml-chart.xsd` |
| `c:gapWidth` | `CT_GapAmount` | `dml-chart.xsd` |
| `c:grouping` | `CT_BarGrouping`<br>`CT_Grouping` | `dml-chart.xsd` |
| `c:h` | `CT_Double` | `dml-chart.xsd` |
| `c:headerFooter` | `CT_HeaderFooter` | `dml-chart.xsd` |
| `c:hiLowLines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:hMode` | `CT_LayoutMode` | `dml-chart.xsd` |
| `c:holeSize` | `CT_HoleSize` | `dml-chart.xsd` |
| `c:hPercent` | `CT_HPercent` | `dml-chart.xsd` |
| `c:idx` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:intercept` | `CT_Double` | `dml-chart.xsd` |
| `c:invertIfNegative` | `CT_Boolean` | `dml-chart.xsd` |
| `c:lang` | `CT_TextLanguageID` | `dml-chart.xsd` |
| `c:layout` | `CT_Layout` | `dml-chart.xsd` |
| `c:layoutTarget` | `CT_LayoutTarget` | `dml-chart.xsd` |
| `c:lblAlgn` | `CT_LblAlgn` | `dml-chart.xsd` |
| `c:lblOffset` | `CT_LblOffset` | `dml-chart.xsd` |
| `c:leaderLines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:legacyDrawingHF` | `CT_RelId` | `dml-chart.xsd` |
| `c:legend` | `CT_Legend` | `dml-chart.xsd` |
| `c:legendEntry` | `CT_LegendEntry` | `dml-chart.xsd` |
| `c:legendPos` | `CT_LegendPos` | `dml-chart.xsd` |
| `c:line3DChart` | `CT_Line3DChart` | `dml-chart.xsd` |
| `c:lineChart` | `CT_LineChart` | `dml-chart.xsd` |
| `c:logBase` | `CT_LogBase` | `dml-chart.xsd` |
| `c:lvl` | `CT_Lvl` | `dml-chart.xsd` |
| `c:majorGridlines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:majorTickMark` | `CT_TickMark` | `dml-chart.xsd` |
| `c:majorTimeUnit` | `CT_TimeUnit` | `dml-chart.xsd` |
| `c:majorUnit` | `CT_AxisUnit` | `dml-chart.xsd` |
| `c:manualLayout` | `CT_ManualLayout` | `dml-chart.xsd` |
| `c:marker` | `CT_Boolean`<br>`CT_Marker` | `dml-chart.xsd` |
| `c:max` | `CT_Double` | `dml-chart.xsd` |
| `c:min` | `CT_Double` | `dml-chart.xsd` |
| `c:minorGridlines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:minorTickMark` | `CT_TickMark` | `dml-chart.xsd` |
| `c:minorTimeUnit` | `CT_TimeUnit` | `dml-chart.xsd` |
| `c:minorUnit` | `CT_AxisUnit` | `dml-chart.xsd` |
| `c:minus` | `CT_NumDataSource` | `dml-chart.xsd` |
| `c:multiLvlStrCache` | `CT_MultiLvlStrData` | `dml-chart.xsd` |
| `c:multiLvlStrRef` | `CT_MultiLvlStrRef` | `dml-chart.xsd` |
| `c:name` | `s:ST_Xstring`<br>`xsd:string` | `dml-chart.xsd` |
| `c:noEndCap` | `CT_Boolean` | `dml-chart.xsd` |
| `c:noMultiLvlLbl` | `CT_Boolean` | `dml-chart.xsd` |
| `c:numCache` | `CT_NumData` | `dml-chart.xsd` |
| `c:numFmt` | `CT_NumFmt` | `dml-chart.xsd` |
| `c:numLit` | `CT_NumData` | `dml-chart.xsd` |
| `c:numRef` | `CT_NumRef` | `dml-chart.xsd` |
| `c:oddFooter` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:oddHeader` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:ofPieChart` | `CT_OfPieChart` | `dml-chart.xsd` |
| `c:ofPieType` | `CT_OfPieType` | `dml-chart.xsd` |
| `c:order` | `CT_Order`<br>`CT_UnsignedInt` | `dml-chart.xsd` |
| `c:orientation` | `CT_Orientation` | `dml-chart.xsd` |
| `c:overlap` | `CT_Overlap` | `dml-chart.xsd` |
| `c:overlay` | `CT_Boolean` | `dml-chart.xsd` |
| `c:pageMargins` | `CT_PageMargins` | `dml-chart.xsd` |
| `c:pageSetup` | `CT_PageSetup` | `dml-chart.xsd` |
| `c:period` | `CT_Period` | `dml-chart.xsd` |
| `c:perspective` | `CT_Perspective` | `dml-chart.xsd` |
| `c:pictureFormat` | `CT_PictureFormat` | `dml-chart.xsd` |
| `c:pictureOptions` | `CT_PictureOptions` | `dml-chart.xsd` |
| `c:pictureStackUnit` | `CT_PictureStackUnit` | `dml-chart.xsd` |
| `c:pie3DChart` | `CT_Pie3DChart` | `dml-chart.xsd` |
| `c:pieChart` | `CT_PieChart` | `dml-chart.xsd` |
| `c:pivotFmt` | `CT_PivotFmt` | `dml-chart.xsd` |
| `c:pivotFmts` | `CT_PivotFmts` | `dml-chart.xsd` |
| `c:pivotSource` | `CT_PivotSource` | `dml-chart.xsd` |
| `c:plotArea` | `CT_PlotArea` | `dml-chart.xsd` |
| `c:plotVisOnly` | `CT_Boolean` | `dml-chart.xsd` |
| `c:plus` | `CT_NumDataSource` | `dml-chart.xsd` |
| `c:printSettings` | `CT_PrintSettings` | `dml-chart.xsd` |
| `c:protection` | `CT_Protection` | `dml-chart.xsd` |
| `c:pt` | `CT_NumVal`<br>`CT_StrVal` | `dml-chart.xsd` |
| `c:ptCount` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:radarChart` | `CT_RadarChart` | `dml-chart.xsd` |
| `c:radarStyle` | `CT_RadarStyle` | `dml-chart.xsd` |
| `c:rAngAx` | `CT_Boolean` | `dml-chart.xsd` |
| `c:rich` | `a:CT_TextBody` | `dml-chart.xsd` |
| `c:rotX` | `CT_RotX` | `dml-chart.xsd` |
| `c:rotY` | `CT_RotY` | `dml-chart.xsd` |
| `c:roundedCorners` | `CT_Boolean` | `dml-chart.xsd` |
| `c:scaling` | `CT_Scaling` | `dml-chart.xsd` |
| `c:scatterChart` | `CT_ScatterChart` | `dml-chart.xsd` |
| `c:scatterStyle` | `CT_ScatterStyle` | `dml-chart.xsd` |
| `c:secondPiePt` | `CT_UnsignedInt` | `dml-chart.xsd` |
| `c:secondPieSize` | `CT_SecondPieSize` | `dml-chart.xsd` |
| `c:selection` | `CT_Boolean` | `dml-chart.xsd` |
| `c:separator` | `xsd:string` | `dml-chart.xsd` |
| `c:ser` | `CT_AreaSer`<br>`CT_BarSer`<br>`CT_BubbleSer`<br>`CT_LineSer`<br>`CT_PieSer`<br>`CT_RadarSer`<br>`CT_ScatterSer`<br>`CT_SurfaceSer` | `dml-chart.xsd` |
| `c:serAx` | `CT_SerAx` | `dml-chart.xsd` |
| `c:serLines` | `CT_ChartLines` | `dml-chart.xsd` |
| `c:shape` | `CT_Shape` | `dml-chart.xsd` |
| `c:showBubbleSize` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showCatName` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showDLblsOverMax` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showHorzBorder` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showKeys` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showLeaderLines` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showLegendKey` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showNegBubbles` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showOutline` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showPercent` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showSerName` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showVal` | `CT_Boolean` | `dml-chart.xsd` |
| `c:showVertBorder` | `CT_Boolean` | `dml-chart.xsd` |
| `c:sideWall` | `CT_Surface` | `dml-chart.xsd` |
| `c:size` | `CT_MarkerSize` | `dml-chart.xsd` |
| `c:sizeRepresents` | `CT_SizeRepresents` | `dml-chart.xsd` |
| `c:smooth` | `CT_Boolean` | `dml-chart.xsd` |
| `c:splitPos` | `CT_Double` | `dml-chart.xsd` |
| `c:splitType` | `CT_SplitType` | `dml-chart.xsd` |
| `c:spPr` | `a:CT_ShapeProperties` | `dml-chart.xsd` |
| `c:stockChart` | `CT_StockChart` | `dml-chart.xsd` |
| `c:strCache` | `CT_StrData` | `dml-chart.xsd` |
| `c:strLit` | `CT_StrData` | `dml-chart.xsd` |
| `c:strRef` | `CT_StrRef` | `dml-chart.xsd` |
| `c:style` | `CT_Style` | `dml-chart.xsd` |
| `c:surface3DChart` | `CT_Surface3DChart` | `dml-chart.xsd` |
| `c:surfaceChart` | `CT_SurfaceChart` | `dml-chart.xsd` |
| `c:symbol` | `CT_MarkerStyle` | `dml-chart.xsd` |
| `c:thickness` | `CT_Thickness` | `dml-chart.xsd` |
| `c:tickLblPos` | `CT_TickLblPos` | `dml-chart.xsd` |
| `c:tickLblSkip` | `CT_Skip` | `dml-chart.xsd` |
| `c:tickMarkSkip` | `CT_Skip` | `dml-chart.xsd` |
| `c:title` | `CT_Title` | `dml-chart.xsd` |
| `c:trendline` | `CT_Trendline` | `dml-chart.xsd` |
| `c:trendlineLbl` | `CT_TrendlineLbl` | `dml-chart.xsd` |
| `c:trendlineType` | `CT_TrendlineType` | `dml-chart.xsd` |
| `c:tx` | `CT_SerTx`<br>`CT_Tx` | `dml-chart.xsd` |
| `c:txPr` | `a:CT_TextBody` | `dml-chart.xsd` |
| `c:upBars` | `CT_UpDownBar` | `dml-chart.xsd` |
| `c:upDownBars` | `CT_UpDownBars` | `dml-chart.xsd` |
| `c:userInterface` | `CT_Boolean` | `dml-chart.xsd` |
| `c:userShapes` | `CT_RelId`<br>`cdr:CT_Drawing` | `dml-chart.xsd` |
| `c:v` | `s:ST_Xstring` | `dml-chart.xsd` |
| `c:val` | `CT_Double`<br>`CT_NumDataSource` | `dml-chart.xsd` |
| `c:valAx` | `CT_ValAx` | `dml-chart.xsd` |
| `c:varyColors` | `CT_Boolean` | `dml-chart.xsd` |
| `c:view3D` | `CT_View3D` | `dml-chart.xsd` |
| `c:w` | `CT_Double` | `dml-chart.xsd` |
| `c:wireframe` | `CT_Boolean` | `dml-chart.xsd` |
| `c:wMode` | `CT_LayoutMode` | `dml-chart.xsd` |
| `c:x` | `CT_Double` | `dml-chart.xsd` |
| `c:xMode` | `CT_LayoutMode` | `dml-chart.xsd` |
| `c:xVal` | `CT_AxDataSource` | `dml-chart.xsd` |
| `c:y` | `CT_Double` | `dml-chart.xsd` |
| `c:yMode` | `CT_LayoutMode` | `dml-chart.xsd` |
| `c:yVal` | `CT_NumDataSource` | `dml-chart.xsd` |
| `cdr:absSizeAnchor` | `CT_AbsSizeAnchor` | `dml-chartDrawing.xsd` |
| `cdr:blipFill` | `a:CT_BlipFillProperties` | `dml-chartDrawing.xsd` |
| `cdr:cNvCxnSpPr` | `a:CT_NonVisualConnectorProperties` | `dml-chartDrawing.xsd` |
| `cdr:cNvGraphicFramePr` | `a:CT_NonVisualGraphicFrameProperties` | `dml-chartDrawing.xsd` |
| `cdr:cNvGrpSpPr` | `a:CT_NonVisualGroupDrawingShapeProps` | `dml-chartDrawing.xsd` |
| `cdr:cNvPicPr` | `a:CT_NonVisualPictureProperties` | `dml-chartDrawing.xsd` |
| `cdr:cNvPr` | `a:CT_NonVisualDrawingProps` | `dml-chartDrawing.xsd` |
| `cdr:cNvSpPr` | `a:CT_NonVisualDrawingShapeProps` | `dml-chartDrawing.xsd` |
| `cdr:cxnSp` | `CT_Connector` | `dml-chartDrawing.xsd` |
| `cdr:ext` | `a:CT_PositiveSize2D` | `dml-chartDrawing.xsd` |
| `cdr:from` | `CT_Marker` | `dml-chartDrawing.xsd` |
| `cdr:graphicFrame` | `CT_GraphicFrame` | `dml-chartDrawing.xsd` |
| `cdr:grpSp` | `CT_GroupShape` | `dml-chartDrawing.xsd` |
| `cdr:grpSpPr` | `a:CT_GroupShapeProperties` | `dml-chartDrawing.xsd` |
| `cdr:nvCxnSpPr` | `CT_ConnectorNonVisual` | `dml-chartDrawing.xsd` |
| `cdr:nvGraphicFramePr` | `CT_GraphicFrameNonVisual` | `dml-chartDrawing.xsd` |
| `cdr:nvGrpSpPr` | `CT_GroupShapeNonVisual` | `dml-chartDrawing.xsd` |
| `cdr:nvPicPr` | `CT_PictureNonVisual` | `dml-chartDrawing.xsd` |
| `cdr:nvSpPr` | `CT_ShapeNonVisual` | `dml-chartDrawing.xsd` |
| `cdr:pic` | `CT_Picture` | `dml-chartDrawing.xsd` |
| `cdr:relSizeAnchor` | `CT_RelSizeAnchor` | `dml-chartDrawing.xsd` |
| `cdr:sp` | `CT_Shape` | `dml-chartDrawing.xsd` |
| `cdr:spPr` | `a:CT_ShapeProperties` | `dml-chartDrawing.xsd` |
| `cdr:style` | `a:CT_ShapeStyle` | `dml-chartDrawing.xsd` |
| `cdr:to` | `CT_Marker` | `dml-chartDrawing.xsd` |
| `cdr:txBody` | `a:CT_TextBody` | `dml-chartDrawing.xsd` |
| `cdr:x` | `ST_MarkerCoordinate` | `dml-chartDrawing.xsd` |
| `cdr:xfrm` | `a:CT_Transform2D` | `dml-chartDrawing.xsd` |
| `cdr:y` | `ST_MarkerCoordinate` | `dml-chartDrawing.xsd` |
| `cp:Properties` | `CT_Properties` | `shared-documentPropertiesCustom.xsd` |
| `cp:property` | `CT_Property` | `shared-documentPropertiesCustom.xsd` |
| `dgm:adj` | `CT_Adj` | `dml-diagram.xsd` |
| `dgm:adjLst` | `CT_AdjLst` | `dml-diagram.xsd` |
| `dgm:alg` | `CT_Algorithm` | `dml-diagram.xsd` |
| `dgm:animLvl` | `CT_AnimLvl` | `dml-diagram.xsd` |
| `dgm:animOne` | `CT_AnimOne` | `dml-diagram.xsd` |
| `dgm:bg` | `a:CT_BackgroundFormatting` | `dml-diagram.xsd` |
| `dgm:bulletEnabled` | `CT_BulletEnabled` | `dml-diagram.xsd` |
| `dgm:cat` | `CT_CTCategory`<br>`CT_Category`<br>`CT_SDCategory` | `dml-diagram.xsd` |
| `dgm:catLst` | `CT_CTCategories`<br>`CT_Categories`<br>`CT_SDCategories` | `dml-diagram.xsd` |
| `dgm:chMax` | `CT_ChildMax` | `dml-diagram.xsd` |
| `dgm:choose` | `CT_Choose` | `dml-diagram.xsd` |
| `dgm:chPref` | `CT_ChildPref` | `dml-diagram.xsd` |
| `dgm:clrData` | `CT_SampleData` | `dml-diagram.xsd` |
| `dgm:colorsDef` | `CT_ColorTransform` | `dml-diagram.xsd` |
| `dgm:colorsDefHdr` | `CT_ColorTransformHeader` | `dml-diagram.xsd` |
| `dgm:colorsDefHdrLst` | `CT_ColorTransformHeaderLst` | `dml-diagram.xsd` |
| `dgm:constr` | `CT_Constraint` | `dml-diagram.xsd` |
| `dgm:constrLst` | `CT_Constraints` | `dml-diagram.xsd` |
| `dgm:cxn` | `CT_Cxn` | `dml-diagram.xsd` |
| `dgm:cxnLst` | `CT_CxnList` | `dml-diagram.xsd` |
| `dgm:dataModel` | `CT_DataModel` | `dml-diagram.xsd` |
| `dgm:desc` | `CT_CTDescription`<br>`CT_Description`<br>`CT_SDDescription` | `dml-diagram.xsd` |
| `dgm:dir` | `CT_Direction` | `dml-diagram.xsd` |
| `dgm:effectClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:else` | `CT_Otherwise` | `dml-diagram.xsd` |
| `dgm:extLst` | `a:CT_OfficeArtExtensionList` | `dml-diagram.xsd` |
| `dgm:fillClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:forEach` | `CT_ForEach` | `dml-diagram.xsd` |
| `dgm:hierBranch` | `CT_HierBranchStyle` | `dml-diagram.xsd` |
| `dgm:if` | `CT_When` | `dml-diagram.xsd` |
| `dgm:layoutDef` | `CT_DiagramDefinition` | `dml-diagram.xsd` |
| `dgm:layoutDefHdr` | `CT_DiagramDefinitionHeader` | `dml-diagram.xsd` |
| `dgm:layoutDefHdrLst` | `CT_DiagramDefinitionHeaderLst` | `dml-diagram.xsd` |
| `dgm:layoutNode` | `CT_LayoutNode` | `dml-diagram.xsd` |
| `dgm:linClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:orgChart` | `CT_OrgChart` | `dml-diagram.xsd` |
| `dgm:param` | `CT_Parameter` | `dml-diagram.xsd` |
| `dgm:presLayoutVars` | `CT_LayoutVariablePropertySet` | `dml-diagram.xsd` |
| `dgm:presOf` | `CT_PresentationOf` | `dml-diagram.xsd` |
| `dgm:prSet` | `CT_ElemPropSet` | `dml-diagram.xsd` |
| `dgm:pt` | `CT_Pt` | `dml-diagram.xsd` |
| `dgm:ptLst` | `CT_PtList` | `dml-diagram.xsd` |
| `dgm:relIds` | `CT_RelIds` | `dml-diagram.xsd` |
| `dgm:resizeHandles` | `CT_ResizeHandles` | `dml-diagram.xsd` |
| `dgm:rule` | `CT_NumericRule` | `dml-diagram.xsd` |
| `dgm:ruleLst` | `CT_Rules` | `dml-diagram.xsd` |
| `dgm:sampData` | `CT_SampleData` | `dml-diagram.xsd` |
| `dgm:scene3d` | `a:CT_Scene3D` | `dml-diagram.xsd` |
| `dgm:shape` | `CT_Shape` | `dml-diagram.xsd` |
| `dgm:sp3d` | `a:CT_Shape3D` | `dml-diagram.xsd` |
| `dgm:spPr` | `a:CT_ShapeProperties` | `dml-diagram.xsd` |
| `dgm:style` | `a:CT_ShapeStyle` | `dml-diagram.xsd` |
| `dgm:styleData` | `CT_SampleData` | `dml-diagram.xsd` |
| `dgm:styleDef` | `CT_StyleDefinition` | `dml-diagram.xsd` |
| `dgm:styleDefHdr` | `CT_StyleDefinitionHeader` | `dml-diagram.xsd` |
| `dgm:styleDefHdrLst` | `CT_StyleDefinitionHeaderLst` | `dml-diagram.xsd` |
| `dgm:styleLbl` | `CT_CTStyleLabel`<br>`CT_StyleLabel` | `dml-diagram.xsd` |
| `dgm:t` | `a:CT_TextBody` | `dml-diagram.xsd` |
| `dgm:title` | `CT_CTName`<br>`CT_Name`<br>`CT_SDName` | `dml-diagram.xsd` |
| `dgm:txEffectClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:txFillClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:txLinClrLst` | `CT_Colors` | `dml-diagram.xsd` |
| `dgm:txPr` | `CT_TextProps` | `dml-diagram.xsd` |
| `dgm:varLst` | `CT_LayoutVariablePropertySet` | `dml-diagram.xsd` |
| `dgm:whole` | `a:CT_WholeE2oFormatting` | `dml-diagram.xsd` |
| `ds:datastoreItem` | `CT_DatastoreItem` | `shared-customXmlDataProperties.xsd` |
| `ds:schemaRef` | `CT_DatastoreSchemaRef` | `shared-customXmlDataProperties.xsd` |
| `ds:schemaRefs` | `CT_DatastoreSchemaRefs` | `shared-customXmlDataProperties.xsd` |
| `ep:Application` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:AppVersion` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:Characters` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:CharactersWithSpaces` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Company` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:DigSig` | `CT_DigSigBlob` | `shared-documentPropertiesExtended.xsd` |
| `ep:DocSecurity` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:HeadingPairs` | `CT_VectorVariant` | `shared-documentPropertiesExtended.xsd` |
| `ep:HiddenSlides` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:HLinks` | `CT_VectorVariant` | `shared-documentPropertiesExtended.xsd` |
| `ep:HyperlinkBase` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:HyperlinksChanged` | `xsd:boolean` | `shared-documentPropertiesExtended.xsd` |
| `ep:Lines` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:LinksUpToDate` | `xsd:boolean` | `shared-documentPropertiesExtended.xsd` |
| `ep:Manager` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:MMClips` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Notes` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Pages` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Paragraphs` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:PresentationFormat` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:Properties` | `CT_Properties` | `shared-documentPropertiesExtended.xsd` |
| `ep:ScaleCrop` | `xsd:boolean` | `shared-documentPropertiesExtended.xsd` |
| `ep:SharedDoc` | `xsd:boolean` | `shared-documentPropertiesExtended.xsd` |
| `ep:Slides` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Template` | `xsd:string` | `shared-documentPropertiesExtended.xsd` |
| `ep:TitlesOfParts` | `CT_VectorLpstr` | `shared-documentPropertiesExtended.xsd` |
| `ep:TotalTime` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `ep:Words` | `xsd:int` | `shared-documentPropertiesExtended.xsd` |
| `lc:lockedCanvas` | `a:CT_GvmlGroupShape` | `dml-lockedCanvas.xsd` |
| `m:acc` | `CT_Acc` | `shared-math.xsd` |
| `m:accPr` | `CT_AccPr` | `shared-math.xsd` |
| `m:aln` | `CT_OnOff` | `shared-math.xsd` |
| `m:alnScr` | `CT_OnOff` | `shared-math.xsd` |
| `m:argPr` | `CT_OMathArgPr` | `shared-math.xsd` |
| `m:argSz` | `CT_Integer2` | `shared-math.xsd` |
| `m:bar` | `CT_Bar` | `shared-math.xsd` |
| `m:barPr` | `CT_BarPr` | `shared-math.xsd` |
| `m:baseJc` | `CT_YAlign` | `shared-math.xsd` |
| `m:begChr` | `CT_Char` | `shared-math.xsd` |
| `m:borderBox` | `CT_BorderBox` | `shared-math.xsd` |
| `m:borderBoxPr` | `CT_BorderBoxPr` | `shared-math.xsd` |
| `m:box` | `CT_Box` | `shared-math.xsd` |
| `m:boxPr` | `CT_BoxPr` | `shared-math.xsd` |
| `m:brk` | `CT_ManualBreak` | `shared-math.xsd` |
| `m:brkBin` | `CT_BreakBin` | `shared-math.xsd` |
| `m:brkBinSub` | `CT_BreakBinSub` | `shared-math.xsd` |
| `m:cGp` | `CT_UnSignedInteger` | `shared-math.xsd` |
| `m:cGpRule` | `CT_SpacingRule` | `shared-math.xsd` |
| `m:chr` | `CT_Char` | `shared-math.xsd` |
| `m:count` | `CT_Integer255` | `shared-math.xsd` |
| `m:cSp` | `CT_UnSignedInteger` | `shared-math.xsd` |
| `m:ctrlPr` | `CT_CtrlPr` | `shared-math.xsd` |
| `m:d` | `CT_D` | `shared-math.xsd` |
| `m:defJc` | `CT_OMathJc` | `shared-math.xsd` |
| `m:deg` | `CT_OMathArg` | `shared-math.xsd` |
| `m:degHide` | `CT_OnOff` | `shared-math.xsd` |
| `m:den` | `CT_OMathArg` | `shared-math.xsd` |
| `m:diff` | `CT_OnOff` | `shared-math.xsd` |
| `m:dispDef` | `CT_OnOff` | `shared-math.xsd` |
| `m:dPr` | `CT_DPr` | `shared-math.xsd` |
| `m:e` | `CT_OMathArg` | `shared-math.xsd` |
| `m:endChr` | `CT_Char` | `shared-math.xsd` |
| `m:eqArr` | `CT_EqArr` | `shared-math.xsd` |
| `m:eqArrPr` | `CT_EqArrPr` | `shared-math.xsd` |
| `m:f` | `CT_F` | `shared-math.xsd` |
| `m:fName` | `CT_OMathArg` | `shared-math.xsd` |
| `m:fPr` | `CT_FPr` | `shared-math.xsd` |
| `m:func` | `CT_Func` | `shared-math.xsd` |
| `m:funcPr` | `CT_FuncPr` | `shared-math.xsd` |
| `m:groupChr` | `CT_GroupChr` | `shared-math.xsd` |
| `m:groupChrPr` | `CT_GroupChrPr` | `shared-math.xsd` |
| `m:grow` | `CT_OnOff` | `shared-math.xsd` |
| `m:hideBot` | `CT_OnOff` | `shared-math.xsd` |
| `m:hideLeft` | `CT_OnOff` | `shared-math.xsd` |
| `m:hideRight` | `CT_OnOff` | `shared-math.xsd` |
| `m:hideTop` | `CT_OnOff` | `shared-math.xsd` |
| `m:interSp` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:intLim` | `CT_LimLoc` | `shared-math.xsd` |
| `m:intraSp` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:jc` | `CT_OMathJc` | `shared-math.xsd` |
| `m:lim` | `CT_OMathArg` | `shared-math.xsd` |
| `m:limLoc` | `CT_LimLoc` | `shared-math.xsd` |
| `m:limLow` | `CT_LimLow` | `shared-math.xsd` |
| `m:limLowPr` | `CT_LimLowPr` | `shared-math.xsd` |
| `m:limUpp` | `CT_LimUpp` | `shared-math.xsd` |
| `m:limUppPr` | `CT_LimUppPr` | `shared-math.xsd` |
| `m:lit` | `CT_OnOff` | `shared-math.xsd` |
| `m:lMargin` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:m` | `CT_M` | `shared-math.xsd` |
| `m:mathFont` | `CT_String` | `shared-math.xsd` |
| `m:mathPr` | `CT_MathPr` | `shared-math.xsd` |
| `m:maxDist` | `CT_OnOff` | `shared-math.xsd` |
| `m:mc` | `CT_MC` | `shared-math.xsd` |
| `m:mcJc` | `CT_XAlign` | `shared-math.xsd` |
| `m:mcPr` | `CT_MCPr` | `shared-math.xsd` |
| `m:mcs` | `CT_MCS` | `shared-math.xsd` |
| `m:mPr` | `CT_MPr` | `shared-math.xsd` |
| `m:mr` | `CT_MR` | `shared-math.xsd` |
| `m:nary` | `CT_Nary` | `shared-math.xsd` |
| `m:naryLim` | `CT_LimLoc` | `shared-math.xsd` |
| `m:naryPr` | `CT_NaryPr` | `shared-math.xsd` |
| `m:noBreak` | `CT_OnOff` | `shared-math.xsd` |
| `m:nor` | `CT_OnOff` | `shared-math.xsd` |
| `m:num` | `CT_OMathArg` | `shared-math.xsd` |
| `m:objDist` | `CT_OnOff` | `shared-math.xsd` |
| `m:oMath` | `CT_OMath` | `shared-math.xsd` |
| `m:oMathPara` | `CT_OMathPara` | `shared-math.xsd` |
| `m:oMathParaPr` | `CT_OMathParaPr` | `shared-math.xsd` |
| `m:opEmu` | `CT_OnOff` | `shared-math.xsd` |
| `m:phant` | `CT_Phant` | `shared-math.xsd` |
| `m:phantPr` | `CT_PhantPr` | `shared-math.xsd` |
| `m:plcHide` | `CT_OnOff` | `shared-math.xsd` |
| `m:pos` | `CT_TopBot` | `shared-math.xsd` |
| `m:postSp` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:preSp` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:r` | `CT_R` | `shared-math.xsd` |
| `m:rad` | `CT_Rad` | `shared-math.xsd` |
| `m:radPr` | `CT_RadPr` | `shared-math.xsd` |
| `m:rMargin` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:rPr` | `CT_RPR` | `shared-math.xsd` |
| `m:rSp` | `CT_UnSignedInteger` | `shared-math.xsd` |
| `m:rSpRule` | `CT_SpacingRule` | `shared-math.xsd` |
| `m:scr` | `CT_Script` | `shared-math.xsd` |
| `m:sepChr` | `CT_Char` | `shared-math.xsd` |
| `m:show` | `CT_OnOff` | `shared-math.xsd` |
| `m:shp` | `CT_Shp` | `shared-math.xsd` |
| `m:smallFrac` | `CT_OnOff` | `shared-math.xsd` |
| `m:sPre` | `CT_SPre` | `shared-math.xsd` |
| `m:sPrePr` | `CT_SPrePr` | `shared-math.xsd` |
| `m:sSub` | `CT_SSub` | `shared-math.xsd` |
| `m:sSubPr` | `CT_SSubPr` | `shared-math.xsd` |
| `m:sSubSup` | `CT_SSubSup` | `shared-math.xsd` |
| `m:sSubSupPr` | `CT_SSubSupPr` | `shared-math.xsd` |
| `m:sSup` | `CT_SSup` | `shared-math.xsd` |
| `m:sSupPr` | `CT_SSupPr` | `shared-math.xsd` |
| `m:strikeBLTR` | `CT_OnOff` | `shared-math.xsd` |
| `m:strikeH` | `CT_OnOff` | `shared-math.xsd` |
| `m:strikeTLBR` | `CT_OnOff` | `shared-math.xsd` |
| `m:strikeV` | `CT_OnOff` | `shared-math.xsd` |
| `m:sty` | `CT_Style` | `shared-math.xsd` |
| `m:sub` | `CT_OMathArg` | `shared-math.xsd` |
| `m:subHide` | `CT_OnOff` | `shared-math.xsd` |
| `m:sup` | `CT_OMathArg` | `shared-math.xsd` |
| `m:supHide` | `CT_OnOff` | `shared-math.xsd` |
| `m:t` | `CT_Text` | `shared-math.xsd` |
| `m:transp` | `CT_OnOff` | `shared-math.xsd` |
| `m:type` | `CT_FType` | `shared-math.xsd` |
| `m:vertJc` | `CT_TopBot` | `shared-math.xsd` |
| `m:wrapIndent` | `CT_TwipsMeasure` | `shared-math.xsd` |
| `m:wrapRight` | `CT_OnOff` | `shared-math.xsd` |
| `m:zeroAsc` | `CT_OnOff` | `shared-math.xsd` |
| `m:zeroDesc` | `CT_OnOff` | `shared-math.xsd` |
| `m:zeroWid` | `CT_OnOff` | `shared-math.xsd` |
| `o:bottom` | `CT_StrokeChild` | `vml-officeDrawing.xsd` |
| `o:callout` | `CT_Callout` | `vml-officeDrawing.xsd` |
| `o:clippath` | `CT_ClipPath` | `vml-officeDrawing.xsd` |
| `o:colormenu` | `CT_ColorMenu` | `vml-officeDrawing.xsd` |
| `o:colormru` | `CT_ColorMru` | `vml-officeDrawing.xsd` |
| `o:column` | `CT_StrokeChild` | `vml-officeDrawing.xsd` |
| `o:complex` | `CT_Complex` | `vml-officeDrawing.xsd` |
| `o:diagram` | `CT_Diagram` | `vml-officeDrawing.xsd` |
| `o:entry` | `CT_Entry` | `vml-officeDrawing.xsd` |
| `o:equationxml` | `CT_EquationXml` | `vml-officeDrawing.xsd` |
| `o:extrusion` | `CT_Extrusion` | `vml-officeDrawing.xsd` |
| `o:FieldCodes` | `xsd:string` | `vml-officeDrawing.xsd` |
| `o:fill` | `CT_Fill` | `vml-officeDrawing.xsd` |
| `o:idmap` | `CT_IdMap` | `vml-officeDrawing.xsd` |
| `o:ink` | `CT_Ink` | `vml-officeDrawing.xsd` |
| `o:left` | `CT_StrokeChild` | `vml-officeDrawing.xsd` |
| `o:LinkType` | `ST_OLELinkType` | `vml-officeDrawing.xsd` |
| `o:lock` | `CT_Lock` | `vml-officeDrawing.xsd` |
| `o:LockedField` | `s:ST_TrueFalseBlank` | `vml-officeDrawing.xsd` |
| `o:OLEObject` | `CT_OLEObject` | `vml-officeDrawing.xsd` |
| `o:proxy` | `CT_Proxy` | `vml-officeDrawing.xsd` |
| `o:r` | `CT_R` | `vml-officeDrawing.xsd` |
| `o:regrouptable` | `CT_RegroupTable` | `vml-officeDrawing.xsd` |
| `o:rel` | `CT_Relation` | `vml-officeDrawing.xsd` |
| `o:relationtable` | `CT_RelationTable` | `vml-officeDrawing.xsd` |
| `o:right` | `CT_StrokeChild` | `vml-officeDrawing.xsd` |
| `o:rules` | `CT_Rules` | `vml-officeDrawing.xsd` |
| `o:shapedefaults` | `CT_ShapeDefaults` | `vml-officeDrawing.xsd` |
| `o:shapelayout` | `CT_ShapeLayout` | `vml-officeDrawing.xsd` |
| `o:signatureline` | `CT_SignatureLine` | `vml-officeDrawing.xsd` |
| `o:skew` | `CT_Skew` | `vml-officeDrawing.xsd` |
| `o:top` | `CT_StrokeChild` | `vml-officeDrawing.xsd` |
| `pic:blipFill` | `a:CT_BlipFillProperties` | `dml-picture.xsd` |
| `pic:cNvPicPr` | `a:CT_NonVisualPictureProperties` | `dml-picture.xsd` |
| `pic:cNvPr` | `a:CT_NonVisualDrawingProps` | `dml-picture.xsd` |
| `pic:nvPicPr` | `CT_PictureNonVisual` | `dml-picture.xsd` |
| `pic:pic` | `CT_Picture` | `dml-picture.xsd` |
| `pic:spPr` | `a:CT_ShapeProperties` | `dml-picture.xsd` |
| `pvml:iscomment` | `CT_Empty` | `vml-presentationDrawing.xsd` |
| `pvml:textdata` | `CT_Rel` | `vml-presentationDrawing.xsd` |
| `sl:schema` | `CT_Schema` | `shared-customXmlSchemaProperties.xsd` |
| `sl:schemaLibrary` | `CT_SchemaLibrary` | `shared-customXmlSchemaProperties.xsd` |
| `v:arc` | `CT_Arc` | `vml-main.xsd` |
| `v:background` | `CT_Background` | `vml-main.xsd` |
| `v:curve` | `CT_Curve` | `vml-main.xsd` |
| `v:f` | `CT_F` | `vml-main.xsd` |
| `v:fill` | `CT_Fill` | `vml-main.xsd` |
| `v:formulas` | `CT_Formulas` | `vml-main.xsd` |
| `v:group` | `CT_Group` | `vml-main.xsd` |
| `v:h` | `CT_H` | `vml-main.xsd` |
| `v:handles` | `CT_Handles` | `vml-main.xsd` |
| `v:image` | `CT_Image` | `vml-main.xsd` |
| `v:imagedata` | `CT_ImageData` | `vml-main.xsd` |
| `v:line` | `CT_Line` | `vml-main.xsd` |
| `v:oval` | `CT_Oval` | `vml-main.xsd` |
| `v:path` | `CT_Path` | `vml-main.xsd` |
| `v:polyline` | `CT_PolyLine` | `vml-main.xsd` |
| `v:rect` | `CT_Rect` | `vml-main.xsd` |
| `v:roundrect` | `CT_RoundRect` | `vml-main.xsd` |
| `v:shadow` | `CT_Shadow` | `vml-main.xsd` |
| `v:shape` | `CT_Shape` | `vml-main.xsd` |
| `v:shapetype` | `CT_Shapetype` | `vml-main.xsd` |
| `v:stroke` | `CT_Stroke` | `vml-main.xsd` |
| `v:textbox` | `CT_Textbox` | `vml-main.xsd` |
| `v:textpath` | `CT_TextPath` | `vml-main.xsd` |
| `vt:array` | `CT_Array` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:blob` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:bool` | `xsd:boolean` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:bstr` | `xsd:string` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:clsid` | `s:ST_Guid` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:cy` | `ST_Cy` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:date` | `xsd:dateTime` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:decimal` | `xsd:decimal` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:empty` | `CT_Empty` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:error` | `ST_Error` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:filetime` | `xsd:dateTime` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:i1` | `xsd:byte` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:i2` | `xsd:short` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:i4` | `xsd:int` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:i8` | `xsd:long` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:int` | `xsd:int` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:lpstr` | `xsd:string` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:lpwstr` | `xsd:string` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:null` | `CT_Null` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:oblob` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ostorage` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ostream` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:r4` | `xsd:float` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:r8` | `xsd:double` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:storage` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:stream` | `xsd:base64Binary` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ui1` | `xsd:unsignedByte` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ui2` | `xsd:unsignedShort` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ui4` | `xsd:unsignedInt` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:ui8` | `xsd:unsignedLong` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:uint` | `xsd:unsignedInt` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:variant` | `CT_Variant` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:vector` | `CT_Vector` | `shared-documentPropertiesVariantTypes.xsd` |
| `vt:vstream` | `CT_Vstream` | `shared-documentPropertiesVariantTypes.xsd` |
| `wp:align` | `ST_AlignH`<br>`ST_AlignV` | `dml-wordprocessingDrawing.xsd` |
| `wp:anchor` | `CT_Anchor` | `dml-wordprocessingDrawing.xsd` |
| `wp:bg` | `a:CT_BackgroundFormatting` | `dml-wordprocessingDrawing.xsd` |
| `wp:bodyPr` | `a:CT_TextBodyProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvCnPr` | `a:CT_NonVisualConnectorProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvContentPartPr` | `a:CT_NonVisualContentPartProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvFrPr` | `a:CT_NonVisualGraphicFrameProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvGraphicFramePr` | `a:CT_NonVisualGraphicFrameProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvGrpSpPr` | `a:CT_NonVisualGroupDrawingShapeProps` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvPr` | `a:CT_NonVisualDrawingProps` | `dml-wordprocessingDrawing.xsd` |
| `wp:cNvSpPr` | `a:CT_NonVisualDrawingShapeProps` | `dml-wordprocessingDrawing.xsd` |
| `wp:contentPart` | `CT_WordprocessingContentPart` | `dml-wordprocessingDrawing.xsd` |
| `wp:docPr` | `a:CT_NonVisualDrawingProps` | `dml-wordprocessingDrawing.xsd` |
| `wp:effectExtent` | `CT_EffectExtent` | `dml-wordprocessingDrawing.xsd` |
| `wp:extent` | `a:CT_PositiveSize2D` | `dml-wordprocessingDrawing.xsd` |
| `wp:extLst` | `a:CT_OfficeArtExtensionList` | `dml-wordprocessingDrawing.xsd` |
| `wp:graphicFrame` | `CT_GraphicFrame` | `dml-wordprocessingDrawing.xsd` |
| `wp:grpSp` | `CT_WordprocessingGroup` | `dml-wordprocessingDrawing.xsd` |
| `wp:grpSpPr` | `a:CT_GroupShapeProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:inline` | `CT_Inline` | `dml-wordprocessingDrawing.xsd` |
| `wp:lineTo` | `a:CT_Point2D` | `dml-wordprocessingDrawing.xsd` |
| `wp:linkedTxbx` | `CT_LinkedTextboxInformation` | `dml-wordprocessingDrawing.xsd` |
| `wp:nvContentPartPr` | `CT_WordprocessingContentPartNonVisual` | `dml-wordprocessingDrawing.xsd` |
| `wp:positionH` | `CT_PosH` | `dml-wordprocessingDrawing.xsd` |
| `wp:positionV` | `CT_PosV` | `dml-wordprocessingDrawing.xsd` |
| `wp:posOffset` | `ST_PositionOffset` | `dml-wordprocessingDrawing.xsd` |
| `wp:simplePos` | `a:CT_Point2D` | `dml-wordprocessingDrawing.xsd` |
| `wp:spPr` | `a:CT_ShapeProperties` | `dml-wordprocessingDrawing.xsd` |
| `wp:start` | `a:CT_Point2D` | `dml-wordprocessingDrawing.xsd` |
| `wp:style` | `a:CT_ShapeStyle` | `dml-wordprocessingDrawing.xsd` |
| `wp:txbx` | `CT_TextboxInfo` | `dml-wordprocessingDrawing.xsd` |
| `wp:txbxContent` | `CT_TxbxContent` | `dml-wordprocessingDrawing.xsd` |
| `wp:wgp` | `CT_WordprocessingGroup` | `dml-wordprocessingDrawing.xsd` |
| `wp:whole` | `a:CT_WholeE2oFormatting` | `dml-wordprocessingDrawing.xsd` |
| `wp:wpc` | `CT_WordprocessingCanvas` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapNone` | `CT_WrapNone` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapPolygon` | `CT_WrapPath` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapSquare` | `CT_WrapSquare` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapThrough` | `CT_WrapThrough` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapTight` | `CT_WrapTight` | `dml-wordprocessingDrawing.xsd` |
| `wp:wrapTopAndBottom` | `CT_WrapTopBottom` | `dml-wordprocessingDrawing.xsd` |
| `wp:wsp` | `CT_WordprocessingShape` | `dml-wordprocessingDrawing.xsd` |
| `wp:xfrm` | `a:CT_Transform2D` | `dml-wordprocessingDrawing.xsd` |
| `wvml:anchorlock` | `CT_AnchorLock` | `vml-wordprocessingDrawing.xsd` |
| `wvml:borderbottom` | `CT_Border` | `vml-wordprocessingDrawing.xsd` |
| `wvml:borderleft` | `CT_Border` | `vml-wordprocessingDrawing.xsd` |
| `wvml:borderright` | `CT_Border` | `vml-wordprocessingDrawing.xsd` |
| `wvml:bordertop` | `CT_Border` | `vml-wordprocessingDrawing.xsd` |
| `wvml:wrap` | `CT_Wrap` | `vml-wordprocessingDrawing.xsd` |
| `xdr:absoluteAnchor` | `CT_AbsoluteAnchor` | `dml-spreadsheetDrawing.xsd` |
| `xdr:blipFill` | `a:CT_BlipFillProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:clientData` | `CT_AnchorClientData` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvCxnSpPr` | `a:CT_NonVisualConnectorProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvGraphicFramePr` | `a:CT_NonVisualGraphicFrameProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvGrpSpPr` | `a:CT_NonVisualGroupDrawingShapeProps` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvPicPr` | `a:CT_NonVisualPictureProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvPr` | `a:CT_NonVisualDrawingProps` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cNvSpPr` | `a:CT_NonVisualDrawingShapeProps` | `dml-spreadsheetDrawing.xsd` |
| `xdr:col` | `ST_ColID` | `dml-spreadsheetDrawing.xsd` |
| `xdr:colOff` | `a:ST_Coordinate` | `dml-spreadsheetDrawing.xsd` |
| `xdr:contentPart` | `CT_Rel` | `dml-spreadsheetDrawing.xsd` |
| `xdr:cxnSp` | `CT_Connector` | `dml-spreadsheetDrawing.xsd` |
| `xdr:ext` | `a:CT_PositiveSize2D` | `dml-spreadsheetDrawing.xsd` |
| `xdr:from` | `CT_Marker` | `dml-spreadsheetDrawing.xsd` |
| `xdr:graphicFrame` | `CT_GraphicalObjectFrame` | `dml-spreadsheetDrawing.xsd` |
| `xdr:grpSp` | `CT_GroupShape` | `dml-spreadsheetDrawing.xsd` |
| `xdr:grpSpPr` | `a:CT_GroupShapeProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:nvCxnSpPr` | `CT_ConnectorNonVisual` | `dml-spreadsheetDrawing.xsd` |
| `xdr:nvGraphicFramePr` | `CT_GraphicalObjectFrameNonVisual` | `dml-spreadsheetDrawing.xsd` |
| `xdr:nvGrpSpPr` | `CT_GroupShapeNonVisual` | `dml-spreadsheetDrawing.xsd` |
| `xdr:nvPicPr` | `CT_PictureNonVisual` | `dml-spreadsheetDrawing.xsd` |
| `xdr:nvSpPr` | `CT_ShapeNonVisual` | `dml-spreadsheetDrawing.xsd` |
| `xdr:oneCellAnchor` | `CT_OneCellAnchor` | `dml-spreadsheetDrawing.xsd` |
| `xdr:pic` | `CT_Picture` | `dml-spreadsheetDrawing.xsd` |
| `xdr:pos` | `a:CT_Point2D` | `dml-spreadsheetDrawing.xsd` |
| `xdr:row` | `ST_RowID` | `dml-spreadsheetDrawing.xsd` |
| `xdr:rowOff` | `a:ST_Coordinate` | `dml-spreadsheetDrawing.xsd` |
| `xdr:sp` | `CT_Shape` | `dml-spreadsheetDrawing.xsd` |
| `xdr:spPr` | `a:CT_ShapeProperties` | `dml-spreadsheetDrawing.xsd` |
| `xdr:style` | `a:CT_ShapeStyle` | `dml-spreadsheetDrawing.xsd` |
| `xdr:to` | `CT_Marker` | `dml-spreadsheetDrawing.xsd` |
| `xdr:twoCellAnchor` | `CT_TwoCellAnchor` | `dml-spreadsheetDrawing.xsd` |
| `xdr:txBody` | `a:CT_TextBody` | `dml-spreadsheetDrawing.xsd` |
| `xdr:wsDr` | `CT_Drawing` | `dml-spreadsheetDrawing.xsd` |
| `xdr:xfrm` | `a:CT_Transform2D` | `dml-spreadsheetDrawing.xsd` |
| `xvml:Accel` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Accel2` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Anchor` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:AutoFill` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:AutoLine` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:AutoPict` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:AutoScale` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Camera` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Cancel` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:CF` | `ST_CF` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Checked` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ClientData` | `CT_ClientData` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ColHidden` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Colored` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Column` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:DDE` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Default` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:DefaultSize` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Disabled` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Dismiss` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:DropLines` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:DropStyle` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Dx` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FirstButton` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaGroup` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaLink` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaMacro` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaPict` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaRange` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:FmlaTxbx` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Help` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Horiz` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Inc` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:JustLastX` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:LCT` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ListItem` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Locked` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:LockText` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:MapOCX` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Max` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Min` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:MoveWithCells` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:MultiLine` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:MultiSel` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:NoThreeD` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:NoThreeD2` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Page` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:PrintObject` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:RecalcAlways` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Row` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:RowHidden` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ScriptExtended` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ScriptLanguage` | `xsd:nonNegativeInteger` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ScriptLocation` | `xsd:nonNegativeInteger` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ScriptText` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:SecretEdit` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Sel` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:SelType` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:SizeWithCells` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:TextHAlign` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:TextVAlign` | `xsd:string` | `vml-spreadsheetDrawing.xsd` |
| `xvml:UIObj` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Val` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:ValidIds` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:Visible` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:VScroll` | `s:ST_TrueFalseBlank` | `vml-spreadsheetDrawing.xsd` |
| `xvml:VTEdit` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
| `xvml:WidthMin` | `xsd:integer` | `vml-spreadsheetDrawing.xsd` |
<!-- END GENERATED SCHEMA INVENTORY -->
