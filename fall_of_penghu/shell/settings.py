from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

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
        if self.last_slot == "":
            self.last_slot = None


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
    )
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
