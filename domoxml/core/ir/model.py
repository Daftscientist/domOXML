"""Normalized IR node types (canvas mode). All EMU; immutable pydantic models.

The IR is a format-agnostic scene the resolver/backends consume. Lengths are EMUs unless a
field name says otherwise (``*_pt`` is typographic points, ``*_pct``/``*_alpha`` is a fraction).
Models are frozen pydantic ``BaseModel``\\s; tuples (not lists) carry ordered children so a node
is hashable and cheap to copy.

This module is **models only** — the extractor (:mod:`domoxml.core.ir.extract`) and the
serializers (:mod:`domoxml.core.html`, :mod:`domoxml.core.drawingml.shape`,
:mod:`domoxml.slides.read`) own the behaviour. Many fields below describe Office constructs the
serializers do not map yet; they exist so the IR can *carry* the construct without dropping it,
and the serializers warn (never silently discard) on the arms they cannot emit.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True)


class Rgba(BaseModel):
    """An 8-bit RGB colour with float alpha in ``[0, 1]``."""

    model_config = _FROZEN

    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    a: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def hex(self) -> str:
        """Uppercase 6-digit hex (``RRGGBB``), no ``#`` — DrawingML's ``srgbClr`` form."""
        return f"{self.r:02X}{self.g:02X}{self.b:02X}"


# --------------------------------------------------------------------------- theme colour


# The DrawingML colour-scheme slots an ``a:schemeClr`` can name (ECMA-376 §20.1.10.16), plus the
# style-matrix placeholder ``phClr``.
SchemeSlot = Literal[
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
    "bg1",
    "tx1",
    "bg2",
    "tx2",
    "phClr",
]

# The colour transforms DrawingML stacks on a base colour, in document order (ECMA-376 §20.1.2.3).
ColorTransformKind = Literal["lumMod", "lumOff", "shade", "tint", "alpha", "satMod"]


class ColorTransform(BaseModel):
    """One ``a:lumMod``/``a:shade``/… modifier. ``value`` is the OOXML fraction in ``[0, 1]``
    (DrawingML stores these as 1000ths of a percent; the IR normalises to a fraction)."""

    model_config = _FROZEN

    kind: ColorTransformKind
    value: float = Field(ge=0.0, le=1.0)


class ThemeColorRef(BaseModel):
    """A reference to a theme colour-scheme slot plus an ordered transform stack
    (``a:schemeClr val="…"`` with child ``a:lumMod`` etc.). Usable anywhere an :class:`Rgba`
    is — see :data:`ColorSpec` — so callers can defer resolution to theme-aware backends."""

    model_config = _FROZEN

    kind: Literal["theme"] = "theme"
    slot: SchemeSlot
    transforms: tuple[ColorTransform, ...] = ()


# A colour the IR can carry: either a resolved RGBA or an unresolved theme reference. New fields
# accept either; the long-standing ``Rgba``-typed fields stay concrete so ``.hex`` keeps working.
type ColorSpec = Rgba | ThemeColorRef


class Box(BaseModel):
    """An axis-aligned position and size, in EMUs."""

    model_config = _FROZEN

    x: int
    y: int
    width: int
    height: int


class Point(BaseModel):
    """A 2-D point in EMUs (used by connectors and custom geometry)."""

    model_config = _FROZEN

    x: int
    y: int


# --------------------------------------------------------------------------- fills


class SolidFill(BaseModel):
    """A flat colour fill (``a:solidFill``)."""

    model_config = _FROZEN

    kind: Literal["solid"] = "solid"
    color: Rgba


class GradientStop(BaseModel):
    """One colour stop of a gradient; ``pos`` is a fraction in ``[0, 1]``."""

    model_config = _FROZEN

    pos: float = Field(ge=0.0, le=1.0)
    color: Rgba


class GradientFill(BaseModel):
    """A linear or radial gradient (``a:gradFill``). ``angle_deg`` is the CSS angle
    (clockwise from 12 o'clock) for linear fills; ignored when ``radial``."""

    model_config = _FROZEN

    kind: Literal["gradient"] = "gradient"
    stops: tuple[GradientStop, ...] = Field(min_length=2)
    angle_deg: float = 180.0
    radial: bool = False


class SrcRect(BaseModel):
    """A picture crop (``a:srcRect``) as fractions inset from each edge, in ``[0, 1]``.
    ``left=0.1`` drops the leftmost 10% of the source image, matching DrawingML's convention."""

    model_config = _FROZEN

    left: float = Field(default=0.0, ge=0.0, le=1.0)
    top: float = Field(default=0.0, ge=0.0, le=1.0)
    right: float = Field(default=0.0, ge=0.0, le=1.0)
    bottom: float = Field(default=0.0, ge=0.0, le=1.0)


class PictureFill(BaseModel):
    """A bitmap fill (``a:blipFill``). ``data`` is the raw image bytes; ``ext`` is the
    lower-case file extension (``png``/``jpeg``/``gif``). Used for native ``<img>`` and
    ``background-image:url()`` as well as the raster fallback for un-mappable elements.

    ``crop`` carries an optional source-rect inset; ``mode`` is how the blip fills the shape
    (``stretch`` = ``a:stretch``, ``tile`` = ``a:tile``).

    ``raster_role`` is an optional marker used for decorative raster layers emitted by the
    forward writer; the reverse reader recognises the marker and restores ``<img>`` with
    ``data-domoxml-raster`` metadata so round-trips are stable."""

    model_config = _FROZEN

    kind: Literal["picture"] = "picture"
    data: bytes
    ext: Literal["png", "jpeg", "gif"] = "png"
    crop: SrcRect | None = None
    mode: Literal["stretch", "tile"] = "stretch"
    # Optional SVG source bytes — when set the forward writer embeds BOTH the raster PNG
    # (a:blip) and the original SVG (asvg:svgBlip extension), preserving vector fidelity.
    svg_data: bytes | None = None
    # Marker for decorative raster layers so the reverse reader can round-trip them.
    raster_role: str | None = None


class PortableFallback(BaseModel):
    """An isolated picture used only when a target renderer cannot paint a native feature.

    The semantic node remains authoritative and editable. ``box`` is the paint-bound crop in
    slide coordinates, which may be larger than the owning shape when an effect overflows.
    """

    model_config = _FROZEN

    box: Box
    picture: PictureFill


class PatternFill(BaseModel):
    """A two-colour preset pattern (``a:pattFill``). ``preset`` is the DrawingML pattern name
    (e.g. ``"pct50"``, ``"ltHorz"``, ``"diagCross"``); ``fg``/``bg`` are its foreground and
    background colours."""

    model_config = _FROZEN

    kind: Literal["pattern"] = "pattern"
    preset: str
    fg: ColorSpec
    bg: ColorSpec


type Fill = Annotated[
    SolidFill | GradientFill | PictureFill | PatternFill,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- stroke / line


# Line dash styles (CSS ``border-style`` ⟷ ``a:prstDash``).
DashStyle = Literal["solid", "dash", "dot", "dashDot", "lgDash", "sysDash"]
# Stroke end cap (``a:ln cap``) and join (``a:round``/``a:bevel``/``a:miter``).
LineCap = Literal["flat", "round", "square"]
LineJoin = Literal["round", "bevel", "miter"]
# Arrowhead geometry (``a:headEnd``/``a:tailEnd``).
ArrowheadType = Literal["none", "triangle", "stealth", "diamond", "oval", "arrow"]
ArrowheadSize = Literal["sm", "med", "lg"]


class Arrowhead(BaseModel):
    """A line-end decoration (``a:headEnd``/``a:tailEnd``)."""

    model_config = _FROZEN

    type: ArrowheadType = "none"
    width: ArrowheadSize = "med"
    length: ArrowheadSize = "med"


class Line(BaseModel):
    """A shape outline (``a:ln``). ``width_emu`` > 0; ``dash`` maps CSS border-style.

    A line is normally a single solid colour; ``gradient`` carries an optional gradient stroke
    (``a:gradFill`` inside ``a:ln``) when present, in which case ``color`` is the flat fallback.
    ``head``/``tail`` are arrowheads for connectors and open paths."""

    model_config = _FROZEN

    color: Rgba
    width_emu: int = Field(gt=0)
    dash: DashStyle = "solid"
    cap: LineCap = "flat"
    join: LineJoin = "round"
    gradient: GradientFill | None = None
    head: Arrowhead | None = None
    tail: Arrowhead | None = None


class SideLines(BaseModel):
    """Per-side outlines (``a:lnT``/``a:lnR``/``a:lnB``/``a:lnL`` on table cells, or four CSS
    border sides). Each side is independent and optional; ``None`` means no border on that side."""

    model_config = _FROZEN

    top: Line | None = None
    right: Line | None = None
    bottom: Line | None = None
    left: Line | None = None


# --------------------------------------------------------------------------- effects


class Shadow(BaseModel):
    """A drop shadow (``a:outerShdw``/``a:innerShdw``) from CSS ``box-shadow``.
    ``spread_emu`` is the shadow grow/choke (CSS spread radius); 0 when absent."""

    model_config = _FROZEN

    kind: Literal["shadow"] = "shadow"
    color: Rgba
    blur_emu: int = Field(ge=0)
    distance_emu: int = Field(ge=0)
    direction_deg: float = 90.0  # OOXML angle: 0 = right, 90 = down
    inset: bool = False
    spread_emu: int = 0


class Glow(BaseModel):
    """A glow halo (``a:glow``). ``radius_emu`` is the halo size."""

    model_config = _FROZEN

    kind: Literal["glow"] = "glow"
    color: Rgba
    radius_emu: int = Field(ge=0)


class Blur(BaseModel):
    """A blur effect (``a:blur``). ``radius_emu`` is the blur radius."""

    model_config = _FROZEN

    kind: Literal["blur"] = "blur"
    radius_emu: int = Field(ge=0)


class SoftEdge(BaseModel):
    """A soft-edge feather (``a:softEdge``). ``radius_emu`` is the feather radius."""

    model_config = _FROZEN

    kind: Literal["softEdge"] = "softEdge"
    radius_emu: int = Field(ge=0)


class Reflection(BaseModel):
    """A reflection (``a:reflection``) — the minimal set of parameters: ``blur_emu`` (blur of
    the reflected copy), ``distance_emu`` (gap below the shape), and ``start_alpha``/``end_alpha``
    (opacity fade of the reflection, fractions in ``[0, 1]``)."""

    model_config = _FROZEN

    kind: Literal["reflection"] = "reflection"
    blur_emu: int = Field(default=0, ge=0)
    distance_emu: int = Field(default=0, ge=0)
    start_alpha: float = Field(default=1.0, ge=0.0, le=1.0)
    end_alpha: float = Field(default=0.0, ge=0.0, le=1.0)


FillOverlayBlend = Literal["mult", "screen", "darken", "lighten"]


class FillOverlay(BaseModel):
    """An additional solid fill blended with the owning shape's base fill
    (``a:fillOverlay``)."""

    model_config = _FROZEN

    kind: Literal["fillOverlay"] = "fillOverlay"
    fill: SolidFill
    blend: FillOverlayBlend


type Effect = Annotated[
    Shadow | Glow | Blur | SoftEdge | Reflection | FillOverlay,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- text / shapes


class Hyperlink(BaseModel):
    """A run hyperlink (``a:hlinkClick``). Either an external ``url`` or an internal jump to a
    zero-based ``slide_index`` (a ``ppaction://hlinksldjump`` relationship)."""

    model_config = _FROZEN

    url: str | None = None
    slide_index: int | None = Field(default=None, ge=0)


class TextRun(BaseModel):
    """A run of text with its resolved typography.

    ``underline`` is ``False``/``True`` (single) or a DrawingML underline-style token
    (``"dbl"``, ``"heavy"``, …); ``caps`` maps ``a:rPr cap`` / CSS ``text-transform``;
    ``letter_spacing_pt`` maps ``a:rPr spc`` / CSS ``letter-spacing`` (points, may be negative)."""

    model_config = _FROZEN

    text: str
    font_family: str
    size_pt: float = Field(gt=0)
    bold: bool = False
    bold_inherited: bool = False
    italic: bool = False
    underline: bool | str = False
    strike: bool = False
    caps: Literal["all", "small"] | None = None
    letter_spacing_pt: float = 0.0
    color: Rgba = Rgba(r=0, g=0, b=0)
    hyperlink: Hyperlink | None = None


class LineSpacing(BaseModel):
    """Paragraph line spacing (``a:lnSpc``). Exactly one variant is set: ``percent`` (a multiple,
    ``1.0`` = single) maps ``a:spcPct``; ``points`` maps ``a:spcPts`` (a fixed leading)."""

    model_config = _FROZEN

    percent: float | None = Field(default=None, gt=0.0)
    points: float | None = Field(default=None, gt=0.0)


class CharBullet(BaseModel):
    """A character bullet (``a:buChar``). ``char`` is the glyph; ``font`` is its ``a:buFont``."""

    model_config = _FROZEN

    kind: Literal["char"] = "char"
    char: str
    font: str | None = None


class AutoNumberBullet(BaseModel):
    """An auto-numbered bullet (``a:buAutoNum``). ``scheme`` is the DrawingML numbering scheme
    (e.g. ``"arabicPeriod"``, ``"alphaLcParenR"``); ``start_at`` is the 1-based start value."""

    model_config = _FROZEN

    kind: Literal["autoNumber"] = "autoNumber"
    scheme: str
    start_at: int = Field(default=1, ge=1)


type Bullet = Annotated[CharBullet | AutoNumberBullet, Field(discriminator="kind")]


class TextParagraph(BaseModel):
    """One text paragraph with ordered inline runs and its paragraph-level formatting.

    Spacing and margins are points/EMUs as their names say; ``level`` is the 0-based outline/list
    level (``a:pPr lvl``); ``bullet`` is ``None`` (no bullet) or a char/auto-number bullet."""

    model_config = _FROZEN

    runs: tuple[TextRun, ...] = ()
    align: Literal["left", "center", "right", "justify"] = "left"
    line_spacing: LineSpacing | None = None
    space_before_pt: float | None = Field(default=None, ge=0.0)
    space_after_pt: float | None = Field(default=None, ge=0.0)
    indent_pt: float = 0.0
    left_margin_pt: float = 0.0
    level: int = Field(default=0, ge=0)
    bullet: Bullet | None = None


class TextBody(BaseModel):
    """Editable text content for a shape.

    ``anchor`` is the vertical text anchor (``a:bodyPr anchor``); ``autofit`` maps ``a:noAutofit``
    /``a:normAutofit``/``a:spAutoFit``; ``columns``/``column_gap_emu`` map ``a:bodyPr numCol``/
    ``spcCol``; ``margins`` stores left/top/right/bottom text insets (``lIns``/``tIns``/``rIns``/
    ``bIns``) in EMUs."""

    model_config = _FROZEN

    paragraphs: tuple[TextParagraph, ...]
    anchor: Literal["top", "middle", "bottom"] = "top"
    autofit: Literal["none", "normal", "shape"] = "normal"
    columns: int = Field(default=1, ge=1)
    column_gap_emu: int = Field(default=0, ge=0)
    margins: tuple[int, int, int, int] = (0, 0, 0, 0)


# --------------------------------------------------------------------------- geometry


# A preset DrawingML shape (``a:prstGeom prst="…"``). A representative subset of the 187
# presets — the ones with a clean CSS/SVG source — kept as an explicit literal so backends can
# switch exhaustively. ``rect``/``roundRect``/``ellipse`` are the historical trio.
GeometryKind = Literal[
    "rect",
    "roundRect",
    "ellipse",
    "triangle",
    "rtTriangle",
    "diamond",
    "pentagon",
    "hexagon",
    "octagon",
    "parallelogram",
    "trapezoid",
    "chevron",
    "plus",
    "star4",
    "star5",
    "star8",
    "rightArrow",
    "leftArrow",
    "upArrow",
    "downArrow",
]

# Backwards-compatible alias for the historical three-preset geometry. ``ShapeNode.geom`` keeps
# this name; new presets are also accepted because ``Geometry`` now widens to ``GeometryKind``.
type Geometry = GeometryKind


# Normalised custom-path commands (``a:path`` children). Coordinates are **absolute EMUs** in the
# shape's local path space (``a:path`` declares ``w``/``h`` and uses the same units): ``move`` =
# ``a:moveTo``, ``line`` = ``a:lnTo``, ``cubic`` = ``a:cubicBezTo`` (two control points + end),
# ``quad`` = ``a:quadBezTo`` (one control point + end), ``close`` = ``a:close``.
class MoveTo(BaseModel):
    """``a:moveTo`` — start a new sub-path at ``to``."""

    model_config = _FROZEN

    kind: Literal["move"] = "move"
    to: Point


class LineTo(BaseModel):
    """``a:lnTo`` — straight segment to ``to``."""

    model_config = _FROZEN

    kind: Literal["line"] = "line"
    to: Point


class CubicTo(BaseModel):
    """``a:cubicBezTo`` — cubic Bézier with control points ``c1``/``c2`` ending at ``to``."""

    model_config = _FROZEN

    kind: Literal["cubic"] = "cubic"
    c1: Point
    c2: Point
    to: Point


class QuadTo(BaseModel):
    """``a:quadBezTo`` — quadratic Bézier with control point ``c1`` ending at ``to``."""

    model_config = _FROZEN

    kind: Literal["quad"] = "quad"
    c1: Point
    to: Point


class ClosePath(BaseModel):
    """``a:close`` — close the current sub-path."""

    model_config = _FROZEN

    kind: Literal["close"] = "close"


type PathCommand = Annotated[
    MoveTo | LineTo | CubicTo | QuadTo | ClosePath,
    Field(discriminator="kind"),
]


class CustomGeometry(BaseModel):
    """A free-form geometry (``a:custGeom``). ``path`` is a normalised command list in absolute
    EMUs (see :data:`PathCommand`); ``width_emu``/``height_emu`` are the path coordinate space
    (``a:path w/h``); ``adjust`` carries named adjust-handle values (``a:gd`` guides)."""

    model_config = _FROZEN

    width_emu: int = Field(gt=0)
    height_emu: int = Field(gt=0)
    path: tuple[PathCommand, ...] = ()
    adjust: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- transform


class Transform(BaseModel):
    """A shape's 2-D transform (``a:xfrm``): rotation in degrees plus horizontal/vertical flips.
    The identity transform (no rotation, no flips) is the default and emits nothing."""

    model_config = _FROZEN

    rotation_deg: float = 0.0
    flip_h: bool = False
    flip_v: bool = False


# --------------------------------------------------------------------------- shapes / nodes


class SourceProvenance(BaseModel):
    """Where a canvas node came from and how it relates to its source visual.

    ``source_id`` is the source-format-local identifier (a DOM capture/index or PowerPoint
    ``p:cNvPr/@id``). ``owner_node_id`` links decomposed or flattened children back to the
    canonical node that owns them; ``role`` identifies the component's job within that owner.
    """

    model_config = _FROZEN

    source_format: Literal["html", "pptx"]
    source_id: str = Field(min_length=1, max_length=512)
    source_part: str | None = Field(default=None, max_length=512)
    owner_node_id: str | None = Field(default=None, min_length=1, max_length=512)
    role: str | None = Field(default=None, min_length=1, max_length=128)


class CanvasNode(BaseModel):
    """Identity and provenance shared by every positioned Canvas IR node.

    Node IDs are slide-scoped opaque strings. A node constructed independently may omit its ID;
    :class:`SlideIR` assigns a deterministic ``node-N`` path when it adopts the node.
    """

    model_config = _FROZEN

    node_id: str | None = Field(default=None, min_length=1, max_length=512)
    provenance: SourceProvenance | None = None


class PreservationRelationship(BaseModel):
    """One relationship retained inside an opaque source-format payload.

    Internal ``target`` values are normalized package-absolute part names; external targets keep
    their original URI. Relationship IDs remain local to the owning root or preserved part.
    """

    model_config = _FROZEN

    id: str = Field(min_length=1, max_length=512)
    type: str = Field(min_length=1, max_length=2048)
    target: str = Field(min_length=1, max_length=4096)
    target_mode: Literal["Internal", "External"] = "Internal"


class PreservationPart(BaseModel):
    """One dependent OPC part plus the relationships it owns."""

    model_config = ConfigDict(frozen=True, ser_json_bytes="base64", val_json_bytes="base64")

    name: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=1, max_length=1024)
    data: bytes
    relationships: tuple[PreservationRelationship, ...] = ()


class PreservationPayload(BaseModel):
    """Opaque source content attached to its owning canvas node for lossless re-emission."""

    model_config = ConfigDict(frozen=True, ser_json_bytes="base64", val_json_bytes="base64")

    source_format: Literal["pptx"] = "pptx"
    kind: str = Field(min_length=1, max_length=128)
    root_xml: str = Field(min_length=1)
    relationships: tuple[PreservationRelationship, ...] = ()
    parts: tuple[PreservationPart, ...] = ()
    ambient_theme: PreservationPart | None = None


class PreservedNode(CanvasNode):
    """A positioned source object awaiting a semantic adapter but retained for source export.

    The node participates in normal stacking and identity. Alternate-format serializers may emit
    ``fallback`` as a renderer-derived element layer while metadata-aware source export continues
    to re-emit :attr:`payload`. The fallback is therefore a visual representation, not a
    replacement for the retained source object.
    """

    model_config = _FROZEN

    box: Box
    payload: PreservationPayload
    fallback: PictureFill | None = None


class ShapeNode(CanvasNode):
    """One positioned element. Stacking is the order within :attr:`SlideIR.contents`.

    ``geom`` is a preset name; ``custom_geom`` overrides it with a free-form path when set.
    ``effects`` is the ordered effect list (shadow/glow/blur/…); :attr:`shadow` remains as a
    backward-compatible accessor over the first shadow in that list."""

    model_config = _FROZEN

    box: Box
    geom: Geometry = "rect"
    custom_geom: CustomGeometry | None = None
    fill: Fill | None = None
    line: Line | None = None
    side_lines: SideLines | None = None
    effects: tuple[Effect, ...] = ()
    portable_fallback: PortableFallback | None = None
    transform: Transform | None = None
    corner_radius_emu: int = 0
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    text: TextBody | None = None

    @property
    def shadow(self) -> Shadow | None:
        """The first :class:`Shadow` in :attr:`effects`, or ``None`` — the historical single
        ``shadow`` field. New code should read :attr:`effects` directly."""
        return next((effect for effect in self.effects if isinstance(effect, Shadow)), None)


# --------------------------------------------------------------------------- connectors


class Connector(CanvasNode):
    """A connector shape (``p:cxnSp``): a line from ``start`` to ``end`` with a routing
    ``kind`` (``straight`` = ``line``, ``bent`` = ``bentConnector``, ``curved`` =
    ``curvedConnector``). ``line`` carries the stroke and any arrowheads."""

    model_config = _FROZEN

    start: Point
    end: Point
    kind: Literal["straight", "bent", "curved"] = "straight"
    line: Line


# --------------------------------------------------------------------------- group / table


class GroupNode(CanvasNode):
    """A shape group (``p:grpSp``). ``box`` is the group's slide-space position/size; ``child_box``
    is the child coordinate space (``a:grpSpPr/a:xfrm`` ``a:chOff``/``a:chExt``) children are
    positioned within, so a group can scale/offset its contents. ``children`` are stacked in
    order."""

    model_config = _FROZEN

    box: Box
    child_box: Box
    children: tuple[ShapeNode | GroupNode | Connector, ...] = ()
    transform: Transform | None = None


class TableCell(BaseModel):
    """One table cell (``a:tc``). ``row_span``/``col_span`` are 1 for an unmerged cell; cells a
    merge covers are represented by spans on the origin cell (consumers skip continuation cells).
    ``margins`` are ``(left, top, right, bottom)`` EMUs (``a:tcPr marL/marT/marR/marB``)."""

    model_config = _FROZEN

    text: TextBody | None = None
    fill: Fill | None = None
    borders: SideLines | None = None
    margins: tuple[int, int, int, int] = (0, 0, 0, 0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)


class TableRow(BaseModel):
    """One table row (``a:tr``). ``height_emu`` is the row's minimum height (``a:tr h``)."""

    model_config = _FROZEN

    height_emu: int = Field(ge=0)
    cells: tuple[TableCell, ...]


class TableNode(CanvasNode):
    """A table (``a:tbl`` inside a ``p:graphicFrame``). ``box`` is the table's slide-space
    position/size; ``col_widths_emu`` are the grid column widths (``a:gridCol w``); ``rows`` hold
    the cells. The grid is rectangular: every row has ``len(col_widths_emu)`` cell slots, with
    merges expressed via cell spans."""

    model_config = _FROZEN

    box: Box
    col_widths_emu: tuple[int, ...]
    rows: tuple[TableRow, ...]
    style_id: str | None = None
    first_row: bool = False
    last_row: bool = False
    first_col: bool = False
    last_col: bool = False
    band_row: bool = False
    band_col: bool = False
    header_bold_inherited: bool = False


class MediaNode(CanvasNode):
    """A video or audio element recovered from a ``p:pic`` with a ``p:videoFile``/``p:audioFile``
    relationship in the reverse (PPTX→HTML) path.

    ``box`` is the slide-space position/size.  ``media_data`` is the embedded media bytes
    (``None`` for external references, where ``media_url`` carries the URL).
    ``media_ext`` is the MIME-friendly file extension (e.g. ``"mp4"``, ``"ogg"``, ``"mp3"``).
    ``kind`` is ``"video"`` or ``"audio"``.
    ``poster_fill`` is the blip image from ``p:blipFill`` used as the poster/placeholder.
    ``play_settings_xml`` is the raw ``p:videoPr``/``p:audioPr`` XML preserved for round-trip."""

    model_config = _FROZEN

    box: Box
    kind: Literal["video", "audio"] = "video"
    media_data: bytes | None = None
    media_url: str | None = None
    media_ext: str = "mp4"
    poster_fill: PictureFill | None = None
    play_settings_xml: str | None = None


# A top-level slide node. ``ShapeNode`` is the historical default; groups, connectors, and tables
# are the richer node types. Kept open (not a discriminated union) because ``ShapeNode`` has no
# ``kind`` tag and the union members are structurally distinct.
type Node = ShapeNode | GroupNode | Connector | TableNode | MediaNode | PreservedNode


def _normalise_node_ids(nodes: tuple[Node, ...]) -> tuple[Node, ...]:
    """Assign deterministic slide-scoped IDs and reject explicit collisions."""

    used: set[str] = set()

    def normalise(node: Node, path: str) -> Node:
        node_id = node.node_id or f"node-{path}"
        if node_id in used:
            raise ValueError(f"duplicate canvas node_id: {node_id!r}")
        used.add(node_id)
        updates: dict[str, object] = {}
        if node.node_id is None:
            updates["node_id"] = node_id
        if isinstance(node, GroupNode):
            children = tuple(
                normalise(child, f"{path}.{index}")
                for index, child in enumerate(node.children, start=1)
            )
            if children != node.children:
                updates["children"] = children
        return node.model_copy(update=updates) if updates else node

    return tuple(normalise(node, str(index)) for index, node in enumerate(nodes, start=1))


# --------------------------------------------------------------------------- slide-level


# Transition direction tokens (maps from p:transition dir/through/side attrs).
TransitionDirection = Literal["l", "r", "u", "d", "lu", "ru", "ld", "rd", "horz", "vert"]

# The supported p:transition child element types.  Each string is the DrawingML local name.
TransitionType = Literal[
    "fade",
    "push",
    "wipe",
    "cut",
    "split",
    "cover",
    "uncover",
    "zoom",
    "dissolve",
    "morph",
    "none",
]


class SlideTransition(BaseModel):
    """Slide-to-slide transition (``p:transition``).

    ``type`` maps the transition XML element to an IR token; ``duration_ms`` is the optional
    advance/animation duration in milliseconds (``p:transition dur``); ``direction`` is an
    optional direction hint (``dir``, ``side``, or ``through`` attribute on the child element).
    """

    model_config = _FROZEN

    type: TransitionType = "fade"
    duration_ms: int | None = None
    direction: TransitionDirection | None = None


class SlideBackground(BaseModel):
    """Native slide background (``p:cSld/p:bg``).

    Carries a fill that applies to the full slide canvas before any shapes are drawn.
    Corresponds to ``p:bg/p:bgPr`` (with fill child) on the write path and
    ``p:cSld/p:bg`` on the read path.
    """

    model_config = _FROZEN

    fill: Fill


class SlideIR(BaseModel):
    """A single slide as a canvas of positioned nodes, sized in EMUs.

    :attr:`contents` is the canonical stacking order for every top-level visual. The historical
    ``shapes=``/``nodes=`` constructor arguments and matching properties remain compatibility
    views; new producers and serializers must use :attr:`contents` so heterogeneous nodes can
    remain interleaved.

    :attr:`transition` carries the optional slide transition; ``None`` means no transition.
    :attr:`background` carries the optional native slide background; ``None`` means no
    explicit background (the slide uses the master/layout background or is transparent)."""

    model_config = _FROZEN

    width: int
    height: int
    contents: tuple[Node, ...]
    transition: SlideTransition | None = None
    background: SlideBackground | None = None

    def __init__(
        self,
        *,
        width: int,
        height: int,
        contents: tuple[Node, ...] | None = None,
        shapes: tuple[ShapeNode, ...] | None = None,
        nodes: tuple[Node, ...] | None = None,
        transition: SlideTransition | None = None,
        background: SlideBackground | None = None,
    ) -> None:
        if contents is not None and (shapes is not None or nodes is not None):
            raise ValueError("pass contents or legacy shapes/nodes, not both")
        ordered: tuple[Node, ...] = (
            contents if contents is not None else (*(shapes or ()), *(nodes or ()))
        )
        super().__init__(
            width=width,
            height=height,
            contents=ordered,
            transition=transition,
            background=background,
        )
        object.__setattr__(self, "contents", _normalise_node_ids(self.contents))

    @property
    def shapes(self) -> tuple[ShapeNode, ...]:
        """Backward-compatible view of plain shapes in canonical stacking order."""
        return tuple(node for node in self.contents if isinstance(node, ShapeNode))

    @property
    def nodes(self) -> tuple[Node, ...]:
        """Backward-compatible view of non-shape nodes in canonical stacking order."""
        return tuple(node for node in self.contents if not isinstance(node, ShapeNode))
