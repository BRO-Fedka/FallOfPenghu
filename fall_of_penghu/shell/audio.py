"""Menu/match music and UI/combat sound effects. Missing files stay silent."""

from __future__ import annotations

from pathlib import Path

import pygame

from fall_of_penghu.paths import resource_root
from fall_of_penghu.shell.settings import Settings

ROOT = resource_root()
AUDIO_DIR = ROOT / "assets" / "audio"
MENU_TRACK = AUDIO_DIR / "menu.ogg"
MATCH_TRACK = AUDIO_DIR / "match.ogg"
SFX_FILES = {
    "click": "click.wav",
    "explosion": "explosion.wav",
    "notification": "notification.wav",
    "failure": "failure.wav",
    "appearance": "appearance.wav",
}

_current: Audio | None = None


class Audio:
    """Music plus one-shot SFX. Volume is master × music or master × sfx."""

    FADE_MS = 3200

    def __init__(self) -> None:
        global _current
        self.ok = False
        self._track = ""
        self._sfx: dict[str, pygame.mixer.Sound] = {}
        self._sfx_vol = 0.8
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
            pygame.mixer.set_num_channels(24)
            self.ok = True
        except pygame.error:
            self.ok = False
            _current = self
            return
        self._load_sfx()
        _current = self

    def apply(self, cfg: Settings) -> None:
        if not self.ok:
            return
        pygame.mixer.music.set_volume(cfg.master * cfg.music)
        self._sfx_vol = cfg.master * cfg.sfx
        for sound in self._sfx.values():
            sound.set_volume(self._sfx_vol)

    def play_menu(self, cfg: Settings) -> None:
        self._play(MENU_TRACK, "menu", cfg)

    def play_match(self, cfg: Settings) -> None:
        self._play(MATCH_TRACK, "match", cfg)

    def fade_out(self, ms: int = FADE_MS) -> None:
        if not self.ok:
            return
        pygame.mixer.music.fadeout(max(0, int(ms)))
        self._track = ""

    def stop(self) -> None:
        if not self.ok:
            return
        pygame.mixer.music.stop()
        self._track = ""

    def play(self, name: str) -> None:
        if not self.ok or self._sfx_vol <= 0.0:
            return
        sound = self._sfx.get(name)
        if sound is None:
            return
        try:
            sound.play()
        except pygame.error:
            return

    def _load_sfx(self) -> None:
        for name, filename in SFX_FILES.items():
            path = AUDIO_DIR / filename
            if not path.is_file():
                continue
            try:
                self._sfx[name] = pygame.mixer.Sound(str(path))
            except pygame.error:
                continue

    def _play(self, path: Path, name: str, cfg: Settings) -> None:
        if not self.ok or self._track == name:
            self.apply(cfg)
            return
        if not path.is_file():
            self.stop()
            return
        try:
            pygame.mixer.music.load(str(path))
            self.apply(cfg)
            pygame.mixer.music.play(-1)
            self._track = name
        except pygame.error:
            self.stop()


def play(name: str) -> None:
    if _current is not None:
        _current.play(name)


def click(event: pygame.event.Event | None = None) -> None:
    if event is not None and (
        event.type != pygame.MOUSEBUTTONDOWN or getattr(event, "button", 0) != 1
    ):
        return
    play("click")
