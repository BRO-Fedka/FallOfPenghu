from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fall_of_penghu.world.notices import (
    CATEGORIES,
    DEFAULT_SHOW,
    DEFAULT_SLOW,
    KIND_FILTERS,
    SPEED_0X,
    SPEED_1X,
    SPEED_OFF,
    default_kinds,
)

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "saves" / "settings.json"
RENDERERS = ("gl", "software")
RENDERER_LABELS = {"gl": "GPU", "software": "CPU"}
AA_MODES = ("off", "fxaa", "msaa2", "msaa4", "msaa8")
AA_LABELS = {
    "off": "OFF",
    "fxaa": "FXAA",
    "msaa2": "2x",
    "msaa4": "4x",
    "msaa8": "8x",
}
AA_SAMPLES = {"off": 0, "fxaa": 0, "msaa2": 2, "msaa4": 4, "msaa8": 8}


def _default_kinds() -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for name in KIND_FILTERS:
        row = default_kinds(name)
        if row is not None:
            out[name] = row
    return out


@dataclass
class Settings:
    fullscreen: bool = False
    master: float = 1.0
    music: float = 0.7
    sfx: float = 0.8
    renderer: str = "gl"
    simple_shaders: bool = False
    antialias: str = "msaa4"
    clock_12h: bool = False
    last_slot: str | None = None
    chat_docked: bool = True
    chat_x: int | None = None
    chat_y: int | None = None
    chat_show: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_SHOW))
    chat_slow: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SLOW))
    chat_kinds: dict[str, dict[str, bool]] = field(default_factory=_default_kinds)

    def clamp(self) -> None:
        self.master = _vol(self.master)
        self.music = _vol(self.music)
        self.sfx = _vol(self.sfx)
        if self.renderer in ("auto", "gpu", "opengl"):
            self.renderer = "gl"
        if self.renderer in ("cpu", "2d"):
            self.renderer = "software"
        if self.renderer not in RENDERERS:
            self.renderer = "gl"
        if self.antialias not in AA_MODES:
            self.antialias = "msaa4"
        self.simple_shaders = bool(self.simple_shaders)
        self.clock_12h = bool(self.clock_12h)
        self.chat_docked = bool(self.chat_docked)
        self.chat_show = _merge_flags(self.chat_show, DEFAULT_SHOW)
        self.chat_slow = _merge_speed(self.chat_slow, DEFAULT_SLOW)
        self.chat_kinds = _merge_kinds(self.chat_kinds)
        if self.last_slot == "":
            self.last_slot = None


def notice_kind_on(cfg: Settings, notice) -> bool:
    kinds = cfg.chat_kinds.get(notice.category)
    if not kinds:
        return True
    if notice.filter_kind:
        return bool(kinds.get(notice.filter_kind, True))
    if notice.icon_kinds:
        return any(kinds.get(kind, True) for kind in notice.icon_kinds)
    return True


def notice_visible(cfg: Settings, notice) -> bool:
    return notice_kind_on(cfg, notice) and bool(
        cfg.chat_show.get(notice.category, True)
    )


def notice_speed(cfg: Settings, notice) -> float | None:
    if not notice_kind_on(cfg, notice):
        return None
    mode = _speed_mode(cfg.chat_slow.get(notice.category))
    if mode == SPEED_1X:
        return 1.0
    if mode == SPEED_0X:
        return 0.0
    return None


def notice_slows(cfg: Settings, notice) -> bool:
    return notice_speed(cfg, notice) is not None


def load() -> Settings:
    if not SETTINGS_PATH.is_file():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    cfg = Settings(
        fullscreen=bool(data.get("fullscreen", False)),
        master=float(data.get("master", 1.0)),
        music=float(data.get("music", 0.7)),
        sfx=float(data.get("sfx", 0.8)),
        renderer=str(data.get("renderer") or "gl"),
        simple_shaders=bool(data.get("simple_shaders", False)),
        antialias=str(data.get("antialias") or "msaa4"),
        clock_12h=bool(data.get("clock_12h", False)),
        last_slot=data.get("last_slot"),
        chat_docked=bool(data.get("chat_docked", True)),
        chat_x=data.get("chat_x"),
        chat_y=data.get("chat_y"),
        chat_show=_merge_flags(data.get("chat_show"), DEFAULT_SHOW),
        chat_slow=_merge_speed(data.get("chat_slow"), DEFAULT_SLOW),
        chat_kinds=_merge_kinds(data.get("chat_kinds")),
    )
    if cfg.chat_x is not None:
        cfg.chat_x = int(cfg.chat_x)
    if cfg.chat_y is not None:
        cfg.chat_y = int(cfg.chat_y)
    if cfg.last_slot is not None:
        cfg.last_slot = str(cfg.last_slot)
    cfg.clamp()
    return cfg


def save(cfg: Settings) -> None:
    cfg.clamp()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8"
    )


def _vol(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _merge_flags(raw, defaults: dict[str, bool]) -> dict[str, bool]:
    out = dict(defaults)
    if isinstance(raw, dict):
        for key in CATEGORIES:
            if key in raw:
                out[key] = bool(raw[key])
    return out


def _speed_mode(value) -> str:
    if value is True or value in (1, "1", "1x"):
        return SPEED_1X
    if value is False or value in (None, "off", "false"):
        return SPEED_OFF
    if value in (0, "0", "0x"):
        return SPEED_0X
    text = str(value).strip().lower()
    if text in (SPEED_OFF, SPEED_1X, SPEED_0X):
        return text
    return SPEED_OFF


def _merge_speed(raw, defaults: dict[str, str]) -> dict[str, str]:
    out = dict(defaults)
    if isinstance(raw, dict):
        for key in CATEGORIES:
            if key in raw:
                out[key] = _speed_mode(raw[key])
    return out


def _merge_kinds(raw) -> dict[str, dict[str, bool]]:
    out = _default_kinds()
    if not isinstance(raw, dict):
        return out
    for category, row in raw.items():
        if category not in out or not isinstance(row, dict):
            continue
        base = out[category]
        allowed = KIND_FILTERS[category]
        for kind, on in row.items():
            if kind in allowed:
                base[kind] = bool(on)
    return out
