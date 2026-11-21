# -*- coding: utf-8 -*-
"""Check the idea deck against the template's rules and the problem statement.

Three things go wrong in a generated deck and none of them raise an error:

  bounds     a shape sits off the slide, or under the footer strip, where it
             is invisible in the PDF the portal actually receives
  structure  more than the six slides the template allows, or a section the
             template asks for by name that is not there
  keywords   a term the problem statement uses that never appears as TEXT.
             A screening tool reads text, not pictures -- which is why the
             diagrams here are native shapes and not images.

    python scripts/check_ppt.py

Exits non-zero if anything fails.
"""
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

DECK = (Path(__file__).resolve().parent.parent / "docs"
        / "SIH_26054_Idea_Presentation.pptx")

SLIDE_W, SLIDE_H = 13.333, 7.5
FOOTER_TOP = 6.93        # the template's own footer bar starts here
MAX_SLIDES = 6           # the template's instruction slide says six, inclusive

# The sections the template names. Each must appear on the slide it belongs to.
REQUIRED = {
    2: ["proposed solution", "addresses the problem", "innovation"],
    3: ["architecture", "methodolog"],
    4: ["feasibility", "challenges and risks", "strategy"],
    5: ["impact", "benefits", "social", "economic", "environmental"],
    6: ["reference"],
}

# The template names technologies on slide 3, but the detailed stack sits on
# slide 4, beside the feasibility claim it supports -- repeating it on slide 3
# only crowded the architecture out. So this one is required somewhere in the
# deck rather than on a particular slide; removing it entirely still fails.
REQUIRED_ANYWHERE = ["technolog", "framework", "hardware", "security"]

# Transcribed from docs/ps.md, section by section, in the problem statement's
# OWN spelling. That matters: the PS writes "visualization", "behavior" and
# "synchronized", and an exact-match screen does not know that "visualisation"
# is the same word. Anything here that is absent from the deck is a keyword a
# screening pass will not find.
PS_TERMS = [
    # title and background
    "digital twin", "real-time", "health monitoring", "fault prediction",
    "mission reliability", "aero piston engine", "MALE UAV", "ISR",
    "communication relay", "maritime surveillance", "predictive maintenance",
    "operational reliability", "mission planning", "life cycle management",
    "virtual representation", "indigenous", "ground control",
    "engine state estimation", "anomaly detection", "degradation tracking",
    "mission replay", "scalable", "modular",
    # what the twin integrates
    "engine sensor data", "thermodynamic behavior", "engine performance maps",
    "AI/ML", "predictive analytics",
    # required capabilities
    "engine parameter visualization", "engine health indicators",
    "abnormal operating conditions", "probable failures",
    "degradation trends", "remaining useful life", "mission profiles",
    "environmental conditions", "post-flight analysis",
    # what it may use
    "CAN bus", "SocketCAN", "ECU", "FADEC", "edge computing",
    "server-based analytics", "physics informed", "dashboard", "HMI",
    "operators", "maintenance engineers",
    # A. core framework
    "virtual engine model", "modular architecture", "data ingestion",
    # B. monitored parameters
    "RPM", "cylinder head temperature", "exhaust gas temperature",
    "oil pressure", "oil temperature", "fuel flow", "vibration signatures",
    "battery", "alternator", "injection timing",
    # C. faults to detect and predict
    "misfire", "injector abnormalit", "cooling degradation", "lubrication",
    "sensor drift", "combustion instability", "overheating trends",
    "abnormal vibration",
    # D. AI/ML layer
    "trend analysis", "maintenance recommendation",
    # E. simulation and replay
    "historical mission data", "environmental condition simulation",
    "high altitude", "endurance", "hot-weather", "rapid throttle",
    # F. visualization dashboard
    "engine health status", "fault alerts", "engine efficiency trends",
    "maintenance advisory", "mission-wise health reports",
    # deliverables -- demonstrated by the slides rather than listed on one,
    # so each has to survive in the wording of the slide that shows it
    "prototype", "software demonstrator", "digital twin architecture",
    "engine simulation model", "visualization dashboard", "simulated",
    "technical documentation", "deployment roadmap",
    # desired innovation areas
    "physics-informed AI", "edge AI", "lightweight onboard analytics",
    "hybrid thermodynamic", "data-driven", "federated learning",
    "explainable AI", "secure telemetry", "autonomous maintenance advisory",
    # technical expectations
    "IC engine", "UAV propulsion", "sensor fusion", "embedded systems",
    "CAN communication", "data visualization", "simulation modelling",
    "reliability engineering",
]


def main():
    prs = Presentation(DECK)
    problems = []
    per_slide = {}

    if len(prs.slides) > MAX_SLIDES:
        problems.append(f"STRUCTURE  {len(prs.slides)} slides, template "
                        f"allows {MAX_SLIDES} including the title")

    for i, slide in enumerate(prs.slides, 1):
        words = []
        for sh in slide.shapes:
            left, top = Emu(sh.left).inches, Emu(sh.top).inches
            right = left + Emu(sh.width).inches
            bottom = top + Emu(sh.height).inches
            name = sh.name
            if left < -0.02 or top < -0.62 or right > SLIDE_W + 0.02:
                problems.append(
                    f"BOUNDS     slide {i}: {name} at ({left:.2f},{top:.2f}) "
                    f"runs to ({right:.2f},{bottom:.2f})")
            # The footer bar is template furniture; anything else under it is
            # content that will be sitting on top of the footer.
            if bottom > FOOTER_TOP and "Footer" not in name \
                    and "Rectangle" not in name and "Slide Number" not in name:
                problems.append(
                    f"FOOTER     slide {i}: {name} reaches {bottom:.2f}in, "
                    f"under the footer bar at {FOOTER_TOP}in")
            if sh.has_text_frame:
                words.append(sh.text_frame.text)
            # A table is a GraphicFrame and has no text_frame of its own. Its
            # cell text IS extractable from the file, so a screening tool sees
            # it -- missing it here reports keywords as absent when they are
            # sitting in the risk table.
            elif getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    for c in row.cells:
                        words.append(c.text)
        per_slide[i] = " ".join(words)

    for idx, needles in REQUIRED.items():
        text = per_slide.get(idx, "").lower()
        for needle in needles:
            if needle not in text:
                problems.append(f"SECTION    slide {idx}: the template asks "
                                f"for \"{needle}\" and it is not on the slide")

    everything = " ".join(per_slide.values()).lower()
    for needle in REQUIRED_ANYWHERE:
        if needle not in everything:
            problems.append(f"SECTION    the template asks for "
                            f"\"{needle}\" and it is nowhere in the deck")

    missing = [t for t in PS_TERMS
               if not re.search(re.escape(t.lower()), everything)]

    print(f"{DECK.name}: {len(prs.slides)} slides")
    for i in sorted(per_slide):
        print(f"  slide {i}: {len(per_slide[i].split()):>4} words")
    total = sum(len(v.split()) for v in per_slide.values())
    print(f"  total   : {total} words")

    print(f"\nProblem-statement terms present as text: "
          f"{len(PS_TERMS) - len(missing)}/{len(PS_TERMS)}")
    if missing:
        print("  MISSING: " + ", ".join(missing))
        problems += [f"KEYWORD    \"{m}\" appears nowhere in the deck text"
                     for m in missing]

    print()
    for p in problems:
        print(f"  {p}")
    print("ALL CHECKS PASS" if not problems else f"{len(problems)} PROBLEM(S)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
