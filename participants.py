from __future__ import annotations

from typing import Any


PARTICIPANTS: tuple[dict[str, str], ...] = (
    {"id": "xiaoli", "name": "小娌"},
    {"id": "xiaoyuan", "name": "小元"},
)

PARTICIPANT_BY_ID = {item["id"]: item for item in PARTICIPANTS}
PARTICIPANT_BY_NAME = {item["name"]: item for item in PARTICIPANTS}
PARTICIPANT_IDS = frozenset(PARTICIPANT_BY_ID)
PARTICIPANT_NAMES = frozenset(PARTICIPANT_BY_NAME)
JOINT_NAME = "共同"
OWNER_NAMES = frozenset((*PARTICIPANT_NAMES, JOINT_NAME))


def participant_ref(value: Any) -> dict[str, str] | None:
    """Resolve a stable participant id or canonical name to a JSON-safe reference."""
    text = str(value or "").strip()
    item = PARTICIPANT_BY_ID.get(text) or PARTICIPANT_BY_NAME.get(text)
    return dict(item) if item else None


def participant_name(participant_id: str) -> str:
    item = PARTICIPANT_BY_ID.get(str(participant_id or "").strip())
    return item["name"] if item else ""


def participant_id(name: str) -> str:
    item = PARTICIPANT_BY_NAME.get(str(name or "").strip())
    return item["id"] if item else ""
