from __future__ import annotations

from pathlib import Path

import pygame

from fall_of_penghu.shell.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / "assets" / "audio"
MENU_TRACK = AUDIO_DIR / "menu.ogg"
MATCH_TRACK = AUDIO_DIR / "match.ogg"


class Audio:
    """Menu and match music. Missing files stay silent."""

    def __init__(self) -> None:
        self.ok = False
        self._track = ""
        try:
            pygame.mixer.init()
            self.ok = True
        except pygame.error:
            self.ok = False

    def apply(self, cfg: Settings) -> None:
        if not self.ok:
            return
        vol = cfg.master * cfg.music
        pygame.mixer.music.set_volume(vol)

    def play_menu(self, cfg: Settings) -> None:
        self._play(MENU_TRACK, "menu", cfg)

    def play_match(self, cfg: Settings) -> None:
        self._play(MATCH_TRACK, "match", cfg)

    def stop(self) -> None:
        if not self.ok:
            return
        pygame.mixer.music.stop()
        self._track = ""

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
