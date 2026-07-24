"""Unit tests for the expanded canvas IR model: construction, validation, and the
backward-compatible accessors/normalisation helpers added in the parity work."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domoxml.core.ir.model import (
    Arrowhead,
    AutoNumberBullet,
    Blur,
    Box,
    CharBullet,
    ClosePath,
    ColorTransform,
    Connector,
    CubicTo,
    CustomGeometry,
    Glow,
    GradientFill,
    GradientStop,
    GroupNode,
    Hyperlink,
    Line,
    LineSpacing,
    MoveTo,
    PatternFill,
    PictureFill,
    Point,
    Reflection,
    Rgba,
    Shadow,
    ShapeNode,
    SideLines,
    SlideIR,
    SoftEdge,
    SolidFill,
    SourceProvenance,
    SrcRect,
    TableCell,
    TableNode,
    TableRow,
    TextBody,
    TextParagraph,
    TextRun,
    ThemeColorRef,
    Transform,
)


def _box() -> Box:
    return Box(x=0, y=0, width=914_400, height=914_400)


# --------------------------------------------------------------------------- run / text props


def test_text_run_carries_new_typography_props() -> None:
    run = TextRun(
        text="hi",
        font_family="Inter",
        size_pt=12,
        underline="dbl",
        strike=True,
        caps="all",
        letter_spacing_pt=1.5,
        hyperlink=Hyperlink(url="https://example.com"),
    )
    assert run.underline == "dbl"
    assert run.strike is True
    assert run.caps == "all"
    assert run.letter_spacing_pt == 1.5
    assert run.hyperlink is not None and run.hyperlink.url == "https://example.com"


def test_text_run_defaults_are_backward_compatible() -> None:
    run = TextRun(text="x", font_family="Inter", size_pt=10)
    assert run.underline is False
    assert run.strike is False
    assert run.caps is None
    assert run.letter_spacing_pt == 0.0
    assert run.hyperlink is None


def test_hyperlink_internal_jump_index_is_non_negative() -> None:
    assert Hyperlink(slide_index=0).slide_index == 0
    with pytest.raises(ValidationError):
        Hyperlink(slide_index=-1)


# --------------------------------------------------------------------------- paragraph props


def test_line_spacing_models_both_variants() -> None:
    assert LineSpacing(percent=1.5).percent == 1.5
    assert LineSpacing(points=18.0).points == 18.0
    with pytest.raises(ValidationError):
        LineSpacing(percent=0.0)  # gt=0


def test_paragraph_bullet_char_and_autonumber() -> None:
    char = TextParagraph(bullet=CharBullet(char="•", font="Arial"), level=1)
    assert isinstance(char.bullet, CharBullet) and char.bullet.char == "•"
    assert char.level == 1
    auto = TextParagraph(bullet=AutoNumberBullet(scheme="arabicPeriod", start_at=3))
    assert isinstance(auto.bullet, AutoNumberBullet) and auto.bullet.start_at == 3


def test_paragraph_spacing_and_margins() -> None:
    para = TextParagraph(
        line_spacing=LineSpacing(percent=2.0),
        space_before_pt=6.0,
        space_after_pt=12.0,
        indent_pt=-18.0,
        left_margin_pt=36.0,
    )
    assert para.indent_pt == -18.0
    assert para.left_margin_pt == 36.0
    with pytest.raises(ValidationError):
        TextParagraph(space_before_pt=-1.0)  # ge=0


# --------------------------------------------------------------------------- text body props


def test_text_body_anchor_autofit_columns() -> None:
    body = TextBody(
        paragraphs=(TextParagraph(),),
        anchor="middle",
        autofit="shape",
        columns=2,
        column_gap_emu=91_440,
    )
    assert body.anchor == "middle"
    assert body.autofit == "shape"
    assert body.columns == 2
    assert body.column_gap_emu == 91_440


def test_text_body_defaults_match_legacy() -> None:
    body = TextBody(paragraphs=())
    assert (body.anchor, body.autofit, body.columns, body.column_gap_emu) == ("top", "normal", 1, 0)


# --------------------------------------------------------------------------- geometry


def test_extended_preset_geometry_accepted() -> None:
    for geom in ("triangle", "hexagon", "star5", "rightArrow", "chevron"):
        assert ShapeNode(box=_box(), geom=geom).geom == geom


def test_custom_geometry_path_commands() -> None:
    geom = CustomGeometry(
        width_emu=100,
        height_emu=100,
        path=(
            MoveTo(to=Point(x=0, y=0)),
            CubicTo(c1=Point(x=10, y=0), c2=Point(x=10, y=10), to=Point(x=10, y=10)),
            ClosePath(),
        ),
        adjust={"adj1": 0.5},
    )
    assert [cmd.kind for cmd in geom.path] == ["move", "cubic", "close"]
    assert geom.adjust["adj1"] == 0.5
    node = ShapeNode(box=_box(), custom_geom=geom)
    assert node.custom_geom is geom


def test_custom_geometry_requires_positive_space() -> None:
    with pytest.raises(ValidationError):
        CustomGeometry(width_emu=0, height_emu=100)


# --------------------------------------------------------------------------- connectors


def test_connector_construction() -> None:
    conn = Connector(
        start=Point(x=0, y=0),
        end=Point(x=100, y=100),
        kind="bent",
        line=Line(color=Rgba(r=0, g=0, b=0), width_emu=9_525, tail=Arrowhead(type="triangle")),
    )
    assert conn.kind == "bent"
    assert conn.line.tail is not None and conn.line.tail.type == "triangle"


# --------------------------------------------------------------------------- fills


def test_pattern_fill_accepts_rgba_and_theme_colors() -> None:
    fill = PatternFill(
        preset="pct50",
        fg=Rgba(r=0, g=0, b=0),
        bg=ThemeColorRef(slot="bg1"),
    )
    assert fill.kind == "pattern"
    assert isinstance(fill.bg, ThemeColorRef) and fill.bg.slot == "bg1"


def test_theme_color_ref_transforms() -> None:
    ref = ThemeColorRef(
        slot="accent1",
        transforms=(
            ColorTransform(kind="lumMod", value=0.6),
            ColorTransform(kind="tint", value=0.2),
        ),
    )
    assert [t.kind for t in ref.transforms] == ["lumMod", "tint"]
    with pytest.raises(ValidationError):
        ColorTransform(kind="shade", value=1.5)  # le=1.0


def test_picture_fill_crop_and_mode() -> None:
    fill = PictureFill(data=b"x", crop=SrcRect(left=0.1, right=0.1), mode="tile")
    assert fill.mode == "tile"
    assert fill.crop is not None and fill.crop.left == 0.1
    with pytest.raises(ValidationError):
        SrcRect(left=1.5)  # le=1.0


def test_fill_discriminator_round_trips() -> None:
    fill = PatternFill(preset="ltHorz", fg=Rgba(r=1, g=2, b=3), bg=Rgba(r=4, g=5, b=6))
    # validate_python via model rebuild: pattern stays a PatternFill under the discriminated union.
    node = ShapeNode(box=_box(), fill=fill)
    assert isinstance(node.fill, PatternFill)


# --------------------------------------------------------------------------- line model


def test_line_per_side_dash_cap_join_arrowheads() -> None:
    side = SideLines(
        top=Line(
            color=Rgba(r=0, g=0, b=0), width_emu=9_525, dash="dashDot", cap="round", join="miter"
        ),
        bottom=Line(color=Rgba(r=0, g=0, b=0), width_emu=9_525, head=Arrowhead(type="oval")),
    )
    assert side.top is not None and side.top.dash == "dashDot"
    assert side.right is None
    assert side.bottom is not None and side.bottom.head is not None
    node = ShapeNode(box=_box(), side_lines=side)
    assert node.side_lines is side


def test_line_gradient_stroke() -> None:
    grad = GradientFill(
        stops=(
            GradientStop(pos=0, color=Rgba(r=0, g=0, b=0)),
            GradientStop(pos=1, color=Rgba(r=255, g=255, b=255)),
        )
    )
    line = Line(color=Rgba(r=0, g=0, b=0), width_emu=9_525, gradient=grad)
    assert line.gradient is not None and len(line.gradient.stops) == 2


# --------------------------------------------------------------------------- effects


def test_effects_list_and_shadow_accessor() -> None:
    shadow = Shadow(color=Rgba(r=0, g=0, b=0), blur_emu=1, distance_emu=2, spread_emu=3)
    node = ShapeNode(
        box=_box(),
        effects=(Glow(color=Rgba(r=1, g=1, b=1), radius_emu=5), shadow, Blur(radius_emu=2)),
    )
    # The backward-compatible accessor returns the first Shadow in the list.
    recovered = node.shadow
    assert recovered is not None
    assert recovered is shadow
    assert recovered.spread_emu == 3


def test_shadow_accessor_none_when_no_shadow() -> None:
    node = ShapeNode(box=_box(), effects=(Glow(color=Rgba(r=0, g=0, b=0), radius_emu=1),))
    assert node.shadow is None
    assert ShapeNode(box=_box()).shadow is None


def test_soft_edge_and_reflection_construct() -> None:
    assert SoftEdge(radius_emu=10).radius_emu == 10
    refl = Reflection(blur_emu=5, distance_emu=10, start_alpha=0.5, end_alpha=0.0)
    assert refl.start_alpha == 0.5
    with pytest.raises(ValidationError):
        Reflection(start_alpha=2.0)  # le=1.0


# --------------------------------------------------------------------------- nodes / transform


def test_transform_rotation_and_flips() -> None:
    node = ShapeNode(box=_box(), transform=Transform(rotation_deg=45, flip_h=True, flip_v=False))
    assert node.transform is not None
    assert node.transform.rotation_deg == 45
    assert node.transform.flip_h is True


def test_group_node_children_and_child_box() -> None:
    child = ShapeNode(box=_box())
    group = GroupNode(box=_box(), child_box=_box(), children=(child,))
    assert group.children == (child,)
    # Groups can nest groups.
    outer = GroupNode(box=_box(), child_box=_box(), children=(group,))
    assert isinstance(outer.children[0], GroupNode)


def test_table_node_grid_cells_spans_borders() -> None:
    cell = TableCell(
        text=TextBody(paragraphs=()),
        fill=SolidFill(color=Rgba(r=255, g=0, b=0)),
        borders=SideLines(top=Line(color=Rgba(r=0, g=0, b=0), width_emu=9_525)),
        margins=(1, 2, 3, 4),
        col_span=2,
    )
    table = TableNode(
        box=_box(),
        col_widths_emu=(100, 200),
        rows=(TableRow(height_emu=50, cells=(cell,)),),
    )
    assert table.col_widths_emu == (100, 200)
    assert table.rows[0].cells[0].col_span == 2
    assert table.rows[0].cells[0].margins == (1, 2, 3, 4)
    with pytest.raises(ValidationError):
        TableCell(col_span=0)  # ge=1


def test_slide_carries_extended_nodes_alongside_shapes() -> None:
    shape = ShapeNode(box=_box())
    shape_after = ShapeNode(box=_box())
    table = TableNode(box=_box(), col_widths_emu=(100,), rows=())
    slide = SlideIR(width=100, height=100, shapes=(shape,), nodes=(table,))
    assert [node.node_id for node in slide.contents] == ["node-1", "node-2"]
    assert slide.shapes == (slide.contents[0],)
    assert slide.nodes == (slide.contents[1],)
    ordered = SlideIR(width=100, height=100, contents=(shape, table, shape_after))
    assert ordered.shapes == (ordered.contents[0], ordered.contents[2])
    assert ordered.nodes == (ordered.contents[1],)
    assert ordered.model_dump().keys() == {
        "width",
        "height",
        "contents",
        "transition",
        "background",
        "renderer_fallback",
    }
    assert SlideIR.model_validate(ordered.model_dump()) == ordered
    legacy_data = {
        "width": 100,
        "height": 100,
        "shapes": [shape.model_dump()],
        "nodes": [table.model_dump()],
    }
    assert [node.node_id for node in SlideIR.model_validate(legacy_data).contents] == [
        "node-1",
        "node-2",
    ]
    with pytest.raises(ValueError, match="contents or legacy"):
        SlideIR(width=100, height=100, contents=(shape,), shapes=(shape,))
    assert SlideIR(width=100, height=100, shapes=()).nodes == ()


def test_slide_preserves_explicit_ids_and_assigns_nested_group_paths() -> None:
    child = ShapeNode(box=_box())
    group = GroupNode(box=_box(), child_box=_box(), children=(child,))
    explicit = ShapeNode(
        node_id="hero",
        provenance=SourceProvenance(source_format="html", source_id="hero-element"),
        box=_box(),
    )

    slide = SlideIR(width=100, height=100, contents=(explicit, group))

    assert slide.contents[0].node_id == "hero"
    adopted_group = slide.contents[1]
    assert isinstance(adopted_group, GroupNode)
    assert adopted_group.node_id == "node-2"
    assert adopted_group.children[0].node_id == "node-2.1"
    assert SlideIR.model_validate(slide.model_dump()) == slide


def test_slide_rejects_duplicate_node_ids_including_group_children() -> None:
    duplicate = ShapeNode(node_id="same", box=_box())
    group = GroupNode(
        node_id="group",
        box=_box(),
        child_box=_box(),
        children=(duplicate,),
    )
    with pytest.raises(ValueError, match="duplicate canvas node_id"):
        SlideIR(width=100, height=100, contents=(duplicate, group))


def test_models_are_frozen() -> None:
    node = ShapeNode(box=_box())
    with pytest.raises(ValidationError):
        node.opacity = 0.5  # type: ignore[misc]
