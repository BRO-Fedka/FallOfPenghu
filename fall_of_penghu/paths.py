"""Repo root vs writable user root. Frozen builds read from _MEIPASS."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Assets, map pack, and bundled data. Read-only when frozen."""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def package_dir() -> Path:
    """The fall_of_penghu package directory."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return resource_root() / "fall_of_penghu"
    return Path(__file__).resolve().parent


def user_root() -> Path:
    """Saves, logs, and writable caches. Next to the exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return resource_root()
