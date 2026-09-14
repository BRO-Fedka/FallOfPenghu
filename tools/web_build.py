"""Stage a pygbag folder and build the web client.

Does not pack .git, tools, tests, or GL-only map rasters. Includes sim_bake.pkl
even though that file is gitignored.

  python tools/web_build.py
  python tools/web_build.py --stage
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "build" / "web_src"
WEB_OUT = ROOT / "build" / "web"

MAP_SKIP = frozenset(
    {
        "dem_src.tif",
        "dem.npz",
        "gl_fields_v1.npz",
    }
)


def _copy_tree(src: Path, dst: Path, *, skip_names: set[str] | None = None) -> None:
    skip = skip_names or set()

    def ignore(directory: str, names: list[str]) -> set[str]:
        drop = {name for name in names if name in skip or name == "__pycache__"}
        drop.update(name for name in names if name.endswith((".pyc", ".pyo")))
        return drop

    shutil.copytree(src, dst, ignore=ignore)


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copy2(ROOT / "main.py", STAGE / "main.py")
    _copy_tree(ROOT / "fall_of_penghu", STAGE / "fall_of_penghu")
    map_src = ROOT / "penghu_map_v1"
    map_dst = STAGE / "penghu_map_v1"
    map_dst.mkdir()
    for path in map_src.iterdir():
        if path.name in MAP_SKIP or path.name.startswith("."):
            continue
        if path.is_file():
            shutil.copy2(path, map_dst / path.name)


def build() -> None:
    cmd = [
        sys.executable,
        "-m",
        "pygbag",
        "--build",
        "--no_opt",
        "--ume_block",
        "0",
        "--can_close",
        "1",
        "--title",
        "Fall of Penghu",
        "--app_name",
        "fall_of_penghu",
        "--package",
        "org.fallofpenghu.game",
        "--directory",
        str(WEB_OUT),
        str(STAGE),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage and build the pygbag web client")
    parser.add_argument("--stage", action="store_true", help="copy files only, do not run pygbag")
    args = parser.parse_args()
    print(f"Staging {STAGE}", flush=True)
    stage()
    bake = STAGE / "penghu_map_v1" / "sim_bake.pkl"
    print(f"sim_bake.pkl {'present' if bake.is_file() else 'MISSING'}", flush=True)
    if args.stage:
        return
    try:
        import pygbag  # noqa: F401
    except ImportError:
        print("Installing pygbag…", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pygbag"])
    build()
    index = WEB_OUT / "index.html"
    print(f"Web build: {index if index.is_file() else WEB_OUT}", flush=True)


if __name__ == "__main__":
    main()
