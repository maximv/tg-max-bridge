import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from config import CONNECTORS_FILE


@dataclass(frozen=True)
class Connector:
    name: str
    tg_group_id: int | None
    tg_topic_id: int | None
    max_group_id: int | None
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


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _to_optional_int(raw_value: object, field_name: str) -> int | None:
    if raw_value is None:
        return None
    return _to_int(raw_value, field_name)


def _connector_from_item(item: dict, idx: int) -> Connector:
    tg_topic_raw = item.get("tg_topic_id", 0)
    tg_topic_num = _to_int(tg_topic_raw, "tg_topic_id")
    tg_topic_id = None if tg_topic_num == 0 else tg_topic_num

    return Connector(
        name=str(item.get("name", f"connector-{idx}")),
        tg_group_id=_to_optional_int(item.get("tg_group_id"), "tg_group_id"),
        tg_topic_id=tg_topic_id,
        max_group_id=_to_optional_int(item.get("max_group_id"), "max_group_id"),
        comment=str(item.get("comment", "")),
        enabled=bool(item.get("enabled", True)),
    )


def load_connectors() -> list[Connector]:
    config_path = Path(CONNECTORS_FILE)
    if not config_path.exists():
        return []

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    items = raw.get("connectors")
    if not isinstance(items, list):
        raise RuntimeError("connectors.json must contain array field 'connectors'")

    connectors: list[Connector] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Connector #{idx} must be object")
        connector = _connector_from_item(item, idx)
        if connector.enabled:
            connectors.append(connector)

    return connectors


CONNECTORS = load_connectors()

TG_GROUP_IDS = {c.tg_group_id for c in CONNECTORS if c.tg_group_id is not None}

CONNECTOR_BY_TG: dict[tuple[int, int], Connector] = {}
CONNECTOR_BY_MAX: dict[int, Connector] = {}

for connector in CONNECTORS:
    if connector.tg_group_id is not None:
        tg_key = (connector.tg_group_id, connector.tg_topic_id or 0)
        if tg_key in CONNECTOR_BY_TG:
            raise RuntimeError(f"Duplicate tg_group_id+tg_topic_id mapping: {tg_key}")
        CONNECTOR_BY_TG[tg_key] = connector

    if connector.max_group_id is not None:
        if connector.max_group_id in CONNECTOR_BY_MAX:
            raise RuntimeError(f"Duplicate max_group_id mapping: {connector.max_group_id}")
        CONNECTOR_BY_MAX[connector.max_group_id] = connector

_FILE_LOCK = Lock()


@dataclass(frozen=True)
class PairingResult:
    connector: Connector
    completed: bool
    message: str


def _load_raw_config() -> dict:
    config_path = Path(CONNECTORS_FILE)
    if not config_path.exists():
        return {"connectors": []}
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if "connectors" not in raw or not isinstance(raw["connectors"], list):
        raw["connectors"] = []
    return raw


def _write_raw_config(raw: dict) -> None:
    config_path = Path(CONNECTORS_FILE)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_connector_indexes(connectors: list[Connector]) -> tuple[dict[tuple[int, int], Connector], dict[int, Connector]]:
    by_tg: dict[tuple[int, int], Connector] = {}
    by_max: dict[int, Connector] = {}
    for c in connectors:
        if not c.enabled:
            continue
        if c.tg_group_id is not None:
            tg_key = (c.tg_group_id, c.tg_topic_id or 0)
            if tg_key in by_tg:
                raise RuntimeError(f"Duplicate tg_group_id+tg_topic_id mapping: {tg_key}")
            by_tg[tg_key] = c
        if c.max_group_id is not None:
            if c.max_group_id in by_max:
                raise RuntimeError(f"Duplicate max_group_id mapping: {c.max_group_id}")
            by_max[c.max_group_id] = c
    return by_tg, by_max


def _reload_state() -> None:
    global CONNECTORS, TG_GROUP_IDS, CONNECTOR_BY_TG, CONNECTOR_BY_MAX
    connectors = load_connectors()
    by_tg, by_max = _build_connector_indexes(connectors)
    CONNECTORS = connectors
    TG_GROUP_IDS = {c.tg_group_id for c in connectors if c.tg_group_id is not None}
    CONNECTOR_BY_TG = by_tg
    CONNECTOR_BY_MAX = by_max


def get_tg_group_ids() -> set[int]:
    return set(TG_GROUP_IDS)


def get_connector_for_tg(chat_id: int, thread_id: int | None) -> Connector | None:
    return CONNECTOR_BY_TG.get((chat_id, thread_id or 0))


def get_connector_for_max(max_group_id: int) -> Connector | None:
    return CONNECTOR_BY_MAX.get(max_group_id)


def disconnect_from_tg(secret: str, tg_group_id: int, tg_topic_id: int | None) -> PairingResult:
    secret_norm = _normalize_name(secret)
    if not secret_norm:
        raise ValueError("Secret cannot be empty")

    with _FILE_LOCK:
        raw = _load_raw_config()
        items = raw["connectors"]
        found_idx = None
        for i, item in enumerate(items):
            if _normalize_name(str(item.get("name", ""))) == secret_norm:
                found_idx = i
                break
        if found_idx is None:
            raise RuntimeError("Связь с таким секретом не найдена")

        item = items[found_idx]
        existing_tg = item.get("tg_group_id")
        existing_topic = int(item.get("tg_topic_id", 0) or 0)
        if existing_tg is None:
            raise RuntimeError("TG-сторона уже не привязана")
        if int(existing_tg) != tg_group_id or existing_topic != int(tg_topic_id or 0):
            raise RuntimeError("Секрет привязан к другой TG-группе/топику")

        item["tg_group_id"] = None
        item["tg_topic_id"] = 0
        if item.get("max_group_id") is None:
            items.pop(found_idx)

        _write_raw_config(raw)
        _reload_state()

    connector = get_connector_for_max(int(item.get("max_group_id"))) if item.get("max_group_id") is not None else Connector(
        name=str(item.get("name", secret.strip())),
        tg_group_id=None,
        tg_topic_id=None,
        max_group_id=None,
        comment=str(item.get("comment", "")),
        enabled=bool(item.get("enabled", True)),
    )
    return PairingResult(connector=connector, completed=False, message="Связь со стороны TG отключена.")


def disconnect_from_max(secret: str, max_group_id: int) -> PairingResult:
    secret_norm = _normalize_name(secret)
    if not secret_norm:
        raise ValueError("Secret cannot be empty")

    with _FILE_LOCK:
        raw = _load_raw_config()
        items = raw["connectors"]
        found_idx = None
        for i, item in enumerate(items):
            if _normalize_name(str(item.get("name", ""))) == secret_norm:
                found_idx = i
                break
        if found_idx is None:
            raise RuntimeError("Связь с таким секретом не найдена")

        item = items[found_idx]
        existing_max = item.get("max_group_id")
        if existing_max is None:
            raise RuntimeError("MAX-сторона уже не привязана")
        if int(existing_max) != max_group_id:
            raise RuntimeError("Секрет привязан к другой MAX-группе")

        item["max_group_id"] = None
        if item.get("tg_group_id") is None:
            items.pop(found_idx)

        _write_raw_config(raw)
        _reload_state()

    connector = get_connector_for_tg(int(item.get("tg_group_id")), int(item.get("tg_topic_id", 0) or 0)) if item.get("tg_group_id") is not None else Connector(
        name=str(item.get("name", secret.strip())),
        tg_group_id=None,
        tg_topic_id=None,
        max_group_id=None,
        comment=str(item.get("comment", "")),
        enabled=bool(item.get("enabled", True)),
    )
    return PairingResult(connector=connector, completed=False, message="Связь со стороны MAX отключена.")


def pair_from_tg(secret: str, tg_group_id: int, tg_topic_id: int | None) -> PairingResult:
    secret_norm = _normalize_name(secret)
    if not secret_norm:
        raise ValueError("Secret cannot be empty")

    with _FILE_LOCK:
        raw = _load_raw_config()
        items = raw["connectors"]

        found_idx = None
        for i, item in enumerate(items):
            if _normalize_name(str(item.get("name", ""))) == secret_norm:
                found_idx = i
                break

        if found_idx is None:
            items.append(
                {
                    "name": secret.strip(),
                    "enabled": True,
                    "tg_group_id": tg_group_id,
                    "tg_topic_id": tg_topic_id or 0,
                    "max_group_id": None,
                    "comment": "Auto-created via /connect",
                }
            )
            _write_raw_config(raw)
            _reload_state()
            connector = get_connector_for_tg(tg_group_id, tg_topic_id)
            if not connector:
                raise RuntimeError("Failed to load connector after create")
            return PairingResult(
                connector=connector,
                completed=False,
                message="Связь частично создана. Теперь выполните /connect с тем же секретом в MAX-группе.",
            )

        item = items[found_idx]
        existing_tg = item.get("tg_group_id")
        if existing_tg is None:
            item["tg_group_id"] = tg_group_id
            item["tg_topic_id"] = tg_topic_id or 0
        elif int(existing_tg) != tg_group_id or int(item.get("tg_topic_id", 0) or 0) != int(tg_topic_id or 0):
            raise RuntimeError("Этот секрет уже привязан к другой TG-группе/топику")

        _write_raw_config(raw)
        _reload_state()

    connector = get_connector_for_tg(tg_group_id, tg_topic_id)
    if not connector:
        raise RuntimeError("Failed to load connector after update")
    completed = connector.max_group_id is not None
    return PairingResult(
        connector=connector,
        completed=completed,
        message=(
            "Связь установлена."
            if completed
            else "TG-сторона привязана. Теперь выполните /connect с тем же секретом в MAX-группе."
        ),
    )


def pair_from_max(secret: str, max_group_id: int) -> PairingResult:
    secret_norm = _normalize_name(secret)
    if not secret_norm:
        raise ValueError("Secret cannot be empty")

    with _FILE_LOCK:
        raw = _load_raw_config()
        items = raw["connectors"]

        found_idx = None
        for i, item in enumerate(items):
            if _normalize_name(str(item.get("name", ""))) == secret_norm:
                found_idx = i
                break

        if found_idx is None:
            items.append(
                {
                    "name": secret.strip(),
                    "enabled": True,
                    "tg_group_id": None,
                    "tg_topic_id": 0,
                    "max_group_id": max_group_id,
                    "comment": "Auto-created via /connect",
                }
            )
            _write_raw_config(raw)
            _reload_state()
            connector = get_connector_for_max(max_group_id)
            if not connector:
                raise RuntimeError("Failed to load connector after create")
            return PairingResult(
                connector=connector,
                completed=False,
                message="Связь частично создана. Теперь выполните /connect с тем же секретом в TG-группе.",
            )

        item = items[found_idx]
        existing_max = item.get("max_group_id")
        if existing_max is None:
            item["max_group_id"] = max_group_id
        elif int(existing_max) != max_group_id:
            raise RuntimeError("Этот секрет уже привязан к другой MAX-группе")

        _write_raw_config(raw)
        _reload_state()

    connector = get_connector_for_max(max_group_id)
    if not connector:
        raise RuntimeError("Failed to load connector after update")
    completed = connector.tg_group_id is not None
    return PairingResult(
        connector=connector,
        completed=completed,
        message=(
            "Связь установлена."
            if completed
            else "MAX-сторона привязана. Теперь выполните /connect с тем же секретом в TG-группе."
        ),
    )
