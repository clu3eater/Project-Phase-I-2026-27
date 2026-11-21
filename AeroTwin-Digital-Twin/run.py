#!/usr/bin/env python3
"""Start the whole system with one command.

    python run.py

That is the entire quickstart. This script finds or builds everything the
twin needs, proves each layer works once, and then serves the console.

WHY THIS EXISTS
---------------
The documented quickstart was `pip install -e .` followed by
`python -m layer4_core.twin_api`, and on a clean machine that DOES NOT WORK.
`twin_api` imports `layer4_core.security` at module scope, which imports
`jwt`, `bcrypt` and `cryptography` with no guard -- and all three live in the
OPTIONAL `security` extra. A fresh install therefore dies on ModuleNotFoundError
before it reaches the first line of `main()`. The console is a second instance
of the same problem: `dist/` is git-ignored, so a fresh clone has no built
console at all and the root URL returns a JSON hint instead of the page.

Neither is a deep defect -- both are one `pip` flag and one `npm` invocation --
but both are exactly the kind of thing that turns a five-minute demonstration
into a twenty-minute debugging session in front of an evaluator. This script
removes that class of failure by checking every precondition and fixing what it
can rather than assuming a correctly prepared machine.

WHAT IT DOES NOT DO
-------------------
It does not regenerate the fleet or retrain anything. It does not need to: the
serving path uses the PHYSICS remaining-life estimator (`layer3_ai.rul_physics`)
and the rule and statistical detection tiers, none of which load a trained
model. The LSTM, the deep classifier and the ONNX edge graph are needed only to
REPRODUCE the reported numbers, which is `scripts/retrain_all.py` and about an
hour. Starting the system is seconds.

Nothing here is faked for the demonstration. The self-check drives the real CAN
simulator through the real ingest path, the real rule engine and the real
shadow model, and reports the frame counters those produce.

Stdlib only, because it has to run BEFORE anything is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# DT_VENV relocates the environment. Mostly this matters for testing this
# script itself -- verifying that the from-nothing path really works should not
# require destroying the environment you are working in.
VENV = Path(os.environ["DT_VENV"]).resolve() if os.environ.get("DT_VENV") \
    else ROOT / ".venv"
CONSOLE = ROOT / "layer5_viz" / "gcs_console"
CONSOLE_DIST = CONSOLE / "dist"
CREDENTIALS = ROOT / "data" / "keys" / "FIRST_RUN_CREDENTIALS.txt"

MIN_PYTHON = (3, 11)

# Set on the re-exec into the virtual environment so we cannot loop forever if
# the venv's interpreter somehow still reports itself as the system one.
REEXEC_FLAG = "DT_RUN_REEXEC"

# import name -> the pip extra that provides it. Everything here is needed to
# SERVE; the optional table below is not.
REQUIRED = {
    "numpy": "core", "scipy": "core", "pandas": "core", "pyarrow": "core",
    "yaml": "core", "pydantic": "core", "can": "core", "cantools": "core",
    "sklearn": "core", "fastapi": "core", "uvicorn": "core",
    "websockets": "core",
    # The three that break the documented quickstart.
    "jwt": "security", "bcrypt": "security", "cryptography": "security",
    # Guarded at import, so the API starts without it -- but then the PDF
    # export the REPORT page offers returns an error instead of a report,
    # which is a worse demonstration than not offering it.
    "reportlab": "reports",
}

# Absent these the system still runs; specific extras degrade. Reported, not
# installed, unless --full is given.
OPTIONAL = {
    "onnxruntime": ("edge", "on-aircraft ONNX inference and scripts/edge_footprint.py"),
    "torch": ("ml", "training and re-evaluating the deep models"),
    "cantera": ("physics", "live combustion chemistry (a precomputed lookup ships in-repo)"),
    "pytest": ("dev", "the test suite"),
}

# What actually gets installed by default. `edge` is included because
# onnxruntime is small and it makes layer 1 completely exercisable; `ml` is not,
# because torch is roughly 2 GB and nothing on the serving path imports it.
DEFAULT_EXTRAS = ["security", "reports", "edge"]

WIN = os.name == "nt"


# ---------------------------------------------------------------------------
# Output. ASCII only: this prints to cp1252 consoles on Windows, and the
# project already has three recorded defects from non-ASCII characters
# rendering as replacement glyphs (DEV-112, DEV-146).
# ---------------------------------------------------------------------------

_step_n = 0


def stage(title: str) -> None:
    global _step_n
    _step_n += 1
    print(f"\n[{_step_n}/6] {title}")
    print("-" * (len(title) + 6))


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def info(msg: str) -> None:
    print(f"  ..    {msg}")


def warn(msg: str) -> None:
    print(f"  WARN  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def die(msg: str, hint: str = "") -> None:
    print(f"\nSTOPPED: {msg}")
    if hint:
        print(f"         {hint}")
    sys.exit(1)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=kw.pop("cwd", ROOT), **kw)


def npm_command() -> list[str] | None:
    """Return an npm command prefix that subprocess can launch on this OS."""
    if os.name == "nt":
        # Windows PATH can list npm's extensionless Unix shell shim before
        # npm.cmd. CreateProcess cannot execute that shim (WinError 193), and
        # batch files need cmd.exe to launch them.
        npm = shutil.which("npm.cmd")
        if npm:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "call", npm]

        # Some Node distributions provide a native npm.exe instead.
        npm = shutil.which("npm.exe")
        return [npm] if npm else None

    npm = shutil.which("npm")
    return [npm] if npm else None


# ---------------------------------------------------------------------------
# 1. Interpreter
# ---------------------------------------------------------------------------

def check_python() -> None:
    stage("Python")
    v = sys.version_info
    got = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        die(
            f"Python {got} is too old; this project needs "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            "Install a newer Python and run this script with it.",
        )
    ok(f"Python {got} on {platform.system()} {platform.machine()}")


# ---------------------------------------------------------------------------
# 2. Virtual environment
# ---------------------------------------------------------------------------

def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WIN else "bin/python")


def bootstrap_venv() -> None:
    """Get into a virtual environment, then hand this script over to it.

    Runs BEFORE the banner, and exits the parent process, so the run the user
    actually watches is the one inside the venv -- printing the banner and the
    first two stages twice made it look like the script had restarted itself
    after a failure.

    Installing into whatever interpreter happened to be on PATH is how a
    machine ends up with a broken system Python, so this refuses to do it.
    """
    if sys.prefix != sys.base_prefix:      # already inside one
        return
    if os.environ.get(REEXEC_FLAG):        # handed over once already
        return

    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        die(f"Python {v.major}.{v.minor}.{v.micro} is too old; this project "
            f"needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            "Install a newer Python and run this script with it.")

    py = venv_python()
    if not py.exists():
        print(f"no virtual environment yet; creating {VENV}")
        r = run([sys.executable, "-m", "venv", str(VENV)])
        if r.returncode != 0 or not py.exists():
            die("could not create a virtual environment.",
                "On Debian/Ubuntu this usually means: apt install python3-venv")

    env = dict(os.environ, **{REEXEC_FLAG: "1"})
    r = subprocess.run([str(py), str(Path(__file__).resolve()), *sys.argv[1:]],
                       cwd=ROOT, env=env)
    sys.exit(r.returncode)


def report_venv() -> None:
    stage("Virtual environment")
    if sys.prefix != sys.base_prefix:
        ok(f"running inside {sys.prefix}")
    else:
        warn("not running inside a virtual environment; packages would be")
        warn("installed into the system Python. Create one with:")
        warn("    python -m venv .venv")


# ---------------------------------------------------------------------------
# 3. Python dependencies
# ---------------------------------------------------------------------------

def probe(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def ensure_deps(full: bool, reinstall: bool) -> None:
    stage("Python dependencies")

    missing = sorted(m for m in REQUIRED if not probe(m))

    if missing and not reinstall:
        info(f"missing: {', '.join(missing)}")
    elif not reinstall:
        ok(f"all {len(REQUIRED)} required packages present")

    extras = list(DEFAULT_EXTRAS)
    if full:
        extras += ["ml", "physics", "dev"]

    if missing or reinstall:
        spec = f".[{','.join(extras)}]"
        info(f"pip install -e \"{spec}\"  (this can take a few minutes)")
        r = run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                 "-q", "-e", spec])
        if r.returncode != 0:
            die("dependency installation failed; the pip output above says why.")

        import importlib
        importlib.invalidate_caches()

        still = sorted(m for m in REQUIRED if not probe(m))
        if still:
            die(f"still missing after install: {', '.join(still)}",
                "This usually means the install went to a different interpreter.")
        ok(f"installed; all {len(REQUIRED)} required packages present")

    for mod, (extra, why) in OPTIONAL.items():
        if probe(mod):
            ok(f"{mod} present ({why})")
        else:
            warn(f"{mod} absent -- {why} unavailable. "
                 f"Add it with: pip install -e \".[{extra}]\"")


# ---------------------------------------------------------------------------
# 4. Console
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3b. Large files, which a clone does not always bring
# ---------------------------------------------------------------------------

# What the pointer file a Git LFS clone leaves behind begins with. A pointer is
# about 130 bytes of text where a model or a mesh should be.
_LFS_MAGIC = b"version https://git-lfs"

# The files that have to be REAL for the system to do what it claims. Not the
# whole LFS set: the PDFs and the presentation decks can stay as pointers and
# nothing stops working.
_NEEDS_CONTENT = (
    ("data/models/tier3.pt", "the Tier-3 detection network"),
    ("data/models/rul_lstm.pt", "the remaining-life network"),
    ("data/models/tier2_extended.joblib", "the Tier-2 statistical ensemble"),
    ("data/models/tier3_edge.onnx", "the edge inference graph"),
    ("layer5_viz/gcs_console/public/engine3d/rotax915is.glb", "the 3D engine model"),
)


def _is_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(_LFS_MAGIC)) == _LFS_MAGIC
    except OSError:
        return False


def ensure_large_files() -> None:
    """Fetch the Git LFS content, or say plainly what is missing and why.

    THE TRAP THIS EXISTS FOR
    ------------------------
    This repository keeps its trained models, its edge graph and its 3D engine
    in Git LFS. `git clone` on a machine without git-lfs installed succeeds,
    reports nothing wrong, and leaves 130-byte text pointers where those files
    should be. Everything then starts, and fails quietly in ways that look like
    different bugs: the console reports the networks as "not installed on this
    aircraft", the engine panel reports the model unavailable, and the twin
    falls back to publishing no fault probabilities at all.

    Every one of those messages is TRUE, and none of them says "your clone did
    not bring the files". This does.
    """
    stage("Large files (Git LFS)")

    missing = [(rel, what) for rel, what in _NEEDS_CONTENT
               if (ROOT / rel).exists() and _is_pointer(ROOT / rel)]
    absent = [(rel, what) for rel, what in _NEEDS_CONTENT
              if not (ROOT / rel).exists()]

    if not missing and not absent:
        ok("all large files present")
        return

    if missing:
        info(f"{len(missing)} file(s) are Git LFS pointers, not content")
        git = shutil.which("git")
        if git and run([git, "lfs", "version"], capture_output=True).returncode == 0:
            info("git lfs pull  (a few hundred megabytes on a cold clone)")
            if run([git, "lfs", "pull"]).returncode == 0:
                missing = [(rel, what) for rel, what in missing
                           if _is_pointer(ROOT / rel)]
                if not missing:
                    ok("large files fetched")
        else:
            warn("git-lfs is not installed, so the clone could not bring them")
            warn("  install it from https://git-lfs.com, then:")
            warn("    git lfs install && git lfs pull")

    for rel, what in missing + absent:
        warn(f"MISSING: {what}")
        warn(f"         {rel}")
    if missing or absent:
        warn("The system will still start. What depends on these files will")
        warn("say so rather than inventing a number, which is the designed")
        warn("behaviour -- but it is not the system working.")


def ensure_console(skip: bool) -> bool:
    stage("Operator console")

    if skip:
        info("skipped by --no-console")
        return CONSOLE_DIST.is_dir()

    built = CONSOLE_DIST / "index.html"
    # A build older than its source is the OLD console. "Already built" used
    # to be enough, so pulling an update that added pages served the console
    # from before it, with nothing to say so.
    stale = False
    if built.exists():
        t_built = built.stat().st_mtime
        sources = [*(CONSOLE / "src").rglob("*"), CONSOLE / "index.html",
                   CONSOLE / "package.json"]
        stale = any(f.is_file() and f.stat().st_mtime > t_built for f in sources)
        if not stale:
            ok("already built")
            return True

    npm = npm_command()
    if stale and not npm:
        warn("the console source is newer than its build, and npm is not on")
        warn("PATH to rebuild it: serving the OLD console. Install Node.js 20+.")
        return True
    if not npm:
        warn("dist/ is git-ignored and npm was not found on PATH, so the")
        warn("console cannot be built. The API will still serve and every")
        warn("endpoint works; the root URL returns a JSON hint instead of")
        warn("the page. Install Node.js 20+ and re-run to get the console.")
        return False

    info("console source changed since the last build; rebuilding it" if stale
         else "no built console found (dist/ is git-ignored); building it now")
    if (CONSOLE / "node_modules").is_dir():
        ok("node_modules present, skipping install")
    else:
        sub = "ci" if (CONSOLE / "package-lock.json").exists() else "install"
        info(f"npm {sub}  (a few minutes on a cold cache)")
        r = run([*npm, sub], cwd=CONSOLE)
        if r.returncode != 0:
            warn("npm install failed; continuing without the console")
            return False

    info("npm run build")
    r = run([*npm, "run", "build"], cwd=CONSOLE)
    if r.returncode != 0 or not (CONSOLE_DIST / "index.html").exists():
        warn("console build failed; continuing without it")
        return False

    ok("console built")
    return True


# ---------------------------------------------------------------------------
# 5. Prove it works, once
# ---------------------------------------------------------------------------

def self_check(with_tests: bool, with_fault: bool) -> bool:
    stage("Self-check")
    passed = True

    # --- layers 1, 2 and 4: drive the real pipeline -----------------------
    info("running the live pipeline for a few seconds")
    try:
        from layer4_core.live import LiveTwin, available_faults
    except Exception as e:  # noqa: BLE001
        fail(f"cannot import the twin: {e}")
        return False

    twin = LiveTwin(speed=200.0)
    twin.start()
    try:
        # THE ENGINE STARTS PARKED AND COLD, so fly a short sortie. The
        # station no longer runs the engine on its own, and the health index
        # is judged only warm, loaded and steady (health.assessment) -- a
        # check that read a parked engine found chi = None and then crashed
        # comparing None with a number. Warm-up, launch at the hold, and wait
        # for the first assessment: about 8 s at 200x.
        from layer2_physics import engine_sim as es
        twin.begin_profile(es.mission_profile(0.3, 8000.0), kind="mission", label="SELF-CHECK")
        deadline = time.time() + 40.0
        launched = False
        while time.time() < deadline:
            s0 = twin.snapshot()
            if not launched and (s0.sortie or {}).get("holding"):
                launched = bool(twin.launch())
            if (s0.pipeline.get("ticks", 0) > 20
                    and isinstance(s0.health.get("chi"), (int, float))):
                break
            time.sleep(0.25)
        snap = twin.snapshot()
        p = snap.pipeline

        checks = [
            ("layer 1  CAN frames decoded",
             p.get("frames_decoded", 0) > 0, f"{p.get('frames_decoded', 0)} frames"),
            ("layer 1  no frames lost",
             p.get("frames_lost", 1) == 0, f"{p.get('frames_lost')} lost"),
            ("layer 1  no decode errors",
             p.get("decode_errors", 1) == 0, f"{p.get('decode_errors')} errors"),
            ("layer 1  no frames refused (sender, type, sequence)",
             p.get("frames_rejected", 1) == 0, f"{p.get('frames_rejected')} refused"),
            ("layer 1  all channels usable",
             p.get("channels_usable") == p.get("channels_total"),
             f"{p.get('channels_usable')}/{p.get('channels_total')} channels"),
            ("layer 2  shadow model locked",
             bool(p.get("shadow_available")), "as-new reference available"),
            ("layer 2  residuals produced",
             len(snap.twin.get("residuals", {})) >= 7,
             f"{len(snap.twin.get('residuals', {}))} residual channels"),
            ("layer 3  health index computed",
             isinstance(snap.health.get("chi"), (int, float)),
             f"chi = {snap.health.get('chi')}"),
            # NOT "hours is a number". On a healthy engine a few seconds in
            # there IS no measurable degradation trend, and the estimator
            # reports reportable=False with a reason rather than inventing a
            # figure. Asserting a number here would fail the system for
            # behaving correctly, so the contract is what gets checked.
            ("layer 3  remaining life contract",
             {"hours", "lower", "upper", "confidence", "reason",
              "reportable"} <= set(snap.rul),
             (f"{snap.rul.get('hours')} h "
              f"[{snap.rul.get('lower')}, {snap.rul.get('upper')}]"
              if snap.rul.get("reportable")
              else f"withheld: {snap.rul.get('reason')}")),
            ("layer 3  three-tier fusion",
             bool(snap.fusion.get("level_name")),
             f"{snap.fusion.get('level_name')} "
             f"(score {snap.fusion.get('score')})"),
            ("layer 3  eight PS fault modes",
             len(available_faults()) == 8, f"{len(available_faults())} modes"),
            ("layer 4  operator view smoothed",
             "chi" in snap.display, f"band {snap.display.get('band')}"),
            ("layer 4  latency within budget",
             p.get("latency_p95_ms", 999) < 200,
             f"p50 {p.get('latency_p50_ms')} ms, p95 {p.get('latency_p95_ms')} ms"),
        ]
        for name, good, detail in checks:
            (ok if good else fail)(f"{name:<34} {detail}")
            passed &= good

        # --- the headline claim, proved rather than asserted --------------
        if with_fault:
            info("injecting a cooling fault to show detection before any limit trips")
            before = snap.health.get("chi")
            twin.inject("cooling_degradation", 0.85)
            # Wait for the signature to actually DEVELOP, not merely to become
            # visible. Breaking at the first 0.01 of movement made the result
            # depend on timing -- one run showed the band falling GOOD to FAIR,
            # the next showed it not moving at all. The health index is EMA
            # smoothed (alpha 0.1, PRD Part 2 s9.4), so it needs a few seconds
            # of ticks before it reflects the fault, and a demonstration that
            # is sometimes dramatic and sometimes marginal proves nothing.
            t_end = time.time() + 25.0
            while time.time() < t_end:
                now_chi = twin.snapshot().health.get("chi")
                if isinstance(now_chi, (int, float)) and now_chi < (before or 1.0) - 0.06:
                    break
                time.sleep(0.3)
            s2 = twin.snapshot()
            after = s2.health.get("chi")
            al = s2.twin.get("alerts", {})
            active = al.get("active", []) if isinstance(al, dict) else []
            master = bool(al.get("master_warning")) or bool(al.get("master_caution"))
            dropped = (after is not None and before is not None and after < before)
            (ok if dropped else warn)(
                f"{'layer 3  health fell on the fault':<34} "
                f"chi {before} -> {after}")
            ok(f"{'layer 3  band / instruction':<34} "
               f"{s2.health.get('band')} / {s2.display.get('instruction')}")
            ok(f"{'layer 4  master warning/caution':<34} "
               f"{'RAISED' if master else 'silent'}")
            ok(f"{'layer 4  active limit alerts':<34} {len(active)}")
            if dropped and not master and not active:
                ok("  ^^ THE POINT: the twin registered the degradation while")
                ok("     every certified limit was still satisfied and a")
                ok("     conventional threshold monitor stayed silent.")
    finally:
        twin.stop()

    # --- layer 5 and traceability: the repo's own auditors -----------------
    for label, script in (("display standard (MIL-STD-1472H/411F)", "hmi_check.py"),
                          ("problem-statement traceability", "ps_compliance.py")):
        r = run([sys.executable, f"scripts/{script}"], capture_output=True, text=True)
        # Skip the rule-off divider lines these scripts print around their
        # verdict, or the "summary" is a row of equals signs.
        lines = [ln.strip() for ln in (r.stdout or "").splitlines()
                 if ln.strip() and set(ln.strip()) - set("=- ")]
        summary = lines[-1] if lines else "(no output)"
        if r.returncode == 0:
            ok(f"{label:<34} {summary}")
        else:
            fail(f"{label:<34} {summary}")
            passed = False

    if with_tests:
        if not probe("pytest"):
            warn("pytest absent; skipping the suite (install with --full)")
        else:
            info("running the full test suite (about 18 minutes)")
            r = run([sys.executable, "-m", "pytest", "-q"])
            if r.returncode == 0:
                ok("test suite passed")
            else:
                fail("test suite reported failures")
                passed = False

    return passed


# ---------------------------------------------------------------------------
# 6. Serve
# ---------------------------------------------------------------------------

def show_credentials() -> None:
    if not CREDENTIALS.exists():
        info("demonstration accounts will be generated on first login")
        return
    print("\n  Demonstration accounts (generated locally, never committed):")
    for line in CREDENTIALS.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            print(f"    {line}")


def wait_ready(port: int, proc: subprocess.Popen, timeout: float = 60.0) -> bool:
    """Poll /api/healthz until the pipeline is actually producing ticks.

    Deliberately not a port check: the port opens before the engine is
    running, and reporting 'ready' at that moment sends whoever is watching
    to a console that shows nothing.
    """
    url = f"http://127.0.0.1:{port}/api/healthz"
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    return False


def serve(port: int, console_ok: bool, open_browser: bool) -> int:
    stage("Serving")

    # A DEMONSTRATION SORTIE HAS TO FINISH.
    #
    # The default profile cruises for an hour, and the loop is compute-bound at
    # roughly 15x real time however high `speed` is set -- so a full sortie
    # needs about six minutes of wall clock. Nobody watches a demonstration
    # that long, so the flight was always stopped in the climb and the
    # post-flight report showed take-off, climb, and a chart cut off at the
    # right-hand edge with no cruise, descent or landing in it.
    #
    # Six minutes of cruise instead of sixty gets the whole shape -- ground,
    # taxi, take-off, climb, cruise, descent, landing -- into about two
    # minutes. Set DT_CRUISE_HOURS yourself to override; a deployment leaves it
    # alone and gets the realistic profile.
    env = dict(os.environ, DT_PORT=str(port))
    env.setdefault("DT_CRUISE_HOURS", "0.1")
    proc = subprocess.Popen([sys.executable, "-m", "layer4_core.twin_api"],
                            cwd=ROOT, env=env)

    if not wait_ready(port, proc):
        if proc.poll() is not None:
            fail(f"the server exited with code {proc.returncode}")
            return proc.returncode or 1
        fail("the server started but never reported a running pipeline")
        proc.terminate()
        return 1

    url = f"http://127.0.0.1:{port}"
    ok(f"pipeline running and serving on {url}")

    print()
    print("=" * 68)
    print(f"  OPEN  {url}")
    print("=" * 68)
    if not console_ok:
        print("  The console is not built, so the root URL returns a JSON")
        print("  hint. Every /api endpoint below works regardless.")
    print(f"  API   {url}/api/state   {url}/api/healthz")
    print(f"  Live  ws://127.0.0.1:{port}/ws/state")
    show_credentials()
    print("\n  Ctrl-C to stop.")
    print("=" * 68)

    if open_browser and console_ok:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    try:
        proc.wait()
    except KeyboardInterrupt:
        # Ctrl-C at a terminal is delivered to the whole process group, so the
        # server has usually begun shutting down before we get here. Give it a
        # moment to do that cleanly, then insist. Not CTRL_BREAK_EVENT: that
        # needs a child created with CREATE_NEW_PROCESS_GROUP, which this one
        # deliberately is not -- sharing the group is what lets Ctrl-C reach it.
        print("\n\nstopping...")
        try:
            proc.wait(timeout=10)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except (KeyboardInterrupt, subprocess.TimeoutExpired):
                proc.kill()
        ok("stopped")
        return 0
    return proc.returncode or 0


# ---------------------------------------------------------------------------

def engine_commands(args) -> int | None:
    """--list-engines and --check-engine. None means carry on."""
    from common import config

    stage("Engines")
    if args.list_engines:
        try:
            import yaml
            fleet = yaml.safe_load((config.config_dir() / "fleet.yaml").read_text(
                encoding="utf-8")) or {}
        except OSError:
            fleet = {}
        fitted: dict[str, list[str]] = {}
        for a in fleet.get("aircraft", []):
            fitted.setdefault(a["engine_key"], []).append(a["tail"])
        for e in config.engine_catalogue():
            state = "ok" if e["usable"] else f"{len(e['problems'])} problem(s)"
            valid = "" if e["validated"] else "  [unvalidated]"
            base = f"  (extends {' -> '.join(e['extends'])})" if e["extends"] else ""
            on = ", ".join(fitted.get(e["key"], [])) or "no aircraft"
            print(f"  {e['key']:<20} {state:<14} {e['display_name']}{valid}{base}")
            print(f"  {'':<20} fitted to: {on}")
        print("  New engine: copy configs/engines/_template.yaml, then fit it to an")
        print("  aircraft in configs/fleet.yaml or on the console's ENGINES page.")
        return 0
    if args.check_engine:
        problems = config.check_engine(args.check_engine)
        if not problems:
            try:
                from layer2_physics.engine_sim import VirtualEngine
                veng = VirtualEngine(engine_key=args.check_engine, seed=1)
                for _ in range(20):
                    veng.step(0.5)
            except Exception as exc:  # noqa: BLE001 - reported to the author
                problems = [f"the engine does not run: {type(exc).__name__}: {exc}"]
        if problems:
            for msg in problems:
                fail(msg)
            return 1
        ok(f"{args.check_engine}: complete, and runs in the virtual engine")
        return 0
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="run.py",
        description="Check every precondition, prove each layer works, "
                    "and serve the engine digital twin.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python run.py                 install what is missing, self-check, serve
  python run.py --check         everything except serving, then exit
  python run.py --tests         also run the 508-test suite (~18 min)
  python run.py --demo          run the 90-second terminal demonstration
  python run.py --full          also install torch, cantera and pytest
  python run.py --port 9000     serve somewhere else
  python run.py --list-engines  every engine definition, and whether it is complete
  python run.py --check-engine my_engine   name every key my_engine is missing
""")
    ap.add_argument("--check", action="store_true",
                    help="run every check but do not serve")
    ap.add_argument("--tests", action="store_true",
                    help="also run the full test suite in the self-check")
    ap.add_argument("--demo", action="store_true",
                    help="run scripts/demo.py instead of serving")
    ap.add_argument("--full", action="store_true",
                    help="also install the ml, physics and dev extras")
    ap.add_argument("--reinstall", action="store_true",
                    help="reinstall dependencies even if they are present")
    ap.add_argument("--no-console", action="store_true",
                    help="do not build the React console")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open a browser")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the self-check and serve immediately")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DT_PORT", "8000")))
    ap.add_argument("--list-engines", action="store_true",
                    help="list the engine definitions and exit")
    ap.add_argument("--check-engine", metavar="KEY",
                    help="check one engine definition, name what is missing, and exit")
    args = ap.parse_args()

    # Line-buffer our own output. Python block-buffers stdout when it is not a
    # terminal, so piping this to a log or a CI file showed NOTHING -- and
    # because the serve path never returns, nothing is exactly what you got.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    # Before the banner: if we are outside a virtual environment this creates
    # one, hands the whole run over to it, and never returns.
    bootstrap_venv()

    print("=" * 68)
    print("  AERO PISTON ENGINE DIGITAL TWIN  --  DRDO / IDEX PS 26054")
    print("  one-command launcher")
    print("=" * 68)

    check_python()
    report_venv()
    ensure_deps(full=args.full, reinstall=args.reinstall)

    if args.list_engines or args.check_engine:
        rc = engine_commands(args)
        if rc is not None:
            return rc
    ensure_large_files()
    console_ok = ensure_console(skip=args.no_console)

    healthy = True
    if not args.no_check:
        healthy = self_check(with_tests=args.tests, with_fault=not args.demo)
        if healthy:
            ok("every check passed")
        else:
            warn("one or more checks failed; see above")

    if args.demo:
        stage("Demonstration")
        return run([sys.executable, "scripts/demo.py"]).returncode

    if args.check:
        stage("Done")
        ok("checks complete; --check given, so not serving")
        return 0 if healthy else 1

    return serve(args.port, console_ok, open_browser=not args.no_browser)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
