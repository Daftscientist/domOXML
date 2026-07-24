# PPTX-Specific Capability And PresentationML Inventory

This inventory contains only presentation-specific behavior. DrawingML geometry, text, paint,
effects, tables, charts, media, packaging, HTML serialization, and fidelity infrastructure belong
in [`inventory-shared.md`](inventory-shared.md), even when PPTX is their first consumer.

Use the shared inventory’s status vocabulary. A row is “verified both” only when executable
evidence covers both conversion directions and the round-trip path.

## Current PresentationML Capability Matrix

Audited on **2026-07-24**.

| Capability | HTML/CSS -> PPTX | PPTX -> HTML/CSS | Evidence | Main remaining work |
|---|---|---|---|---|
| Presentation package, slide order, and visual IDs | Native with private identity extension and mandatory core package validation | Native with extension or `cNvPr` fallback provenance | package-validator unit suite + `cap:node-identity` (both) + 6 real decks | sections/custom shows where useful, strict/nonstandard packages and full XSD validation |
| Slide dimensions | Native | Native | integration | mixed-size output policy and repeated-round-trip proof |
| Slide creation and relationships | Native; builder rejects missing/duplicate/dangling package graphs and invalid core structure | Native | package-validator unit suite + all capability/re-emission gates | full ECMA XSD validation and deterministic source relationship preservation |
| Slide backgrounds | Native subset | Native subset | `cap:transition-bg` (both) | theme/style-matrix backgrounds, image/pattern variants, inheritance |
| Themes | Partial generated default; restores an attached chart's ambient source theme | Native/partial read | unit + chart real deck | general source-theme authoring, multiple-theme policy, scheme refs, format scheme and full inheritance |
| Masters and layouts | Fixed generated baseline | Native/partial read, including placeholder body-property inheritance | unit/integration + chart real deck | author arbitrary masters/layouts and preserve them through round trips |
| Placeholders | Gap on authoring | Native/partial read for geometry, runs, field runs, inherited paragraph alignment and body properties | unit + chart real deck | public/IR model, create placeholders and preserve the full inheritance chain without flattening |
| Slide inheritance | Gap/flattened output | Partial/native resolution | unit only | complete slide -> layout -> master -> theme cascade and source-reference retention |
| Transitions | Native subset | Native subset | `cap:transition-bg` (both) | complete transition set, attributes, sounds, advance timing and extension variants |
| Animations/timing | Gap | Preserve only | unit only | timing IR/input contract, HTML state mapping, visual playback/layer policy, re-emission |
| Speaker notes | Gap; no public argument | Gap | none | `Slide` notes argument, notes parts/relationships, normalized HTML metadata, round trip |
| Embedded fonts | Partial/native | Partial/native | unit/integration + real deck | complete face slots, substitutions/licensing, malformed data and renderer baselines |
| Pictures and raster fallback markers | Native; isolated effect fallbacks, sole-visual preset-shadow fallbacks, and one whole-sequence slide fallback are renderer-selected through `mc:AlternateContent` | Native; authoritative isolated crops attach to preserved positioned nodes, safe composite-only fallbacks report rasterized/noneditable, and normalized HTML recovers slide-owned pixels above retained native contents | capabilities/integration + `cap:blur-effect` + `cap:reflection-effect` + `cap:soft-edge-effect` + `cap:fill-overlay-effect` + `cap:fill-overlay-owned-fallback` + `cap:preset-shadow-raster-fallback` + `cap:preset-shadow-slide-fallback` + malformed slide-marker regression + `cap:chart-preservation` | automatic renderer policy beyond proven effects, multiple unsupported siblings, smaller preset-shadow isolation, stable group ownership and accessibility fields |
| SVG extension (`asvg:svgBlip`) | Native write | Native read and exact re-emission for pure pictures | `cap:svg-vector` (both) | cropped/effect-bearing SVG pictures, external assets, and adversarial SVG content |
| Native tables in graphic frames | Native subset | Native subset; default style reference/flags survive IR and normalized HTML | `cap:table` (both) + LO/Graph real deck | arbitrary style definitions/inheritance and richer graphic-frame ordering |
| Charts in graphic frames | Attached source re-emission only; authored charts remain a gap | Attached exact graph plus caller-rendered normalized-HTML element layer | `cap:chart-preservation` (reverse) + scoped HTML and real-deck PPTX visual gates | shared chart IR, automatic renderer selection, semantic HTML rendering, and native authoring |
| Groups | Gap on authoring | Native read then flattened | unit only | author/preserve nested groups, child coordinates, interleaved z-order and IDs |
| Connectors | Partial | Partial; transform-box route/endpoints are reported approximated/lost | unit + `cap:custom-path` (both) | attachment/routing/arrows and structure-preserving reverse re-emission |
| Audio/video | Layered/not native | Native read | unit only | native relationships/parts, playback settings, poster handling and real deck |
| SmartArt/diagram | Gap | Positioned fallback contract available; ownership/corpus proof pending | unit only | source attachment/re-emission, visual fixture, optional semantic model |
| OLE/embedded objects | Gap | Positioned fallback contract available; ownership/corpus proof pending | unit only | preview fixture, package preservation/re-emission, security policy |
| 3D/model extensions | Gap | Positioned fallback contract available where bounds and graph capture succeed | limited unit coverage | package preservation, visual fixture and representative corpus |
| Accessibility and alternative text | Gap/partial incidental | Partial incidental | no capability fixture | first-class IR/API, `cNvPr` metadata and HTML semantics |
| Comments/review history | Intentionally ignored | Intentionally ignored | policy | ensure ignored parts never damage visible/package conversion |
| Unknown slide/extension nodes | no authoring classification contract | Per-visual `element_layer` only where ownership is proved; one slide-level composite fallback is proven for a preset-shadow shape plus supported siblings, while missing renders and retention debt remain explicit | chart + preset-shadow capabilities + focused coverage tests | automatic renderer policy, multiple unknown siblings, SmartArt/OLE/3D corpus, group ownership, and attached re-emission proof beyond charts |

## Atomic Executable Coverage

| Capability fixture | Direction | Current role |
|---|---|---|
| `body-props` | both | shared text-body properties used by PPTX |
| `borders` | both | shared stroke/decomposition behavior |
| `blur-effect` | both | native PowerPoint blur plus isolated LibreOffice fallback, exact effect payload, transform/text stacking, and convergence |
| `bullets-spacing` | both | shared list/paragraph behavior |
| `chart-preservation` | reverse | owned chart graph, ambient theme, identity, renderer-backed HTML element layer, and exact PPTX re-emission |
| `custom-path` | both | native custom geometry and connector structure survive normalized HTML and PPTX re-emission |
| `effects` | both | native outer shadow/glow plus portable inset layer; broader effect-list family remains |
| `fill-overlay-effect` | both | four editable solid blend modes, portable renderer branches, exact payload, stacking, and convergence |
| `fill-overlay-owned-fallback` | reverse | rotated unsupported `over` blend remains visible as one owned layer, retains exact source payload, and converges after the fallback boundary |
| `hyperlink` | both | run hyperlinks and relationships |
| `interleaved-order` | both | canonical mixed-node z-order through both adapters |
| `node-identity` | both | stable IDs, source provenance, ownership, and private OOXML extension |
| `pattern-fills` | both | DrawingML pattern mapping |
| `picture-crop` | both | picture crop and reverse CSS |
| `preset-shadow-raster-fallback` | reverse | sole-visual perspective preset shadow remains visible through one measured full-slide raster fallback, retains exact native source, and converges after the fallback boundary |
| `preset-shadow-slide-fallback` | reverse | perspective shadow plus overlapping translucent sibling retain native z-order under one slide-owned renderer fallback and converge after two normalized HTML cycles |
| `preset-shapes` | both | supported preset geometry subset |
| `reflection-effect` | both | native PowerPoint reflection plus isolated LibreOffice fallback, exact effect payload, stacking, and convergence |
| `soft-edge-effect` | both | strict CSS feather mask, ellipse-aware reverse feather, native PowerPoint soft edge plus shape-bound fallback, exact payload, stacking, and convergence |
| `svg-vector` | both | original SVG asset, identity, native picture, and extension survive re-emission |
| `table` | both | native DrawingML table subset |
| `text-decorations` | both | text decoration subset |
| `text-rich-runs` | both | ordered rich runs |
| `transforms` | both | supported rotation/flip subset |
| `transition-bg` | both | slide transition/background subset |

This table reports fixture execution, not completion of the entire named family. Thresholds and
structural assertions live in each `capability.toml` and are the executable authority. Every
fixture pins exact representation, editability, retention, output-count, and raster-area bounds for
the initial PPTX-ingest boundary; the six real-deck manifests pin the same reverse contract.

## PPTX-Specific Work Remaining

1. Masters, layouts, placeholders, themes, and inheritance in both directions without flattening.
2. Speaker notes and useful presentation/accessibility metadata.
3. Exact slide/group/graphic-frame ordering on the canonical node sequence.
4. Complete transitions plus an explicit animation/timing authoring contract.
5. Native media authoring and playback relationships.
6. Chart visual layers/native authoring plus SmartArt, OLE, 3D, and unknown-node exact re-emission.
7. Strict, broader alternate-content, Microsoft-extension, and malformed-but-accepted package coverage.
8. Larger Microsoft-authored corpus and repeated PowerPoint-rendered convergence gates.

<!-- BEGIN GENERATED SCHEMA INVENTORY -->
## ECMA-376 Schema Surface

Generated by `scripts/generate_spec_inventories.py` from the official ECMA-376 5th edition Part 4 Transitional XSDs. The source archives are SHA-256 pinned in the generator.

This `pptx` partition contains **213 qualified element names**, **316 named declarations**, **149 named complex types**, and **1 namespace**. Repeated declarations of one QName are combined and retain every declared type.

This appendix is a discovery checklist, not an implementation percentage. One user-facing capability often uses several elements, and one element can participate in unrelated capabilities. Runtime status belongs in the curated tables above and in executable fixtures.

Official standard: <https://ecma-international.org/publications-and-standards/standards/ecma-376/>

### Namespace Legend

| Prefix | Namespace |
|---|---|
| `p` | `http://schemas.openxmlformats.org/presentationml/2006/main` |

### Elements

| QName | Declared type(s) | Source XSD |
|---|---|---|
| `p:anim` | `CT_TLAnimateBehavior` | `pml.xsd` |
| `p:animClr` | `CT_TLAnimateColorBehavior` | `pml.xsd` |
| `p:animEffect` | `CT_TLAnimateEffectBehavior` | `pml.xsd` |
| `p:animMotion` | `CT_TLAnimateMotionBehavior` | `pml.xsd` |
| `p:animRot` | `CT_TLAnimateRotationBehavior` | `pml.xsd` |
| `p:animScale` | `CT_TLAnimateScaleBehavior` | `pml.xsd` |
| `p:attrName` | `xsd:string` | `pml.xsd` |
| `p:attrNameLst` | `CT_TLBehaviorAttributeNameList` | `pml.xsd` |
| `p:audio` | `CT_TLMediaNodeAudio` | `pml.xsd` |
| `p:bg` | `CT_Background`<br>`CT_Empty` | `pml.xsd` |
| `p:bgPr` | `CT_BackgroundProperties` | `pml.xsd` |
| `p:bgRef` | `a:CT_StyleMatrixReference` | `pml.xsd` |
| `p:bldAsOne` | `CT_Empty` | `pml.xsd` |
| `p:bldDgm` | `CT_TLBuildDiagram` | `pml.xsd` |
| `p:bldGraphic` | `CT_TLGraphicalObjectBuild` | `pml.xsd` |
| `p:bldLst` | `CT_BuildList` | `pml.xsd` |
| `p:bldOleChart` | `CT_TLOleBuildChart` | `pml.xsd` |
| `p:bldP` | `CT_TLBuildParagraph` | `pml.xsd` |
| `p:bldSub` | `a:CT_AnimationGraphicalObjectBuildProperties` | `pml.xsd` |
| `p:blinds` | `CT_OrientationTransition` | `pml.xsd` |
| `p:blipFill` | `a:CT_BlipFillProperties` | `pml.xsd` |
| `p:bodyStyle` | `a:CT_TextListStyle` | `pml.xsd` |
| `p:bold` | `CT_EmbeddedFontDataId` | `pml.xsd` |
| `p:boldItalic` | `CT_EmbeddedFontDataId` | `pml.xsd` |
| `p:boolVal` | `CT_TLAnimVariantBooleanVal` | `pml.xsd` |
| `p:browse` | `CT_ShowInfoBrowse` | `pml.xsd` |
| `p:by` | `CT_TLByAnimateColorTransform`<br>`CT_TLPoint` | `pml.xsd` |
| `p:cBhvr` | `CT_TLCommonBehaviorData` | `pml.xsd` |
| `p:charRg` | `CT_IndexRange` | `pml.xsd` |
| `p:checker` | `CT_OrientationTransition` | `pml.xsd` |
| `p:childTnLst` | `CT_TimeNodeList` | `pml.xsd` |
| `p:circle` | `CT_Empty` | `pml.xsd` |
| `p:clrMap` | `a:CT_ColorMapping` | `pml.xsd` |
| `p:clrMapOvr` | `a:CT_ColorMappingOverride` | `pml.xsd` |
| `p:clrMru` | `a:CT_ColorMRU` | `pml.xsd` |
| `p:clrVal` | `a:CT_Color` | `pml.xsd` |
| `p:cm` | `CT_Comment` | `pml.xsd` |
| `p:cmAuthor` | `CT_CommentAuthor` | `pml.xsd` |
| `p:cmAuthorLst` | `CT_CommentAuthorList` | `pml.xsd` |
| `p:cmd` | `CT_TLCommandBehavior` | `pml.xsd` |
| `p:cMediaNode` | `CT_TLCommonMediaNodeData` | `pml.xsd` |
| `p:cmLst` | `CT_CommentList` | `pml.xsd` |
| `p:cNvCxnSpPr` | `a:CT_NonVisualConnectorProperties` | `pml.xsd` |
| `p:cNvGraphicFramePr` | `a:CT_NonVisualGraphicFrameProperties` | `pml.xsd` |
| `p:cNvGrpSpPr` | `a:CT_NonVisualGroupDrawingShapeProps` | `pml.xsd` |
| `p:cNvPicPr` | `a:CT_NonVisualPictureProperties` | `pml.xsd` |
| `p:cNvPr` | `a:CT_NonVisualDrawingProps` | `pml.xsd` |
| `p:cNvSpPr` | `a:CT_NonVisualDrawingShapeProps` | `pml.xsd` |
| `p:comb` | `CT_OrientationTransition` | `pml.xsd` |
| `p:cond` | `CT_TLTimeCondition` | `pml.xsd` |
| `p:contentPart` | `CT_Rel` | `pml.xsd` |
| `p:control` | `CT_Control` | `pml.xsd` |
| `p:controls` | `CT_ControlList` | `pml.xsd` |
| `p:cover` | `CT_EightDirectionTransition` | `pml.xsd` |
| `p:cSld` | `CT_CommonSlideData` | `pml.xsd` |
| `p:cSldViewPr` | `CT_CommonSlideViewProperties` | `pml.xsd` |
| `p:cTn` | `CT_TLCommonTimeNodeData` | `pml.xsd` |
| `p:custData` | `CT_CustomerData` | `pml.xsd` |
| `p:custDataLst` | `CT_CustomerDataList` | `pml.xsd` |
| `p:custShow` | `CT_CustomShow`<br>`CT_CustomShowId` | `pml.xsd` |
| `p:custShowLst` | `CT_CustomShowList` | `pml.xsd` |
| `p:cut` | `CT_OptionalBlackTransition` | `pml.xsd` |
| `p:cViewPr` | `CT_CommonViewProperties` | `pml.xsd` |
| `p:cxnSp` | `CT_Connector` | `pml.xsd` |
| `p:defaultTextStyle` | `a:CT_TextListStyle` | `pml.xsd` |
| `p:diamond` | `CT_Empty` | `pml.xsd` |
| `p:dissolve` | `CT_Empty` | `pml.xsd` |
| `p:embed` | `CT_OleObjectEmbed` | `pml.xsd` |
| `p:embeddedFont` | `CT_EmbeddedFontListEntry` | `pml.xsd` |
| `p:embeddedFontLst` | `CT_EmbeddedFontList` | `pml.xsd` |
| `p:endCondLst` | `CT_TLTimeConditionList` | `pml.xsd` |
| `p:endSnd` | `CT_Empty` | `pml.xsd` |
| `p:endSync` | `CT_TLTimeCondition` | `pml.xsd` |
| `p:excl` | `CT_TLTimeNodeExclusive` | `pml.xsd` |
| `p:ext` | `CT_Extension` | `pml.xsd` |
| `p:extLst` | `CT_ExtensionList`<br>`CT_ExtensionListModify` | `pml.xsd` |
| `p:fade` | `CT_OptionalBlackTransition` | `pml.xsd` |
| `p:fltVal` | `CT_TLAnimVariantFloatVal` | `pml.xsd` |
| `p:font` | `a:CT_TextFont` | `pml.xsd` |
| `p:from` | `CT_TLPoint`<br>`a:CT_Color` | `pml.xsd` |
| `p:graphicEl` | `a:CT_AnimationElementChoice` | `pml.xsd` |
| `p:graphicFrame` | `CT_GraphicalObjectFrame` | `pml.xsd` |
| `p:gridSpacing` | `a:CT_PositiveSize2D` | `pml.xsd` |
| `p:grpSp` | `CT_GroupShape` | `pml.xsd` |
| `p:grpSpPr` | `a:CT_GroupShapeProperties` | `pml.xsd` |
| `p:guide` | `CT_Guide` | `pml.xsd` |
| `p:guideLst` | `CT_GuideList` | `pml.xsd` |
| `p:handoutMaster` | `CT_HandoutMaster` | `pml.xsd` |
| `p:handoutMasterId` | `CT_HandoutMasterIdListEntry` | `pml.xsd` |
| `p:handoutMasterIdLst` | `CT_HandoutMasterIdList` | `pml.xsd` |
| `p:hf` | `CT_HeaderFooter` | `pml.xsd` |
| `p:hsl` | `CT_TLByHslColorTransform` | `pml.xsd` |
| `p:htmlPubPr` | `CT_HtmlPublishProperties` | `pml.xsd` |
| `p:inkTgt` | `CT_TLSubShapeId` | `pml.xsd` |
| `p:intVal` | `CT_TLAnimVariantIntegerVal` | `pml.xsd` |
| `p:italic` | `CT_EmbeddedFontDataId` | `pml.xsd` |
| `p:iterate` | `CT_TLIterateData` | `pml.xsd` |
| `p:kinsoku` | `CT_Kinsoku` | `pml.xsd` |
| `p:kiosk` | `CT_ShowInfoKiosk` | `pml.xsd` |
| `p:link` | `CT_OleObjectLink` | `pml.xsd` |
| `p:modifyVerifier` | `CT_ModifyVerifier` | `pml.xsd` |
| `p:newsflash` | `CT_Empty` | `pml.xsd` |
| `p:nextCondLst` | `CT_TLTimeConditionList` | `pml.xsd` |
| `p:normalViewPr` | `CT_NormalViewProperties` | `pml.xsd` |
| `p:notes` | `CT_NotesSlide` | `pml.xsd` |
| `p:notesMaster` | `CT_NotesMaster` | `pml.xsd` |
| `p:notesMasterId` | `CT_NotesMasterIdListEntry` | `pml.xsd` |
| `p:notesMasterIdLst` | `CT_NotesMasterIdList` | `pml.xsd` |
| `p:notesStyle` | `a:CT_TextListStyle` | `pml.xsd` |
| `p:notesSz` | `a:CT_PositiveSize2D` | `pml.xsd` |
| `p:notesTextViewPr` | `CT_NotesTextViewProperties` | `pml.xsd` |
| `p:notesViewPr` | `CT_NotesViewProperties` | `pml.xsd` |
| `p:nvCxnSpPr` | `CT_ConnectorNonVisual` | `pml.xsd` |
| `p:nvGraphicFramePr` | `CT_GraphicalObjectFrameNonVisual` | `pml.xsd` |
| `p:nvGrpSpPr` | `CT_GroupShapeNonVisual` | `pml.xsd` |
| `p:nvPicPr` | `CT_PictureNonVisual` | `pml.xsd` |
| `p:nvPr` | `CT_ApplicationNonVisualDrawingProps` | `pml.xsd` |
| `p:nvSpPr` | `CT_ShapeNonVisual` | `pml.xsd` |
| `p:oleChartEl` | `CT_TLOleChartTargetElement` | `pml.xsd` |
| `p:oleObj` | `CT_OleObject` | `pml.xsd` |
| `p:origin` | `a:CT_Point2D` | `pml.xsd` |
| `p:otherStyle` | `a:CT_TextListStyle` | `pml.xsd` |
| `p:outlineViewPr` | `CT_OutlineViewProperties` | `pml.xsd` |
| `p:par` | `CT_TLTimeNodeParallel` | `pml.xsd` |
| `p:penClr` | `a:CT_Color` | `pml.xsd` |
| `p:ph` | `CT_Placeholder` | `pml.xsd` |
| `p:photoAlbum` | `CT_PhotoAlbum` | `pml.xsd` |
| `p:pic` | `CT_Picture` | `pml.xsd` |
| `p:plus` | `CT_Empty` | `pml.xsd` |
| `p:pos` | `a:CT_Point2D` | `pml.xsd` |
| `p:present` | `CT_Empty` | `pml.xsd` |
| `p:presentation` | `CT_Presentation` | `pml.xsd` |
| `p:presentationPr` | `CT_PresentationProperties` | `pml.xsd` |
| `p:prevCondLst` | `CT_TLTimeConditionList` | `pml.xsd` |
| `p:pRg` | `CT_IndexRange` | `pml.xsd` |
| `p:prnPr` | `CT_PrintProperties` | `pml.xsd` |
| `p:progress` | `CT_TLAnimVariant` | `pml.xsd` |
| `p:pull` | `CT_EightDirectionTransition` | `pml.xsd` |
| `p:push` | `CT_SideDirectionTransition` | `pml.xsd` |
| `p:random` | `CT_Empty` | `pml.xsd` |
| `p:randomBar` | `CT_OrientationTransition` | `pml.xsd` |
| `p:rCtr` | `CT_TLPoint` | `pml.xsd` |
| `p:regular` | `CT_EmbeddedFontDataId` | `pml.xsd` |
| `p:restoredLeft` | `CT_NormalViewPortion` | `pml.xsd` |
| `p:restoredTop` | `CT_NormalViewPortion` | `pml.xsd` |
| `p:rgb` | `CT_TLByRgbColorTransform` | `pml.xsd` |
| `p:rtn` | `CT_TLTriggerRuntimeNode` | `pml.xsd` |
| `p:scale` | `a:CT_Scale2D` | `pml.xsd` |
| `p:seq` | `CT_TLTimeNodeSequence` | `pml.xsd` |
| `p:set` | `CT_TLSetBehavior` | `pml.xsd` |
| `p:showPr` | `CT_ShowProperties` | `pml.xsd` |
| `p:sld` | `CT_OutlineViewSlideEntry`<br>`CT_Slide`<br>`CT_SlideRelationshipListEntry` | `pml.xsd` |
| `p:sldAll` | `CT_Empty` | `pml.xsd` |
| `p:sldId` | `CT_SlideIdListEntry` | `pml.xsd` |
| `p:sldIdLst` | `CT_SlideIdList` | `pml.xsd` |
| `p:sldLayout` | `CT_SlideLayout` | `pml.xsd` |
| `p:sldLayoutId` | `CT_SlideLayoutIdListEntry` | `pml.xsd` |
| `p:sldLayoutIdLst` | `CT_SlideLayoutIdList` | `pml.xsd` |
| `p:sldLst` | `CT_OutlineViewSlideList`<br>`CT_SlideRelationshipList` | `pml.xsd` |
| `p:sldMaster` | `CT_SlideMaster` | `pml.xsd` |
| `p:sldMasterId` | `CT_SlideMasterIdListEntry` | `pml.xsd` |
| `p:sldMasterIdLst` | `CT_SlideMasterIdList` | `pml.xsd` |
| `p:sldRg` | `CT_IndexRange` | `pml.xsd` |
| `p:sldSyncPr` | `CT_SlideSyncProperties` | `pml.xsd` |
| `p:sldSz` | `CT_SlideSize` | `pml.xsd` |
| `p:sldTgt` | `CT_Empty` | `pml.xsd` |
| `p:slideViewPr` | `CT_SlideViewProperties` | `pml.xsd` |
| `p:smartTags` | `CT_SmartTags` | `pml.xsd` |
| `p:snd` | `a:CT_EmbeddedWAVAudioFile` | `pml.xsd` |
| `p:sndAc` | `CT_TransitionSoundAction` | `pml.xsd` |
| `p:sndTgt` | `a:CT_EmbeddedWAVAudioFile` | `pml.xsd` |
| `p:sorterViewPr` | `CT_SlideSorterViewProperties` | `pml.xsd` |
| `p:sp` | `CT_Shape` | `pml.xsd` |
| `p:split` | `CT_SplitTransition` | `pml.xsd` |
| `p:spPr` | `a:CT_ShapeProperties` | `pml.xsd` |
| `p:spTgt` | `CT_TLShapeTargetElement` | `pml.xsd` |
| `p:spTree` | `CT_GroupShape` | `pml.xsd` |
| `p:stCondLst` | `CT_TLTimeConditionList` | `pml.xsd` |
| `p:strips` | `CT_CornerDirectionTransition` | `pml.xsd` |
| `p:strVal` | `CT_TLAnimVariantStringVal` | `pml.xsd` |
| `p:stSnd` | `CT_TransitionStartSoundAction` | `pml.xsd` |
| `p:style` | `a:CT_ShapeStyle` | `pml.xsd` |
| `p:subSp` | `CT_TLSubShapeId` | `pml.xsd` |
| `p:subTnLst` | `CT_TimeNodeList` | `pml.xsd` |
| `p:tag` | `CT_StringTag` | `pml.xsd` |
| `p:tagLst` | `CT_TagList` | `pml.xsd` |
| `p:tags` | `CT_TagsData` | `pml.xsd` |
| `p:tav` | `CT_TLTimeAnimateValue` | `pml.xsd` |
| `p:tavLst` | `CT_TLTimeAnimateValueList` | `pml.xsd` |
| `p:text` | `xsd:string` | `pml.xsd` |
| `p:tgtEl` | `CT_TLTimeTargetElement` | `pml.xsd` |
| `p:timing` | `CT_SlideTiming` | `pml.xsd` |
| `p:titleStyle` | `a:CT_TextListStyle` | `pml.xsd` |
| `p:tmAbs` | `CT_TLIterateIntervalTime` | `pml.xsd` |
| `p:tmPct` | `CT_TLIterateIntervalPercentage` | `pml.xsd` |
| `p:tmpl` | `CT_TLTemplate` | `pml.xsd` |
| `p:tmplLst` | `CT_TLTemplateList` | `pml.xsd` |
| `p:tn` | `CT_TLTriggerTimeNodeID` | `pml.xsd` |
| `p:tnLst` | `CT_TimeNodeList` | `pml.xsd` |
| `p:to` | `CT_TLAnimVariant`<br>`CT_TLPoint`<br>`a:CT_Color` | `pml.xsd` |
| `p:transition` | `CT_SlideTransition` | `pml.xsd` |
| `p:txBody` | `a:CT_TextBody` | `pml.xsd` |
| `p:txEl` | `CT_TLTextTargetElement` | `pml.xsd` |
| `p:txStyles` | `CT_SlideMasterTextStyles` | `pml.xsd` |
| `p:val` | `CT_TLAnimVariant` | `pml.xsd` |
| `p:video` | `CT_TLMediaNodeVideo` | `pml.xsd` |
| `p:viewPr` | `CT_ViewProperties` | `pml.xsd` |
| `p:webPr` | `CT_WebProperties` | `pml.xsd` |
| `p:wedge` | `CT_Empty` | `pml.xsd` |
| `p:wheel` | `CT_WheelTransition` | `pml.xsd` |
| `p:wipe` | `CT_SideDirectionTransition` | `pml.xsd` |
| `p:xfrm` | `a:CT_Transform2D` | `pml.xsd` |
| `p:zoom` | `CT_InOutTransition` | `pml.xsd` |
<!-- END GENERATED SCHEMA INVENTORY -->
