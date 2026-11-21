"""Scripted demonstration -- the system detecting a fault no limit catches.

Run:  python scripts/demo.py [--fault cooling_degradation] [--severity 0.85]

Ninety seconds, no browser needed. It runs the real pipeline: a virtual engine
feeding real CAN frames to a real edge node, a twin comparing them against an
as-new reference, and the AI layer reading the result. Nothing is staged.

The moment worth watching for is the one where the twin reports a degrading
engine while every certified limit is still satisfied. A threshold monitor
shows nothing at that point, and it is the reason this system exists.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from layer4_core.live import LiveTwin  # noqa: E402

def _enable_colour() -> bool:
    """True only if this terminal will actually render ANSI.

    A demonstration script is the one piece of software that has to work on
    someone else's machine at the moment it matters. Windows consoles need
    virtual-terminal processing switched on explicitly, and piping the output
    to a file should give readable text rather than escape codes.
    """
    if not sys.stdout.isatty():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x4) on stdout.
        return bool(k32.SetConsoleMode(k32.GetStdHandle(-11), 7))
    except Exception:
        return False


# The console's codepage is not ours to choose. cp1252 cannot encode a minus
# sign or an em dash, and the UnicodeEncodeError lands in the middle of the
# demonstration -- so the output is ASCII and stdout is reconfigured to be
# forgiving of anything that slips through.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_COLOUR = _enable_colour()
BOLD = "\033[1m" if _COLOUR else ""
DIM = "\033[2m" if _COLOUR else ""
RED = "\033[31m" if _COLOUR else ""
YEL = "\033[33m" if _COLOUR else ""
GRN = "\033[32m" if _COLOUR else ""
CYN = "\033[36m" if _COLOUR else ""
OFF = "\033[0m" if _COLOUR else ""


def banner(text: str) -> None:
    print(f"\n{BOLD}{'=' * 74}{OFF}")
    print(f"{BOLD}  {text}{OFF}")
    print(f"{BOLD}{'=' * 74}{OFF}")


def row(lt: LiveTwin) -> None:
    s = lt.snapshot()
    if not s.pipeline:
        return
    h, r = s.health, s.twin["residuals"]
    alerts = s.twin["alerts"]["active"]
    adv = s.twin["advisory"]

    band_colour = (
        GRN if h["chi"] >= 0.80 else YEL if h["chi"] >= 0.60 else RED
    )
    limit_colour = RED if alerts else GRN
    res = r["cht"]["mean_delta"]

    print(
        f"  t+{s.t_s:6.0f}s  "
        f"CHI {band_colour}{h['chi']:.3f} {h['band']:<9}{OFF} "
        f"THRM {h['thermal']:.2f}  "
        f"resid CHT {CYN}{res:+5.1f} K{OFF}  "
        f"limits {limit_colour}{len(alerts)}{OFF}  "
        f"{adv['severity']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fault", default="cooling_degradation")
    ap.add_argument("--severity", type=float, default=0.85)
    ap.add_argument("--speed", type=float, default=120.0,
                    help="simulated seconds per wall second")
    args = ap.parse_args()

    banner("AERO PISTON ENGINE DIGITAL TWIN -- DRDO PS 26054")
    print(f"{DIM}  Rotax 915 iS - virtual CAN - every layer running for real{OFF}")

    lt = LiveTwin(speed=args.speed)
    lt.start()
    try:
        # ---------------------------------------------------------------
        banner("1. HEALTHY ENGINE")
        print(f"{DIM}  MIL-STD-411F 4.1.1a: a healthy engine must be SILENT.")
        print(f"  No 'all systems normal' banner -- nothing at all.{OFF}\n")
        for _ in range(6):
            time.sleep(4)
            row(lt)

        s = lt.snapshot()
        p = s.pipeline
        print(f"\n{DIM}  pipeline: {p['channels_usable']}/{p['channels_total']} channels valid, "
              f"{p['frames_decoded']} frames decoded, {p['decode_errors']} errors")
        print(f"  latency p50 {p['latency_p50_ms']} ms / p95 {p['latency_p95_ms']} ms "
              f"(budget 100 / 200 ms){OFF}")

        # ---------------------------------------------------------------
        banner(f"2. INJECTING {args.fault.upper().replace('_', ' ')} "
               f"-- severity {args.severity}")
        rec = lt.inject(args.fault, args.severity, ramp_hours=0.01)
        print(f"{DIM}  Injected into the physics model at {rec['onset_hours']:.3f} "
              f"flight hours. Nothing is faked at the display layer -- the")
        print(f"  cooling jacket really conducts less heat from now on.{OFF}\n")
        for _ in range(14):
            time.sleep(4)
            row(lt)

        # ---------------------------------------------------------------
        banner("3. WHAT THE SYSTEM CONCLUDED")
        s = lt.snapshot()
        h, adv = s.health, s.twin["advisory"]
        res = s.twin["residuals"]
        alerts = s.twin["alerts"]["active"]

        print(f"  health index      {h['chi']:.3f}  ({h['band']})")
        print(f"  thermal subsystem {h['thermal']:.3f}")
        print(f"  CHT residual      {res['cht']['mean_delta']:+.1f} K vs an as-new engine "
              f"at the same operating point")
        print(f"  CHT - coolant     {res['cht_minus_coolant']:.1f} K")
        print()
        print(f"  {BOLD}certified limits exceeded: {len(alerts)}{OFF}")
        if not alerts:
            print(f"  {DIM}Every reading is inside its certified band. A threshold")
            print(f"  monitor would show nothing here.{OFF}")
        print()
        print(f"  {BOLD}advisory{OFF}  [{adv['severity']}] {adv['message']}")
        print(f"            -> {adv['recommended_action']}")
        print(f"            -> {adv['time_to_action']}")

        rul = s.rul
        print()
        if rul["reportable"]:
            print(f"  remaining life    {rul['hours']:.0f} h "
                  f"[{rul['lower']:.0f}-{rul['upper']:.0f}, "
                  f"{rul['confidence']:.0%} confidence]")
        else:
            print(f"  remaining life    not determinable -- {rul['reason']}")

        # ---------------------------------------------------------------
        banner("4. CAN THIS ENGINE FLY?")
        print(f"{DIM}  Mission reliability -- the third pillar of the problem")
        print(f"  statement's title. The answer depends on the mission.{OFF}\n")
        for prof in s.mission.get("profiles", []):
            colour = {"GO": GRN, "GO_WITH_LIMITS": YEL, "NO_GO": RED}.get(
                prof["verdict"], ""
            )
            missions = (
                f"{prof['missions_remaining']:.1f}"
                if prof["missions_remaining"] is not None else "--"
            )
            print(f"  {prof['profile']:<14} {colour}{prof['verdict']:<15}{OFF}"
                  f" P(success) {prof['success_probability']:.2f}"
                  f"  missions left {missions}")
            for reason in prof["reasons"][:2]:
                print(f"       {DIM}- {reason}{OFF}")
            for tip in prof["recommendations"][:1]:
                print(f"       -> {tip}")

        banner("DONE")
        print(f"{DIM}  Full console: python -m layer4_core.twin_api "
              f"-> http://127.0.0.1:8000{OFF}\n")
    finally:
        lt.stop()


if __name__ == "__main__":
    main()
