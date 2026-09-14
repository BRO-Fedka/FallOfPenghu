from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fall_of_penghu.paths import user_root
from fall_of_penghu.world.clock import CALENDAR_DAY_S, CALENDAR_PER_SIM

ROOT = user_root()
SLOTS_DIR = ROOT / "saves" / "slots"


@dataclass
class SlotMeta:
    id: str
    label: str
    path: Path
    saved_at: str = ""


def alloc_slot_id() -> str:
    """New campaign folder. Does not reuse another match's slot."""
    SLOTS_DIR.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    sid = base
    n = 1
    while (SLOTS_DIR / sid).exists():
        n += 1
        sid = f"{base}-{n}"
    return sid


def list_slots() -> list[SlotMeta]:
    if not SLOTS_DIR.is_dir():
        return []
    out: list[SlotMeta] = []
    for path in SLOTS_DIR.glob("*/meta.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        sid = str(data.get("id") or path.parent.name)
        clock = str(data.get("clock_label") or "")
        raw = str(data.get("label") or "")
        if "  ·  " in raw:
            raw = raw.split("  ·  ", 1)[0].strip()
        label = clock or raw or sid
        saved_at = str(data.get("saved_at") or "")
        out.append(SlotMeta(id=sid, label=label, path=path, saved_at=saved_at))
    out.sort(key=lambda slot: (slot.saved_at, slot.id), reverse=True)
    return out


def latest_slot() -> SlotMeta | None:
    slots = list_slots()
    return slots[0] if slots else None


def find_slot(slot_id: str) -> SlotMeta | None:
    for slot in list_slots():
        if slot.id == slot_id:
            return slot
    return None


def write_slot(payload: dict[str, Any], *, slot_id: str | None = None) -> SlotMeta:
    sid = slot_id or alloc_slot_id()
    folder = SLOTS_DIR / sid
    folder.mkdir(parents=True, exist_ok=True)
    clock = str(payload.get("clock_label") or "")
    label = clock if clock else sid
    saved_at = datetime.now().isoformat(timespec="seconds")
    match_path = folder / "match.json"
    tmp = folder / "match.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(match_path)
    meta = {
        "id": sid,
        "label": label,
        "saved_at": saved_at,
        "clock_label": clock,
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return SlotMeta(id=sid, label=label, path=folder / "meta.json", saved_at=saved_at)


def ago_phrase(elapsed_s: float) -> str:
    """How long the match clock has run since the declaration of war."""
    from fall_of_penghu.shell.i18n import counted, t

    minutes = int(max(0.0, float(elapsed_s)) // 60)
    if minutes < 1:
        return t("ago.lt_minute")
    if minutes < 60:
        return t("ago.past", span=counted(minutes, "minute"))
    hours = minutes // 60
    if hours < 24:
        return t("ago.past", span=counted(hours, "hour"))
    days = hours // 24
    rest = hours % 24
    if rest == 0:
        return t("ago.past", span=counted(days, "day"))
    return t(
        "ago.days_hours",
        days=counted(days, "day"),
        hours=counted(rest, "hour"),
    )


def slot_ago(slot_id: str) -> str:
    data = read_slot(slot_id)
    if not data:
        return ago_phrase(0.0)
    clock = data.get("clock") or {}
    start = 0.5 * CALENDAR_DAY_S
    if "calendar_time" in clock:
        elapsed = float(clock["calendar_time"]) - start
    else:
        elapsed = float(clock.get("simulation_time") or 0.0) * CALENDAR_PER_SIM
    return ago_phrase(elapsed)


def read_slot(slot_id: str) -> dict[str, Any] | None:
    path = SLOTS_DIR / slot_id / "match.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data
