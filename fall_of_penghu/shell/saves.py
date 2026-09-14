from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fall_of_penghu.world.clock import CALENDAR_DAY_S, CALENDAR_PER_SIM

ROOT = Path(__file__).resolve().parents[2]
SLOTS_DIR = ROOT / "saves" / "slots"


@dataclass
class SlotMeta:
    id: str
    label: str
    path: Path
    saved_at: str = ""


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
        label = str(data.get("label") or sid)
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
    sid = slot_id or "autosave"
    folder = SLOTS_DIR / sid
    folder.mkdir(parents=True, exist_ok=True)
    clock = str(payload.get("clock_label") or "")
    n = len(payload.get("objects") or [])
    label = clock if clock else sid
    if n:
        label = f"{label}  ·  {n} objects"
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
    minutes = int(max(0.0, float(elapsed_s)) // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 60:
        return f"{minutes} {_en(minutes, 'minute')} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {_en(hours, 'hour')} ago"
    days = hours // 24
    rest = hours % 24
    day_s = f"{days} {_en(days, 'day')}"
    if rest == 0:
        return f"{day_s} ago"
    return f"{day_s}, {rest} {_en(rest, 'hour')} ago"


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


def _en(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


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
