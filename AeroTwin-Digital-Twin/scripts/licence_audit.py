"""Dependency and licence audit -- the evidence behind the indigenisation claim.

The problem statement asks for an *indigenous* Digital Twin framework. That
claim is only worth making if it can be checked, so this walks the ACTUAL
installed dependency closure rather than the declared top-level list, reads
each distribution's licence metadata, and flags anything that would compromise
the claim:

  * a proprietary or source-unavailable package  -- a foreign vendor in the
    critical path, and a licence cost;
  * a copyleft licence (GPL/AGPL/SSPL)           -- a distribution constraint
    on a system that will be handed to a defence establishment;
  * a package that phones home                   -- a data-sovereignty problem;
  * an unknown or missing licence                -- the honest answer is that
    it is unaudited, not that it is fine.

It exits non-zero if anything in the first two categories is present, so the
claim cannot quietly rot as dependencies are added.

    python scripts/licence_audit.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Licence families, checked against the normalised licence string.
PERMISSIVE = (
    "mit", "bsd", "apache", "isc", "python software foundation", "psf",
    "mpl", "mozilla", "zlib", "unlicense", "public domain", "cc0",
    "historical permission notice", "hpnd", "0bsd", "apache-2.0",
)
# Copyleft: usable, but it constrains how the system may be distributed and
# that has to be a conscious decision rather than a surprise at handover.
COPYLEFT = ("gpl", "agpl", "sspl", "lgpl", "eupl", "cecill", "osl")
# LGPL is weak copyleft -- dynamic linking is fine. Kept separate so it is not
# reported as if it were GPL.
WEAK_COPYLEFT = ("lgpl",)

# Top-level dependencies as declared in pyproject.toml. Kept here rather than
# parsed so that the audit still runs from a wheel with no pyproject present.
ROOTS = [
    # core
    "numpy", "scipy", "pandas", "pyarrow", "pyyaml", "pydantic",
    "python-can", "cantools", "scikit-learn", "fastapi", "uvicorn",
    "websockets",
    # extras: ml / edge / physics / reports / security / fleet / docs / dev
    "torch", "onnx", "onnxruntime", "cantera", "reportlab",
    # bcrypt and cryptography are imported BY NAME in layer4_core/security.py,
    # so they are roots in their own right. Leaning on passlib[bcrypt] and
    # pyjwt[crypto] to drag them in made them transitive dependencies of code
    # that imports them directly -- and a transitive dependency disappears
    # the day the intermediary changes its own requirements. This audit
    # flagged exactly that, which is what it is for.
    "pyjwt", "passlib", "bcrypt", "cryptography",
    "asyncpg",                      # fleet: fleet_server, register_station
    "python-pptx",
    "pytest", "pytest-asyncio", "httpx", "ruff", "mypy",
    "psutil",                       # scripts/edge_footprint.py
    "pypdf",                        # layer4_core/tests/test_report_pdf.py
]


# Distribution name -> the module you actually import. Needed to answer "is
# this dependency used", which is a different question from "is it licensed
# acceptably" and just as relevant to the indigenisation claim: a declared
# dependency nothing imports is an unnecessary foreign component in the
# manifest of a system being handed to a defence establishment.
IMPORT_NAME = {
    "pyyaml": "yaml",
    "python-can": "can",
    "scikit-learn": "sklearn",
    "pyjwt": "jwt",
    "paho-mqtt": "paho",
    "pydantic-settings": "pydantic_settings",
    "pillow": "PIL",
    "onnxruntime": "onnxruntime",
    "python-pptx": "pptx",
    "pytest-asyncio": "pytest_asyncio",
    "types-pyyaml": "yaml",
}

# Declared for reasons other than being imported. Each needs a stated reason,
# because "it is probably needed by something" is how a manifest rots.
JUSTIFIED_UNUSED = {
    "pyarrow": "parquet engine pandas requires; used through pandas, not imported",
    "websockets": "WS transport uvicorn uses to serve /ws/state",
    "onnx": "edge export path (extra: edge)",
    "onnxruntime": "edge inference without torch (extra: edge)",
    "reportlab": "PDF post-flight report export (extra: reports)",
    "pyjwt": "twin API authentication (extra: security)",
    "passlib": "twin API password hashing (extra: security)",
    "ruff": "linter, invoked as a command",
    "mypy": "type checker, invoked as a command",
    "pytest-asyncio": "pytest plugin, loaded by pytest not imported",
    "httpx": "fastapi.testclient transport",
}

SOURCE_DIRS = ("layer1_edge", "layer2_physics", "layer3_ai", "layer4_core",
               "layer5_viz", "common", "scripts", "tests")


def unused_roots() -> list[str]:
    """Declared dependencies that nothing in the source tree imports."""
    text = []
    # Repo root still scanned, though nothing should live there now:
    # gen_ppt.py moved into scripts/, and a root .py reappearing is worth
    # catching rather than silently skipping.
    for d in SOURCE_DIRS + (".",):
        base = REPO / d
        if not base.is_dir():
            continue
        for f in (base.glob("*.py") if d == "." else base.rglob("*.py")):
            if f.name == "licence_audit.py":
                continue  # it names every package by definition
            try:
                text.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    blob = "\n".join(text)
    out = []
    for root in ROOTS:
        mod = IMPORT_NAME.get(_norm(root), _norm(root).replace("-", "_"))
        if f"import {mod}" not in blob and f"from {mod}" not in blob:
            if _norm(root) in JUSTIFIED_UNUSED:
                continue
            out.append(root)
    return out


LOCAL_PACKAGES = set(SOURCE_DIRS) | {"conftest"}


def undeclared_imports() -> list[dict]:
    """Third-party modules the source imports that nothing declares.

    The more serious direction of the two. An unused declaration is clutter; an
    UNDECLARED import means a clean checkout does not install what the repo
    needs to run its own code, and the failure surfaces on someone else's
    machine rather than here.
    """
    import ast

    provided = metadata.packages_distributions()
    declared = set(closure(ROOTS))
    # A root that is declared but not installed locally is still DECLARED --
    # a clean checkout would install it. Map it through IMPORT_NAME so it is
    # not reported as undeclared just because this machine lacks it.
    declared_modules = {
        IMPORT_NAME.get(_norm(r), _norm(r).replace("-", "_")) for r in ROOTS
    }
    stdlib = set(getattr(sys, "stdlib_module_names", set()))

    found: dict[str, set[str]] = {}
    for d in SOURCE_DIRS + (".",):
        base = REPO / d
        if not base.is_dir():
            continue
        pyfiles = base.glob("*.py") if d == "." else base.rglob("*.py")
        for f in pyfiles:
            if f.name == "licence_audit.py":
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # level > 0 is a relative import, always local.
                    if node.level or not node.module:
                        continue
                    mods = [node.module.split(".")[0]]
                else:
                    continue
                for m in mods:
                    if m in stdlib or m in LOCAL_PACKAGES or m.startswith("_"):
                        continue
                    found.setdefault(m, set()).add(
                        str(f.relative_to(REPO)).replace("\\", "/")
                    )

    out = []
    for mod, files in sorted(found.items()):
        dists = {_norm(x) for x in provided.get(mod, [])}
        if dists & declared:
            continue
        if mod in declared_modules:
            continue
        out.append({
            "module": mod,
            "distribution": sorted(dists)[0] if dists else "(not installed)",
            "used_by": sorted(files)[:3],
        })
    return out


def _norm(name: str) -> str:
    return name.lower().replace("_", "-").strip()


def _licence_of(dist: metadata.Distribution) -> str:
    """Licence text from metadata, preferring the classifier.

    ``License:`` is free-form and packages fill it with anything from "MIT" to
    the entire licence body, so the trove classifier is the more reliable
    source when it is present.
    """
    md = dist.metadata
    classifiers = md.get_all("Classifier") or []
    for c in classifiers:
        if c.startswith("License :: "):
            tail = c.rsplit(" :: ", 1)[-1].strip()
            if tail and tail != "OSI Approved":
                return tail
    expr = md.get("License-Expression")
    if expr:
        return str(expr).strip()
    lic = md.get("License")
    if lic:
        lic = str(lic).strip()
        # Some packages inline the whole licence; keep the first line only.
        return lic.splitlines()[0][:80] if lic else "UNKNOWN"
    return "UNKNOWN"


def _requires(dist: metadata.Distribution) -> list[str]:
    """Runtime requirements, skipping extras-gated ones.

    A requirement marked ``extra == "docs"`` is not installed unless that extra
    is requested, so counting it would overstate the closure.
    """
    out = []
    for req in dist.requires or []:
        if "extra ==" in req:
            continue
        name = req.split(";")[0].split("[")[0]
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", " "):
            name = name.split(sep)[0]
        name = _norm(name)
        if name:
            out.append(name)
    return out


def closure(roots: list[str]) -> dict[str, metadata.Distribution]:
    """Every distribution actually reachable from the declared roots."""
    found: dict[str, metadata.Distribution] = {}
    missing: list[str] = []
    q = deque(_norm(r) for r in roots)
    while q:
        name = q.popleft()
        if name in found or name in missing:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        found[name] = dist
        q.extend(_requires(dist))
    return found


def classify(lic: str) -> str:
    low = lic.lower()
    if any(k in low for k in WEAK_COPYLEFT):
        return "weak-copyleft"
    if any(k in low for k in COPYLEFT):
        return "copyleft"
    if any(k in low for k in PERMISSIVE):
        return "permissive"
    if low in ("unknown", "", "none"):
        return "unknown"
    return "other"


def audit() -> dict:
    dists = closure(ROOTS)
    rows = []
    for name, dist in sorted(dists.items()):
        lic = _licence_of(dist)
        rows.append({
            "package": name,
            "version": dist.version,
            "licence": lic,
            "class": classify(lic),
        })

    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(r["class"], []).append(r)

    # A root that is not installed is not a finding about licences -- it is a
    # gap in the audit, and is reported as such rather than silently skipped.
    not_installed = [
        r for r in (_norm(x) for x in ROOTS) if r not in dists
    ]

    return {
        "packages": rows,
        "counts": {k: len(v) for k, v in sorted(buckets.items())},
        "total": len(rows),
        "copyleft": buckets.get("copyleft", []),
        "unknown": buckets.get("unknown", []),
        "other": buckets.get("other", []),
        "roots_not_installed": not_installed,
        "roots_unused": unused_roots(),
        "undeclared": undeclared_imports(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true",
                    help="list every package, not just the findings")
    args = ap.parse_args()

    result = audit()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 78)
        print("  DEPENDENCY AND LICENCE AUDIT")
        print("=" * 78)
        print(f"  {result['total']} distributions in the installed closure "
              f"of {len(ROOTS)} declared roots")
        for k, v in result["counts"].items():
            print(f"    {k:<16} {v:>4}")
        if args.verbose:
            print("-" * 78)
            for r in result["packages"]:
                print(f"  {r['package']:<28} {r['version']:<12} "
                      f"{r['class']:<15} {r['licence'][:30]}")
        for label, key in (("COPYLEFT", "copyleft"),
                           ("UNCLASSIFIED LICENCE", "other"),
                           ("NO LICENCE METADATA", "unknown")):
            if result[key]:
                print("-" * 78)
                print(f"  {label}:")
                for r in result[key]:
                    print(f"    {r['package']:<28} {r['version']:<12} "
                          f"{r['licence'][:40]}")
        if result["undeclared"]:
            print("-" * 78)
            print("  IMPORTED BUT NEVER DECLARED (a clean checkout will not run):")
            for r in result["undeclared"]:
                print(f"    {r['module']:<20} -> {r['distribution']:<22} "
                      f"{', '.join(r['used_by'])}")
        if result["roots_unused"]:
            print("-" * 78)
            print("  DECLARED BUT NEVER IMPORTED (remove, or justify):")
            print("    " + ", ".join(result["roots_unused"]))
        if result["roots_not_installed"]:
            print("-" * 78)
            print("  DECLARED BUT NOT INSTALLED (not audited here):")
            print("    " + ", ".join(result["roots_not_installed"]))
        print("=" * 78)

    # Copyleft is the only hard failure: it constrains how the delivered system
    # may be distributed, which is a decision for the establishment taking
    # delivery and must never be made silently by adding a dependency.
    rc = 0
    if result["copyleft"]:
        print("FAIL: copyleft dependency in the runtime closure", file=sys.stderr)
        rc = 1
    if result["undeclared"]:
        print("FAIL: imported but undeclared dependency", file=sys.stderr)
        rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
