"""Unit tests for :mod:`domoxml.core.crop` — pure crop math, round-trip property."""

# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import pytest

from domoxml.core.crop import cover_crop, css_to_srcrect, srcrect_to_css
from domoxml.core.ir.model import SrcRect

# ---------------------------------------------------------------------------
# cover_crop


def test_cover_crop_wider_src_crops_left_right() -> None:
    """Source wider than dest → symmetric horizontal crop."""
    crop = cover_crop(src_w=400.0, src_h=200.0, dst_w=200.0, dst_h=200.0)
    # src_ratio=2, dst_ratio=1 → visible_frac = 0.5 → crop_each = 0.25
    assert pytest.approx(crop.left, abs=1e-9) == 0.25
    assert pytest.approx(crop.right, abs=1e-9) == 0.25
    assert crop.top == 0.0
    assert crop.bottom == 0.0


def test_cover_crop_taller_src_crops_top_bottom() -> None:
    """Source taller than dest → symmetric vertical crop."""
    crop = cover_crop(src_w=100.0, src_h=400.0, dst_w=100.0, dst_h=100.0)
    # src_ratio=0.25, dst_ratio=1 → visible_frac = 0.25 → crop_each = 0.375
    assert pytest.approx(crop.top, abs=1e-9) == 0.375
    assert pytest.approx(crop.bottom, abs=1e-9) == 0.375
    assert crop.left == 0.0
    assert crop.right == 0.0


def test_cover_crop_same_ratio_no_crop() -> None:
    """Matching aspect ratios → all fractions zero."""
    crop = cover_crop(src_w=800.0, src_h=600.0, dst_w=400.0, dst_h=300.0)
    assert crop == SrcRect()


def test_cover_crop_square_src_landscape_dst() -> None:
    """Square source, landscape destination → top/bottom crop."""
    crop = cover_crop(src_w=100.0, src_h=100.0, dst_w=200.0, dst_h=100.0)
    # src_ratio=1 < dst_ratio=2 → visible_frac = 0.5 → crop_each = 0.25
    assert pytest.approx(crop.top, abs=1e-9) == 0.25
    assert pytest.approx(crop.bottom, abs=1e-9) == 0.25
    assert crop.left == 0.0
    assert crop.right == 0.0


def test_cover_crop_zero_dimensions_returns_empty() -> None:
    """Zero dimensions don't crash — return an all-zero SrcRect."""
    assert cover_crop(src_w=0.0, src_h=100.0, dst_w=100.0, dst_h=100.0) == SrcRect()
    assert cover_crop(src_w=100.0, src_h=100.0, dst_w=0.0, dst_h=100.0) == SrcRect()


# ---------------------------------------------------------------------------
# srcrect_to_css


def test_srcrect_to_css_no_crop_fills_box() -> None:
    """No crop → image exactly fills the box."""
    css = srcrect_to_css(SrcRect(), box_w_px=200.0, box_h_px=100.0)
    assert css["position"] == "absolute"
    assert css["width"] == "200px"
    assert css["height"] == "100px"
    assert css["left"] == "0px"
    assert css["top"] == "0px"


def test_srcrect_to_css_left_right_crop() -> None:
    """25% left+right crop → image 4/3 wider, shifted left by 1/3 of original width."""
    # visible_w = 1 - 0.25 - 0.25 = 0.5 → img_w = 200/0.5 = 400
    # left_offset = -0.25 * 400 = -100
    crop = SrcRect(left=0.25, right=0.25)
    css = srcrect_to_css(crop, box_w_px=200.0, box_h_px=100.0)
    assert css["width"] == "400px"
    assert css["height"] == "100px"
    assert css["left"] == "-100px"
    assert css["top"] == "0px"


def test_srcrect_to_css_top_bottom_crop() -> None:
    """10% top + 10% bottom → image 1.25x taller, shifted up."""
    crop = SrcRect(top=0.1, bottom=0.1)
    css = srcrect_to_css(crop, box_w_px=100.0, box_h_px=100.0)
    # vis_h = 0.8 → img_h = 125; top_offset = -0.1*125 = -12.5
    assert css["width"] == "100px"
    assert css["height"] == "125px"
    assert css["left"] == "0px"
    assert css["top"] == "-12.5px"


# ---------------------------------------------------------------------------
# css_to_srcrect (inverse)


def _round_trip(crop: SrcRect, box_w: float, box_h: float) -> SrcRect:
    """Forward-then-inverse should reproduce the original crop."""
    css = srcrect_to_css(crop, box_w_px=box_w, box_h_px=box_h)
    # Parse the px values back out.
    img_w = float(css["width"].removesuffix("px"))
    img_h = float(css["height"].removesuffix("px"))
    left_off = float(css["left"].removesuffix("px"))
    top_off = float(css["top"].removesuffix("px"))
    return css_to_srcrect(
        box_w_px=box_w,
        box_h_px=box_h,
        img_w_px=img_w,
        img_h_px=img_h,
        left_offset_px=left_off,
        top_offset_px=top_off,
    )


@pytest.mark.parametrize(
    "crop",
    [
        SrcRect(),
        SrcRect(left=0.25, right=0.25),
        SrcRect(top=0.1, bottom=0.1),
        SrcRect(left=0.1, top=0.2, right=0.05, bottom=0.15),
        SrcRect(left=0.33, right=0.33),
    ],
)
def test_round_trip_property(crop: SrcRect) -> None:
    """srcrect_to_css → css_to_srcrect must reproduce the original fractions."""
    recovered = _round_trip(crop, box_w=300.0, box_h=200.0)
    assert pytest.approx(recovered.left, abs=1e-6) == crop.left
    assert pytest.approx(recovered.top, abs=1e-6) == crop.top
    assert pytest.approx(recovered.right, abs=1e-6) == crop.right
    assert pytest.approx(recovered.bottom, abs=1e-6) == crop.bottom


def test_cover_crop_round_trip() -> None:
    """cover_crop fractions can be inverted back to the original crop region."""
    crop = cover_crop(src_w=400.0, src_h=300.0, dst_w=200.0, dst_h=300.0)
    recovered = _round_trip(crop, box_w=200.0, box_h=300.0)
    assert pytest.approx(recovered.left, abs=1e-6) == crop.left
    assert pytest.approx(recovered.right, abs=1e-6) == crop.right


def test_css_to_srcrect_zero_img_size_returns_empty() -> None:
    """Zero image dimensions don't crash — return all-zero SrcRect."""
    result = css_to_srcrect(
        box_w_px=100.0,
        box_h_px=100.0,
        img_w_px=0.0,
        img_h_px=0.0,
        left_offset_px=0.0,
        top_offset_px=0.0,
    )
    assert result == SrcRect()
