"""Admission rules for native group projections."""

from __future__ import annotations

from domoxml.core.ir.model import Connector, GroupNode, ShapeNode


def group_pptx_write_error(group: GroupNode) -> str | None:
    """Return why the current PPTX writer cannot emit ``group`` without visible loss."""
    if not group.children:
        return "empty group has no stable normalized visual owner"
    if group.box.width <= 0 or group.box.height <= 0:
        return "group extent must be positive"
    if group.child_box.width <= 0 or group.child_box.height <= 0:
        return "group child coordinate extent must be positive"
    for child in group.children:
        if isinstance(child, ShapeNode):
            continue
        elif isinstance(child, GroupNode):
            if reason := group_pptx_write_error(child):
                return f"nested {reason}"
        else:
            # Connectors are the only remaining modeled group child and the PPTX
            # writer can emit them natively.
            continue
    return None


def group_html_roundtrip_error(group: GroupNode) -> str | None:
    """Return why normalized HTML cannot retain this group as editable structure yet."""
    if reason := group_pptx_write_error(group):
        return reason
    if group.transform is not None:
        return "transformed group has no exact normalized-HTML group projection"
    for child in group.children:
        if isinstance(child, Connector):
            return "connector group child has no exact normalized-HTML group projection"
        if isinstance(child, GroupNode):
            return "nested group reconstruction has no executable visual proof"
    return None
