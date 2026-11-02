"""Speaker notes: the notes master PowerPoint needs, one notes slide per slide, and reading them."""

from __future__ import annotations

from xml.sax.saxutils import escape

from defusedxml import ElementTree

from domoxml.core.opc import OpcPackage
from domoxml.slides import _templates as t

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
NOTES_MASTER_CT = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"
NOTES_SLIDE_CT = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"

_GROUP = (
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
)


def _placeholder(shape_id: int, name: str, kind: str, index: str, box: str, body: str) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr>'
        '<a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
        f'<p:nvPr><p:ph type="{kind}"{index}/></p:nvPr></p:nvSpPr>'
        f"<p:spPr>{box}</p:spPr>{body}</p:sp>"
    )


_SLIDE_IMAGE_BOX = (
    '<a:xfrm><a:off x="685800" y="1143000"/><a:ext cx="5486400" cy="3086100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
)
_BODY_BOX = (
    '<a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
)

NOTES_MASTER = (
    f'{t.XML_DECL}<p:notesMaster {t.NS}><p:cSld><p:bg><p:bgRef idx="1001">'
    '<a:schemeClr val="bg1"/></p:bgRef></p:bg>'
    f"<p:spTree>{_GROUP}"
    + _placeholder(2, "Slide Image Placeholder 1", "sldImg", ' idx="2"', _SLIDE_IMAGE_BOX, "")
    + _placeholder(
        3,
        "Notes Placeholder 2",
        "body",
        ' sz="quarter" idx="3"',
        _BODY_BOX,
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
        "<a:t>Click to edit Master text styles</a:t></a:r></a:p></p:txBody>",
    )
    + "</p:spTree></p:cSld>"
    '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
    'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
    'hlink="hlink" folHlink="folHlink"/>'
    '<p:notesStyle><a:lvl1pPr marL="0" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" '
    'latinLnBrk="0" hangingPunct="1"><a:defRPr sz="1200" kern="1200"><a:solidFill>'
    '<a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/>'
    '<a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr></p:notesStyle></p:notesMaster>'
)

NOTES_MASTER_RELS = (
    f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL}">'
    f'<Relationship Id="rId1" Type="{_REL}/theme" Target="../theme/theme2.xml"/></Relationships>'
)


def notes_slide_xml(text: str) -> str:
    """A notes page whose body placeholder holds ``text`` (one paragraph per line)."""
    paragraphs = "".join(
        f'<a:p><a:r><a:rPr lang="en-US"/><a:t>{escape(line)}</a:t></a:r></a:p>'
        if line
        else '<a:p><a:endParaRPr lang="en-US"/></a:p>'
        for line in text.split("\n")
    )
    return (
        f"{t.XML_DECL}<p:notes {t.NS}><p:cSld><p:spTree>{_GROUP}"
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr>'
        '<a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr>'
        '<a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr>'
        "</p:nvSpPr><p:spPr/>"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>"
        "</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>"
    )


def notes_slide_rels(slide_number: int) -> str:
    return (
        f'{t.XML_DECL}<Relationships xmlns="{_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{_REL}/notesMaster" '
        'Target="../notesMasters/notesMaster1.xml"/>'
        f'<Relationship Id="rId2" Type="{_REL}/slide" '
        f'Target="../slides/slide{slide_number}.xml"/></Relationships>'
    )


def read_notes(package: OpcPackage, slide_part: str) -> str | None:
    """The slide's speaker notes as plain text, one line per paragraph, or ``None``."""
    for relationship in package.relationships(slide_part):
        if not relationship.type.endswith("/notesSlide"):
            continue
        try:
            part = package.resolve(slide_part, relationship)
            root = ElementTree.fromstring(package.read(part))
        except (KeyError, ValueError, ElementTree.ParseError):
            return None
        for shape in root.iterfind(".//p:sp", _NS):
            holder = shape.find("p:nvSpPr/p:nvPr/p:ph", _NS)
            if holder is None or holder.get("type") != "body":
                continue
            lines = [
                "".join(run.text or "" for run in paragraph.iterfind(".//a:t", _NS))
                for paragraph in shape.iterfind("p:txBody/a:p", _NS)
            ]
            while lines and not lines[-1]:
                lines.pop()
            return "\n".join(lines) or None
    return None
