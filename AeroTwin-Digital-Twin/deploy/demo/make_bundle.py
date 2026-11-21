"""Pack the hosted demonstration copy into one file for the server.

    python deploy/demo/make_bundle.py

Writes deploy/demo/out/astra-demo-bundle.tar.gz (about 200 MB): the code, the
BUILT console, and only the data the running system reads -- the trained
models, the flame lookup, the terrain, and the fleet data set the fleet and
replay pages draw on. Not the benchmarks, the shards or the raw runs, which
are training material and 6 GB of it.

Rebuild the console first (npm run build in layer5_viz/gcs_console) if it has
changed; the bundle takes dist/ as it is and says how old it is.

On the server: unpack it and run ``bash astra-demo/setup_server.sh``. That
installs Python packages into a virtual environment and runs ASTRA under
systemd -- no containers.
"""

from __future__ import annotations

import io
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "astra-demo-bundle.tar.gz"

# Repository paths copied as they are.
TREES = [
    "pyproject.toml", "requirements.lock", "README.md",
    "common", "configs", "layer1_edge", "layer2_physics", "layer3_ai",
    "layer4_core", "fleet_server", "scripts", "docs", "assets",
    "layer5_viz/__init__.py",
    "layer5_viz/gcs_console/dist",
    "layer5_viz/gcs_console/public/geo",   # terrain.py reads it from here
    "data/models", "data/physics", "data/terrain_tiles",
    "data/synthetic/train.parquet", "data/synthetic/val.parquet",
    "data/synthetic/test.parquet", "data/synthetic/manifest.json",
]
# The server-side files, placed at the top of the bundle.
DEPLOY = ["astra-demo.service", "setup_server.sh"]

SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def _skip(p: Path) -> bool:
    return bool(SKIP_PARTS.intersection(p.parts)) or p.suffix == ".pyc"


def _add_text_lf(tar: tarfile.TarFile, src: Path, name: str, mode: int) -> None:
    """Shell and unit files with Unix line endings, whatever the checkout has."""
    data = src.read_bytes().replace(b"\r\n", b"\n")
    info = tarfile.TarInfo(f"astra-demo/{name}")
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    tar.addfile(info, io.BytesIO(data))


def main() -> int:
    missing = [t for t in TREES if not (ROOT / t).exists()]
    if missing:
        print("missing, cannot bundle:", *missing, sep="\n  ")
        return 1
    dist = ROOT / "layer5_viz/gcs_console/dist/index.html"
    age_h = (time.time() - dist.stat().st_mtime) / 3600
    print(f"console build is {age_h:.1f} h old")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT, "w:gz", compresslevel=6) as tar:
        for t in TREES:
            tar.add(ROOT / t, arcname=f"astra-demo/{t}",
                    filter=lambda ti: None if _skip(Path(ti.name)) else ti)
        for f in DEPLOY:
            _add_text_lf(tar, HERE / f, f, 0o755 if f.endswith(".sh") else 0o644)
    print(f"wrote {OUT}  ({OUT.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
