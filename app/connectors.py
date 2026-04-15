import json
from dataclasses import dataclass
from pathlib import Path

from config import CONNECTORS_FILE


@dataclass(frozen=True)
class Connector:
    name: str
    tg_group_id: int
    tg_topic_id: int | None
    max_group_id: int
    comment: str
    enabled: bool

    @property
    def key(self) -> str:
        topic_part = self.tg_topic_id if self.tg_topic_id is not None else 0
        return f"{self.tg_group_id}:{topic_part}:{self.max_group_id}"


def _to_int(raw_value: object, field_name: str) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Connector field '{field_name}' must be int, got {raw_value!r}") from exc


def load_connectors() -> list[Connector]:
    config_path = Path(CONNECTORS_FILE)
    if not config_path.exists():
        raise RuntimeError(
            f"connectors.json not found at '{config_path}'. "
            "Create file from connectors.json.example."
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    items = raw.get("connectors")
    if not isinstance(items, list) or not items:
        raise RuntimeError("connectors.json must contain non-empty array 'connectors'")

    connectors: list[Connector] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Connector #{idx} must be object")

        enabled = bool(item.get("enabled", True))
        connector = Connector(
            name=str(item.get("name", f"connector-{idx}")),
            tg_group_id=_to_int(item.get("tg_group_id"), "tg_group_id"),
            tg_topic_id=(
                None
                if int(item.get("tg_topic_id", 0)) == 0
                else _to_int(item.get("tg_topic_id"), "tg_topic_id")
            ),
            max_group_id=_to_int(item.get("max_group_id"), "max_group_id"),
            comment=str(item.get("comment", "")),
            enabled=enabled,
        )
        if connector.enabled:
            connectors.append(connector)

    if not connectors:
        raise RuntimeError("No enabled connectors in connectors.json")

    return connectors


CONNECTORS = load_connectors()

TG_GROUP_IDS = {c.tg_group_id for c in CONNECTORS}

CONNECTOR_BY_TG: dict[tuple[int, int], Connector] = {}
CONNECTOR_BY_MAX: dict[int, Connector] = {}

for connector in CONNECTORS:
    tg_key = (connector.tg_group_id, connector.tg_topic_id or 0)
    if tg_key in CONNECTOR_BY_TG:
        raise RuntimeError(f"Duplicate tg_group_id+tg_topic_id mapping: {tg_key}")
    CONNECTOR_BY_TG[tg_key] = connector

    if connector.max_group_id in CONNECTOR_BY_MAX:
        raise RuntimeError(f"Duplicate max_group_id mapping: {connector.max_group_id}")
    CONNECTOR_BY_MAX[connector.max_group_id] = connector


def get_connector_for_tg(chat_id: int, thread_id: int | None) -> Connector | None:
    return CONNECTOR_BY_TG.get((chat_id, thread_id or 0))


def get_connector_for_max(max_group_id: int) -> Connector | None:
    return CONNECTOR_BY_MAX.get(max_group_id)
