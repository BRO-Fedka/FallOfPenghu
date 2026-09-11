from __future__ import annotations

from pathlib import Path


class DecisionLog:
    """China AI decisions. Console and logs/china_ai.log."""

    def __init__(self, path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.path = path if path is not None else root / "logs" / "china_ai.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.emit(0.0, "boot", f"log {self.path}")

    def emit(self, now: float, tag: str, msg: str) -> None:
        line = f"{now:10.1f}  {tag:<14} {msg}"
        print(line, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()
