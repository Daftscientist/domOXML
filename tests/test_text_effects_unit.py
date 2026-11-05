"""Run-level text effects: the cases a one-property round trip would not notice."""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element, fromstring

from domoxml.core.drawingml.shape import _run  # pyright: ignore[reportPrivateUsage]
from domoxml.core.ir.model import GradientFill, GradientStop, Rgba, TextRun
from domoxml.slides.inherit import ThemeContext
from domoxml.slides.text_read import read_text_run

NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def element(markup: str) -> Element:
    return fromstring(markup.replace("<a:r>", f"<a:r {NS}>").replace("<a:rPr>", f"<a:rPr {NS}>"))


def gradient(first: str, last: str) -> str:
    return (
        "<a:gradFill><a:gsLst>"
        f'<a:gs pos="0"><a:srgbClr val="{first}"/></a:gs>'
        f'<a:gs pos="100000"><a:srgbClr val="{last}"/></a:gs>'
        '</a:gsLst><a:lin ang="0"/></a:gradFill>'
    )


def solid(colour: str) -> str:
    return f'<a:solidFill><a:srgbClr val="{colour}"/></a:solidFill>'


def read(run_properties: str, *, inherited: str | None = None) -> TextRun | None:
    run = element(f"<a:r><a:rPr sz='2000'>{run_properties}</a:rPr><a:t>Text</a:t></a:r>")
    fallback = element(f"<a:rPr>{inherited}</a:rPr>") if inherited is not None else None
    return read_text_run(run, {}, lambda _: None, fallback_rpr=fallback)


def test_gradient_stops_keep_their_own_alpha_instead_of_the_fallback_colours() -> None:
    # A transparent-to-blue gradient has a transparent first stop, which is also the run's
    # fallback colour. Multiplying every stop by it would make the whole gradient invisible.
    clear = Rgba(r=0, g=0, b=0, a=0.0)
    stops = (
        GradientStop(pos=0.0, color=clear),
        GradientStop(pos=1.0, color=Rgba(r=0, g=0, b=255)),
    )
    run = TextRun(
        text="Fade",
        font_family="Inter",
        size_pt=40,
        color=clear,
        gradient=GradientFill(stops=stops),
    )

    xml = _run(run, lambda _: None)

    pattern = r'<a:gs pos="(\d+)"><a:srgbClr val="\w+">(?:<a:alpha val="(\d+)"/>)?'
    stops = re.findall(pattern, xml)
    # Subdivided like a fill's, each stop keeping its own alpha: transparent to opaque blue.
    assert stops[0] == ("0", "0") and stops[-1] == ("100000", ""), "the blue stop stays opaque"
    alphas = [int(alpha or "100000") for _, alpha in stops]
    assert alphas == sorted(alphas) and len(set(alphas)) > 2


def test_an_explicit_run_fill_beats_an_inherited_gradient() -> None:
    run = read(solid("CC2200"), inherited=gradient("000000", "FFFFFF"))

    assert run is not None
    assert run.gradient is None and run.color.hex == "CC2200"


def test_a_run_with_no_fill_of_its_own_still_inherits_the_gradient() -> None:
    run = read("", inherited=gradient("FF0000", "0000FF"))

    assert run is not None and run.gradient is not None and run.color.hex == "FF0000"


def test_a_run_with_no_fill_reads_as_transparent_text() -> None:
    outline = f'<a:ln w="12700">{solid("CC2200")}</a:ln><a:noFill/>'

    run = read(outline)

    assert run is not None and run.color.a == 0.0 and run.outline is not None


def test_text_that_names_no_typeface_is_set_in_the_theme_body_font() -> None:
    # PowerPoint sets such text in the theme's minor font; a bare ``sans-serif`` is far wider
    # than Calibri, so every line of it wrapped at different words.
    theme = ThemeContext(major_latin="Calibri Light", minor_latin="Calibri", colors={})
    run = element("<a:r><a:rPr sz='1800'/><a:t>Text</a:t></a:r>")
    bare = element("<a:r><a:t>Text</a:t></a:r>")

    with_properties = read_text_run(run, {}, lambda _: None, theme_ctx=theme)
    without_properties = read_text_run(bare, {}, lambda _: None, theme_ctx=theme)

    assert with_properties is not None and with_properties.font_family == "Calibri"
    assert without_properties is not None and without_properties.font_family == "Calibri"


def test_text_with_no_size_anywhere_in_its_chain_is_18pt_like_powerpoint() -> None:
    plain = read_text_run(
        element("<a:r><a:rPr/><a:t>Text</a:t></a:r>"), {}, lambda _: None, theme_ctx=None
    )
    bare = read_text_run(element("<a:r><a:t>Text</a:t></a:r>"), {}, lambda _: None)
    sized = read_text_run(
        element("<a:r><a:rPr sz='1400'/><a:t>Text</a:t></a:r>"), {}, lambda _: None
    )

    assert plain is not None and plain.size_pt == 18.0
    assert bare is not None and bare.size_pt == 18.0
    assert sized is not None and sized.size_pt == 14.0
