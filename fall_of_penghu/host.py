from __future__ import annotations

import sys


def running_in_browser() -> bool:
    return sys.platform in ("emscripten", "wasi")
