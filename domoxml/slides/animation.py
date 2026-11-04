"""Entrance and exit animations: ``p:timing`` to the IR and back.

PowerPoint builds a slide's animation as a tree of timing nodes. The part of it the IR carries is
the common one: entrance and exit effects (appear, fade, disappear, fade out) on shapes, grouped
into steps that start with the slide or on a click, each with a delay. Anything else in a slide's
timing (emphasis, motion paths, triggers, other presets) is not mapped, and the whole timing then
stays preserved source.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from domoxml.core.ir.model import Animation

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = {"p": _P}
_PRESETS = {
    ("entr", "1"): "appear",
    ("entr", "10"): "fade",
    ("exit", "1"): "disappear",
    ("exit", "10"): "fade-out",
    ("emph", "8"): "spin",
    ("emph", "6"): "grow",
}
_PRESET_IDS = {"appear": 1, "fade": 10, "disappear": 1, "fade-out": 10, "spin": 8, "grow": 6}
_FADES = ("fade", "fade-out")
_TIMED = ("fade", "fade-out", "spin", "grow")
_DEFAULT_AMOUNT = {"spin": 360.0, "grow": 150.0}


def read_animations(timing: Element, node_ids: dict[str, str]) -> tuple[Animation, ...] | None:
    """The slide's entrance and exit animations, or ``None`` if its timing holds anything else.

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
                if node is None or node.get("presetClass") not in ("entr", "exit", "emph"):
                    return None
                # A paragraph or character range animates part of a shape; the IR animates whole
                # shapes, so such timing stays preserved source.
                if any(len(tgt) for tgt in node.iterfind(".//p:spTgt", _NS)):
                    return None
                name = _PRESETS.get((node.get("presetClass", ""), node.get("presetID", "")))
                target = node_ids.get(_target(node) or "")
                if name is None or target is None:
                    return None
                duration = _duration(node) if name in _TIMED else 1
                amount = _amount(node, name)
                if amount is None:
                    return None
                found.append(
                    Animation(
                        target=target,
                        effect=name,  # type: ignore[arg-type]
                        amount=amount,
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


def _amount(node: Element, name: str) -> float | None:
    """The turn (degrees) or size (percent) of an emphasis effect; 0 for the others.

    ``None`` when the behaviour is not the plain rotate or uniform scale the IR carries.
    """
    if name == "spin":
        rotation = node.find(".//p:animRot", _NS)
        try:
            return int(rotation.get("by", "")) / 60_000 if rotation is not None else None
        except ValueError:
            return None
    if name == "grow":
        scale = node.find(".//p:animScale/p:by", _NS)
        try:
            if scale is None or scale.get("x") != scale.get("y"):
                return None
            return int(scale.get("x", "")) / 1000
        except ValueError:
            return None
    return 0.0


def _duration(node: Element) -> int:
    # The behaviour that takes the time: not the instant ``set`` that shows or hides the shape.
    timed = (".//p:animEffect", ".//p:animRot", ".//p:animScale")
    for behaviour in (cTn for path in timed for cTn in node.findall(f"{path}/p:cBhvr/p:cTn", _NS)):
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
            leaving = animation.effect in ("disappear", "fade-out")
            fades = animation.effect in _FADES
            target = f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
            if animation.effect in ("spin", "grow"):
                amount = animation.amount or _DEFAULT_AMOUNT[animation.effect]
                behaviour_cTn = (
                    f'<p:cTn id="{next_id()}" dur="{animation.duration_ms}" fill="hold"/>'
                )
                body = (
                    f'<p:animRot by="{round(amount * 60_000)}"><p:cBhvr>{behaviour_cTn}{target}'
                    "<p:attrNameLst><p:attrName>r</p:attrName></p:attrNameLst></p:cBhvr></p:animRot>"
                    if animation.effect == "spin"
                    else f"<p:animScale><p:cBhvr>{behaviour_cTn}{target}</p:cBhvr>"
                    f'<p:by x="{round(amount * 1000)}" y="{round(amount * 1000)}"/></p:animScale>'
                )
                effects += (
                    f'<p:par><p:cTn id="{next_id()}" presetID="{_PRESET_IDS[animation.effect]}" '
                    f'presetClass="emph" presetSubtype="0" fill="hold" nodeType="{kind}">'
                    f'<p:stCondLst><p:cond delay="{animation.delay_ms}"/></p:stCondLst>'
                    f"<p:childTnLst>{body}</p:childTnLst></p:cTn></p:par>"
                )
                continue
            fade = (
                f'<p:animEffect transition="{"out" if leaving else "in"}" filter="fade"><p:cBhvr>'
                f'<p:cTn id="{next_id()}" dur="{animation.duration_ms}"/>'
                f"{target}</p:cBhvr></p:animEffect>"
                if fades
                else ""
            )
            # An entrance shows the shape first and then fades it in; an exit fades it out and then
            # hides it, so the hide waits for the fade to finish.
            hide_after = max(0, animation.duration_ms - 1) if fades else 0
            visibility = (
                f'<p:set><p:cBhvr><p:cTn id="{next_id()}" dur="1" fill="hold"><p:stCondLst>'
                f'<p:cond delay="{hide_after if leaving else 0}"/></p:stCondLst></p:cTn>'
                f"{target}<p:attrNameLst>"
                "<p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
                f'<p:to><p:strVal val="{"hidden" if leaving else "visible"}"/></p:to></p:set>'
            )
            effects += (
                f'<p:par><p:cTn id="{next_id()}" presetID="{_PRESET_IDS[animation.effect]}" '
                f'presetClass="{"exit" if leaving else "entr"}" presetSubtype="0" fill="hold" '
                f'nodeType="{kind}"><p:stCondLst><p:cond delay="{animation.delay_ms}"/>'
                f"</p:stCondLst><p:childTnLst>"
                f"{fade + visibility if leaving else visibility + fade}"
                "</p:childTnLst></p:cTn></p:par>"
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
