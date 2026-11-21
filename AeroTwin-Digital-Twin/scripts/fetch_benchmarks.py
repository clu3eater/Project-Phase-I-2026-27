"""Fetch the third-party benchmark datasets. Nothing here is committed.

WHY A SCRIPT AND NOT A COMMITTED FILE
-------------------------------------
Two reasons, and the second is the one that matters. C-MAPSS is 12 MB of
NASA's bytes and redistributing them inside this repository is not ours to do.
More importantly `docs/INDIGENISATION.md` makes a measured claim about what
this repository contains and depends on; a vendored foreign dataset would have
to be accounted for there, and accounting for it is more expensive than
fetching it on demand.

WHAT IT VERIFIES
----------------
The archive is checked against a recorded SHA-256 before extraction, and the
loader then asserts the fleet sizes the readme states. A truncated download
does not raise -- it reads as a smaller fleet, and would silently produce a
"benchmark" number that is not the benchmark. That is the failure this guards.

    python scripts/fetch_benchmarks.py            # fetch what is missing
    python scripts/fetch_benchmarks.py --check    # verify, download nothing
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from layer3_ai import cmapss  # noqa: E402

CMAPSS_URL = "https://data.nasa.gov/docs/legacy/CMAPSSData.zip"

# Recorded from the download of 2026-09-06. A mismatch is not automatically
# corruption -- NASA may legitimately republish -- but it must be a decision
# somebody makes, not a file that quietly changed under a benchmark.
CMAPSS_SHA256 = "74bef434a34db25c7bf72e668ea4cd52afe5f2cf8e44367c55a82bfd91a5a34f"

CMAPSS_MEMBERS = tuple(
    f"{kind}_{s}.txt" for s in cmapss.SUBSETS for kind in ("train", "test")
) + tuple(f"RUL_{s}.txt" for s in cmapss.SUBSETS) + ("readme.txt",)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_cmapss(root: Path, *, force: bool = False) -> bool:
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "CMAPSSData.zip"

    if not archive.exists() or force:
        print(f"downloading {CMAPSS_URL}")
        urllib.request.urlretrieve(CMAPSS_URL, archive)  # noqa: S310
    else:
        print(f"archive already present: {archive}")

    digest = _sha256(archive)
    if digest != CMAPSS_SHA256:
        print(f"  !! sha256 {digest}")
        print(f"     expected {CMAPSS_SHA256}")
        print("     REFUSING to extract. Either the download is damaged or NASA")
        print("     republished the archive; if the latter, update CMAPSS_SHA256")
        print("     deliberately and re-run the benchmark from scratch.")
        return False
    print(f"  sha256 verified ({archive.stat().st_size:,} bytes)")

    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad is not None:
            print(f"  !! archive corrupt at {bad}")
            return False
        # Extract only the members we expect, by exact name. A zip may name a
        # member "../something"; nothing here needs a general extractor.
        missing = [m for m in CMAPSS_MEMBERS if m not in z.namelist()]
        if missing:
            print(f"  !! archive is missing {missing}")
            return False
        for member in CMAPSS_MEMBERS:
            (root / member).write_bytes(z.read(member))
    print(f"  extracted {len(CMAPSS_MEMBERS)} files -> {root}")
    return True


def check_cmapss(root: Path) -> bool:
    if not cmapss.is_available(root):
        print(f"C-MAPSS not present under {root}")
        return False
    ok = True
    for name in cmapss.SUBSETS:
        try:
            s = cmapss.load(name, root)
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            print(f"  {name}: FAILED -- {exc}")
            ok = False
            continue
        print(f"  {name}: train {s.n_train_units:>3} units / "
              f"{len(s.train_unit):>6,} rows   "
              f"test {s.n_test_units:>3} units / {len(s.test_unit):>6,} rows")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify what is present; download nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the archive is present")
    args = ap.parse_args()

    root = config.data_dir() / "benchmarks"
    print("=" * 70)
    print("  NASA C-MAPSS turbofan benchmark")
    print("=" * 70)
    print("  NOT compatible with the reference engine and never mixed with it:")
    print("  a turbofan's gas path shares no sensor and no failure mode with a")
    print("  four-cylinder piston engine. It benchmarks the METHOD only.")
    print()

    if not args.check and not fetch_cmapss(root, force=args.force):
        return 1
    print()
    return 0 if check_cmapss(root) else 1


if __name__ == "__main__":
    raise SystemExit(main())
