"""Put every downloaded release file where ASTRA expects it, in one step.

For someone who downloaded the ASTRA release rather than cloning:

    1. Download ASTRA-update3-app.zip and extract it: you get an ASTRA folder.
    2. Download any data files you want (astra-data-*.zip, 2days.tar.gz, ...)
       into the folder that CONTAINS the ASTRA folder, or into Downloads.
    3. python ASTRA/scripts/unpack_release.py

Each astra-*.zip holds paths relative to the repository root and is extracted
there; 2days.tar.gz (the NGAFID benchmark) goes to data/benchmarks/ngafid.
Nothing is deleted, and a file already unpacked is left alone.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH = [ROOT.parent, ROOT, Path.home() / "Downloads"]


def _found(pattern: str) -> list[Path]:
    seen, out = set(), []
    for d in SEARCH:
        if d.is_dir():
            for p in sorted(d.glob(pattern)):
                if p.name not in seen and p.is_file():
                    seen.add(p.name)
                    out.append(p)
    return out


def main() -> int:
    print(f"ASTRA folder: {ROOT}")
    zips = [z for z in _found("astra-*.zip") if z.name != "ASTRA-update3-app.zip"]
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            todo = [n for n in names if not (ROOT / n).exists()]
            print(f"  {z.name}: {len(todo)} of {len(names)} files to unpack")
            for n in todo:
                zf.extract(n, ROOT)
    for t in _found("2days.tar.gz"):
        dest = ROOT / "data" / "benchmarks" / "ngafid"
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / t.name
        if not target.exists():
            print(f"  {t.name}: copying to {dest}")
            target.write_bytes(t.read_bytes())
        with tarfile.open(target) as tf:
            members = [m for m in tf.getmembers() if not (dest / m.name).exists()]
            print(f"  {t.name}: {len(members)} entries to extract")
            try:
                tf.extractall(dest, members=members, filter="data")
            except TypeError:           # Python before 3.11.4 has no filter
                tf.extractall(dest, members=members)
    if not zips and not _found("2days.tar.gz"):
        print("  no release data files found next to the ASTRA folder or in Downloads.")
        print("  The app runs without them; they are only needed to retrain.")
    print("done. Start ASTRA with:  python run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
