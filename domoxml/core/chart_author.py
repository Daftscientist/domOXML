"""Author a native chart part from a small data spec.

HTML has no chart element, so a chart is written as ``data-chart='{...}'`` on a block: a type
(``bar``, ``column``, ``line``, ``pie``), the category labels and one or more named series. The
spec becomes a real ``c:chartSpace`` part (its data cached beside an embedded workbook, so
PowerPoint draws it, styles it and opens Edit Data natively), wrapped in the graphic frame that
places it on the slide.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass
from typing import cast
from xml.sax.saxutils import escape

from domoxml.core.ir.model import (
    Box,
    PreservationPart,
    PreservationPayload,
    PreservationRelationship,
)

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_GRIDLINES = (
    '<c:majorGridlines><c:spPr><a:ln w="9525"><a:solidFill><a:srgbClr val="D9D9D9"/>'
    "</a:solidFill></a:ln></c:spPr></c:majorGridlines>"
)
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS_CT = "application/vnd.openxmlformats-package.relationships+xml"
_SHEET_BASE = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_SHEET_CT = f"{_SHEET_BASE}.sheet"
_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CHART_CT = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
_PALETTE = ("4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47")
_TYPES = ("bar", "column", "line", "pie")


@dataclass(frozen=True)
class SeriesSpec:
    name: str
    values: tuple[float, ...]
    color: str | None = None


@dataclass(frozen=True)
class ChartSpec:
    kind: str
    categories: tuple[str, ...]
    series: tuple[SeriesSpec, ...]
    title: str = ""
    legend: bool | None = None


def parse_chart_spec(raw: str) -> ChartSpec | None:
    """The spec in ``raw`` if it is a well-formed chart description, else ``None``."""
    try:
        loaded: object = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(loaded, dict):
        return None
    spec = cast("dict[str, object]", loaded)
    kind = spec.get("type")
    categories = spec.get("categories")
    series = spec.get("series")
    if (
        not isinstance(kind, str)
        or kind not in _TYPES
        or not isinstance(categories, list)
        or not categories
        or not isinstance(series, list)
        or not series
    ):
        return None
    parsed: list[SeriesSpec] = []
    for item in cast("list[object]", series):
        if not isinstance(item, dict):
            return None
        fields = cast("dict[str, object]", item)
        values = fields.get("values")
        if not isinstance(values, list) or len(cast("list[object]", values)) != len(
            cast("list[object]", categories)
        ):
            return None
        numbers: list[float] = []
        for value in cast("list[object]", values):
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            try:
                number = float(value)
            except OverflowError:
                return None
            if not math.isfinite(number):
                return None
            numbers.append(number)
        name = fields.get("name")
        colour = fields.get("color")
        parsed.append(
            SeriesSpec(
                name=str(name) if name is not None else f"Series {len(parsed) + 1}",
                values=tuple(numbers),
                color=str(colour) if colour is not None else None,
            )
        )
    if kind == "pie" and len(parsed) != 1:
        return None
    title = spec.get("title")
    legend = spec.get("legend")
    return ChartSpec(
        kind=kind,
        categories=tuple(str(c) for c in cast("list[object]", categories)),
        series=tuple(parsed),
        title=str(title) if title is not None else "",
        legend=legend if isinstance(legend, bool) else None,
    )


def _colour(spec_colour: str | None, index: int) -> str:
    text = (spec_colour or "").lstrip("#").upper()
    if len(text) == 6 and all(c in "0123456789ABCDEF" for c in text):
        return text
    return _PALETTE[index % len(_PALETTE)]


def _strings(values: tuple[str, ...], tag: str) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{escape(v)}</c:v></c:pt>' for i, v in enumerate(values))
    return f'<c:{tag}><c:ptCount val="{len(values)}"/>{points}</c:{tag}>'


def _numbers(values: tuple[float, ...]) -> str:
    points = "".join(f'<c:pt idx="{i}"><c:v>{v!r}</c:v></c:pt>' for i, v in enumerate(values))
    return (
        "<c:numCache><c:formatCode>General</c:formatCode>"
        f'<c:ptCount val="{len(values)}"/>{points}</c:numCache>'
    )


def _series(spec: ChartSpec, index: int, item: SeriesSpec) -> str:
    kind = spec.kind
    colour = _colour(item.color, index)
    name = escape(item.name)
    last = len(spec.categories) + 1
    column = _column(index + 1)
    cached = _strings(spec.categories, "strCache")
    categories = f"<c:strRef><c:f>Sheet1!$A$2:$A${last}</c:f>{cached}</c:strRef>"
    numbers = _numbers(item.values)
    values = f"<c:numRef><c:f>Sheet1!${column}$2:${column}${last}</c:f>{numbers}</c:numRef>"
    if kind == "pie":
        extra = "".join(
            f'<c:dPt><c:idx val="{i}"/><c:bubble3D val="0"/><c:spPr><a:solidFill>'
            f'<a:srgbClr val="{_colour(None, i)}"/></a:solidFill></c:spPr></c:dPt>'
            for i in range(len(item.values))
        )
        shape = ""
    elif kind == "line":
        shape = (
            f'<c:spPr><a:ln w="28575" cap="rnd"><a:solidFill><a:srgbClr val="{colour}"/>'
            '</a:solidFill><a:round/></a:ln></c:spPr><c:marker><c:symbol val="circle"/>'
            '<c:size val="5"/></c:marker>'
        )
        extra = ""
    else:
        shape = f'<c:spPr><a:solidFill><a:srgbClr val="{colour}"/></a:solidFill></c:spPr>'
        extra = '<c:invertIfNegative val="0"/>'
    smooth = '<c:smooth val="0"/>' if kind == "line" else ""
    return (
        f'<c:ser><c:idx val="{index}"/><c:order val="{index}"/>'
        f'<c:tx><c:strRef><c:f>Sheet1!${column}$1</c:f><c:strCache><c:ptCount val="1"/>'
        f'<c:pt idx="0"><c:v>{name}</c:v></c:pt></c:strCache></c:strRef></c:tx>'
        f"{shape}{extra}<c:cat>{categories}</c:cat><c:val>{values}</c:val>{smooth}</c:ser>"
    )


def _column(index: int) -> str:
    """The spreadsheet column letter for a zero-based index (A, B, ... Z, AA)."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def workbook_bytes(spec: ChartSpec) -> bytes:
    """A minimal ``.xlsx`` of the chart's data: categories in column A, one column per series."""
    rows: list[str] = []
    header = "".join(
        f'<c r="{_column(i + 1)}1" t="inlineStr"><is><t>{escape(item.name)}</t></is></c>'
        for i, item in enumerate(spec.series)
    )
    rows.append(f'<row r="1">{header}</row>')
    for row, category in enumerate(spec.categories, start=2):
        cells = f'<c r="A{row}" t="inlineStr"><is><t>{escape(category)}</t></is></c>'
        for i, item in enumerate(spec.series):
            cells += f'<c r="{_column(i + 1)}{row}"><v>{item.values[row - 2]!r}</v></c>'
        rows.append(f'<row r="{row}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{_CT_NS}">'
            f'<Default Extension="rels" ContentType="{_RELS_CT}"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{_SHEET_CT}.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            f'ContentType="{_SHEET_BASE}.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_SS}" xmlns:r="{_R}">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_R}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


def chart_part_xml(spec: ChartSpec) -> bytes:
    """The ``c:chartSpace`` part for a parsed spec."""
    kind = spec.kind
    series = "".join(_series(spec, i, item) for i, item in enumerate(spec.series))
    axes = '<c:axId val="111111111"/><c:axId val="222222222"/>'
    if kind in ("bar", "column"):
        plot = (
            f'<c:barChart><c:barDir val="{"bar" if kind == "bar" else "col"}"/>'
            f'<c:grouping val="clustered"/><c:varyColors val="0"/>{series}'
            f'<c:gapWidth val="80"/>{axes}</c:barChart>'
        )
    elif kind == "line":
        plot = (
            f'<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>{series}'
            f'<c:marker val="1"/>{axes}</c:lineChart>'
        )
    else:
        plot = f'<c:pieChart><c:varyColors val="1"/>{series}<c:firstSliceAng val="0"/></c:pieChart>'
    if kind == "pie":
        axis_xml = ""
    else:
        cat_pos, val_pos = ("l", "b") if kind == "bar" else ("b", "l")
        axis_xml = (
            f'<c:catAx><c:axId val="111111111"/><c:scaling><c:orientation val="minMax"/>'
            f'</c:scaling><c:delete val="0"/><c:axPos val="{cat_pos}"/><c:numFmt '
            'formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/>'
            '<c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
            '<c:crossAx val="222222222"/><c:crosses val="autoZero"/><c:auto val="1"/>'
            '<c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
            f'<c:valAx><c:axId val="222222222"/><c:scaling><c:orientation val="minMax"/>'
            f'</c:scaling><c:delete val="0"/><c:axPos val="{val_pos}"/>{_GRIDLINES}'
            '<c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/>'
            '<c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
            '<c:crossAx val="111111111"/><c:crosses val="autoZero"/>'
            '<c:crossBetween val="between"/></c:valAx>'
        )
    title = spec.title
    title_xml = (
        f"<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p>"
        '</c:rich></c:tx><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>'
        if title
        else '<c:autoTitleDeleted val="1"/>'
    )
    legend = (
        '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>'
        if (spec.legend if spec.legend is not None else len(spec.series) > 1 or kind == "pie")
        else ""
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{_C}" xmlns:a="{_A}" xmlns:r="{_R}">'
        f'<c:roundedCorners val="0"/><c:chart>{title_xml}<c:plotArea><c:layout/>{plot}{axis_xml}'
        f'</c:plotArea>{legend}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
        '<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData></c:chartSpace>'
    )
    return xml.encode()


def chart_payload(spec: ChartSpec, box: Box) -> PreservationPayload:
    """The graphic frame placing the authored chart, with its chart part, as source to re-emit."""
    data = chart_part_xml(spec)
    name = f"ppt/charts/chart_{hashlib.sha1(data, usedforsecurity=False).hexdigest()[:10]}.xml"
    frame = (
        f'<p:graphicFrame xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}">'
        '<p:nvGraphicFramePr><p:cNvPr id="2" name="Chart"/><p:cNvGraphicFramePr/><p:nvPr/>'
        f'</p:nvGraphicFramePr><p:xfrm><a:off x="{box.x}" y="{box.y}"/>'
        f'<a:ext cx="{box.width}" cy="{box.height}"/></p:xfrm><a:graphic>'
        f'<a:graphicData uri="{_C}"><c:chart xmlns:c="{_C}" r:id="rId1"/></a:graphicData>'
        "</a:graphic></p:graphicFrame>"
    )
    workbook = workbook_bytes(spec)
    book_id = hashlib.sha1(workbook, usedforsecurity=False).hexdigest()[:10]
    book = f"ppt/embeddings/Microsoft_Excel_Sheet_{book_id}.xlsx"
    return PreservationPayload(
        kind="graphicFrame",
        root_xml=frame,
        relationships=(PreservationRelationship(id="rId1", type=f"{_R}/chart", target=name),),
        parts=(
            PreservationPart(
                name=name,
                content_type=_CHART_CT,
                data=data,
                relationships=(
                    PreservationRelationship(id="rId1", type=f"{_R}/package", target=book),
                ),
            ),
            PreservationPart(name=book, content_type=_XLSX_CT, data=workbook),
        ),
    )
