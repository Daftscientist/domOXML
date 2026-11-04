"""Entrance animations: ``p:timing`` to the IR and back.

PowerPoint builds a slide's animation as a tree of timing nodes. The part of it the IR carries is
the common one: entrance effects (appear, fade) on shapes, grouped into steps that start with the
slide or on a click, each with a delay. Anything else in a slide's timing (emphasis, exit, motion
paths, triggers, other presets) is not mapped, and the whole timing then stays preserved source.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from domoxml.core.ir.model import Animation

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"p": _P}
_PRESETS = {"1": "appear", "10": "fade"}
_PRESET_IDS = {"appear": 1, "fade": 10}


def read_animations(timing: Element, node_ids: dict[str, str]) -> tuple[Animation, ...] | None:
    """The slide's entrance animations, or ``None`` if its timing holds anything else.

    ``node_ids`` maps a source shape id (``spid``) to the node id of the slide node it became: an
    effect on anything outside it (a placeholder, a group) is not one this can carry.
    """
    tn_list = timing.find("p:tnLst", _NS)
    roots = timing.findall("p:tnLst/p:par", _NS)
    if tn_list is None or len(roots) != 1 or len(tn_list) != 1:
        return None
    branches = roots[0].findall("p:cTn/p:childTnLst/*", _NS)
    main = branches[0] if len(branches) == 1 else None
    # One main sequence and nothing beside it: an interactive (trigger) sequence would be lost.
    if main is None or main.tag != f"{{{_P}}}seq":
        return None
    sequence = main.find("p:cTn/p:childTnLst", _NS)
    if sequence is None or any(child.tag != f"{{{_P}}}par" for child in sequence):
        return None
    found: list[Animation] = []
    step = 0
    for outer in sequence.findall("p:par", _NS):
        starts = outer.find("p:cTn/p:stCondLst", _NS)
        if starts is not None and any(c.get("delay") == "indefinite" for c in starts):
            step += 1
        for group in outer.findall("p:cTn/p:childTnLst/p:par", _NS):
            offset = _delay(group.find("p:cTn/p:stCondLst", _NS))
            for effect in group.findall("p:cTn/p:childTnLst/p:par", _NS):
                node = effect.find("p:cTn", _NS)
                if node is None or node.get("presetClass") != "entr":
                    return None
                # A paragraph or character range animates part of a shape; the IR animates whole
                # shapes, so such timing stays preserved source.
                if any(len(tgt) for tgt in node.iterfind(".//p:spTgt", _NS)):
                    return None
                name = _PRESETS.get(node.get("presetID", ""))
                target = node_ids.get(_target(node) or "")
                if name is None or target is None:
                    return None
                duration = _duration(node) if name == "fade" else 1
                found.append(
                    Animation(
                        target=target,
                        effect="appear" if name == "appear" else "fade",
                        step=step,
                        delay_ms=offset + _delay(node.find("p:stCondLst", _NS)),
                        duration_ms=duration,
                    )
                )
    return tuple(found) if found else None


def _delay(conditions: Element | None) -> int:
    if conditions is None:
        return 0
    for condition in conditions:
        try:
            return max(0, int(condition.get("delay", "0")))
        except ValueError:
            continue
    return 0


def _target(node: Element) -> str | None:
    target = node.find(".//p:spTgt", _NS)
    return target.get("spid") if target is not None else None


def _duration(node: Element) -> int:
    for behaviour in node.findall(".//p:animEffect/p:cBhvr/p:cTn", _NS):
        try:
            return max(1, int(behaviour.get("dur", "500")))
        except ValueError:
            break
    return 500


def timing_xml(animations: tuple[Animation, ...], shape_ids: dict[str, int]) -> str:
    """The ``p:timing`` element for ``animations``; ``shape_ids`` maps node ids to ``spid``."""
    counter = 2

    def next_id() -> int:
        nonlocal counter
        counter += 1
        return counter

    steps: dict[int, list[Animation]] = {}
    for animation in animations:
        if animation.target in shape_ids:
            steps.setdefault(animation.step, []).append(animation)
    if not steps:
        return ""
    outer_xml = ""
    for step in sorted(steps):
        effects = ""
        for position, animation in enumerate(steps[step]):
            spid = shape_ids[animation.target]
            kind = "clickEffect" if step > 0 and position == 0 else "withEffect"
            fade = (
                '<p:animEffect transition="in" filter="fade"><p:cBhvr>'
                f'<p:cTn id="{next_id()}" dur="{animation.duration_ms}"/>'
                f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
                if animation.effect == "fade"
                else ""
            )
            effects += (
                f'<p:par><p:cTn id="{next_id()}" presetID="{_PRESET_IDS[animation.effect]}" '
                f'presetClass="entr" presetSubtype="0" fill="hold" nodeType="{kind}">'
                f'<p:stCondLst><p:cond delay="{animation.delay_ms}"/></p:stCondLst><p:childTnLst>'
                f'<p:set><p:cBhvr><p:cTn id="{next_id()}" dur="1" fill="hold"><p:stCondLst>'
                '<p:cond delay="0"/></p:stCondLst></p:cTn>'
                f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst>'
                "<p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
                '<p:to><p:strVal val="visible"/></p:to></p:set>'
                f"{fade}</p:childTnLst></p:cTn></p:par>"
            )
        start = "indefinite" if step > 0 else "0"
        outer_xml += (
            f'<p:par><p:cTn id="{next_id()}" fill="hold"><p:stCondLst><p:cond delay="{start}"/>'
            "</p:stCondLst><p:childTnLst>"
            f'<p:par><p:cTn id="{next_id()}" fill="hold"><p:stCondLst><p:cond delay="0"/>'
            f"</p:stCondLst><p:childTnLst>{effects}</p:childTnLst></p:cTn></p:par>"
            "</p:childTnLst></p:cTn></p:par>"
        )
    return (
        f'<p:timing xmlns:p="{_P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" '
        'nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek">'
        '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        f"{outer_xml}</p:childTnLst></p:cTn>"
        '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond>'
        '</p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/>'
        "</p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst>"
        "</p:timing>"
    )
