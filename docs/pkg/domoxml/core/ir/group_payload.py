"""Versioned normalized-HTML transport for native group coordinate spaces."""

from __future__ import annotations

import base64
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from domoxml.core.ir.model import Box, Connector, GroupNode, Point, ShapeNode, Transform
from domoxml.core.units import px_to_emu


class GroupMemberPayload(BaseModel):
    """Original child geometry keyed by the normalized child identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    box: Box | None = None
    start: Point | None = None
    end: Point | None = None
    projected_box: Box | None = None

    @model_validator(mode="after")
    def validate_identity_and_geometry(self) -> Self:
        if not self.node_id or self.node_id != self.node_id.strip():
            raise ValueError("group member node_id must be nonempty and trimmed")
        has_points = self.start is not None and self.end is not None
        if (self.start is None) != (self.end is None):
            raise ValueError("group member connector geometry requires both start and end")
        if (self.box is not None) == has_points:
            raise ValueError("group member requires exactly one geometry form")
        return self


class GroupPayload(BaseModel):
    """The geometry needed to invert flattened browser coordinates back into a group."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    box: Box
    child_box: Box
    transform: Transform | None = None
    members: tuple[GroupMemberPayload, ...] = ()

    @model_validator(mode="after")
    def validate_unique_members(self) -> Self:
        identities = [member.node_id for member in self.members]
        if len(identities) != len(set(identities)):
            raise ValueError("group member identities must be unique")
        return self


def encode_group_payload(
    *,
    box: Box,
    child_box: Box,
    transform: Transform | None = None,
    children: tuple[ShapeNode | GroupNode | Connector, ...] = (),
    projected_children: tuple[ShapeNode | GroupNode | Connector, ...] = (),
) -> str:
    projected_by_id = {
        child.node_id: child for child in projected_children if child.node_id is not None
    }

    def projection_box(child: ShapeNode | GroupNode | Connector | None) -> Box | None:
        if child is None:
            return None
        if not isinstance(child, Connector):
            return child.box
        pad = max(child.line.width_emu * 2, px_to_emu(4.0))
        left = min(child.start.x, child.end.x) - pad
        top = min(child.start.y, child.end.y) - pad
        return Box(
            x=left,
            y=top,
            width=max(child.start.x, child.end.x) - left + pad,
            height=max(child.start.y, child.end.y) - top + pad,
        )

    members: list[GroupMemberPayload] = []
    for child in children:
        if child.node_id is None:
            continue
        projected_box = projection_box(projected_by_id.get(child.node_id))
        if isinstance(child, Connector):
            members.append(
                GroupMemberPayload(
                    node_id=child.node_id,
                    start=child.start,
                    end=child.end,
                    projected_box=projected_box,
                )
            )
        else:
            members.append(
                GroupMemberPayload(
                    node_id=child.node_id,
                    box=child.box,
                    projected_box=projected_box,
                )
            )
    payload = GroupPayload(
        box=box,
        child_box=child_box,
        transform=transform,
        members=tuple(members),
    )
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode("ascii")


def decode_group_payload(value: str | None) -> GroupPayload | None:
    if not value:
        return None
    try:
        raw = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        return GroupPayload.model_validate_json(raw)
    except (ValueError, TypeError):
        return None
