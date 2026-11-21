================================================================================
TECHNICAL PRODUCT REQUIREMENTS DOCUMENT (PRD) — PART 4 of 4
SIH 2026 / DRDO IDEX Problem Statement 26054
DEFENCE HUMAN–MACHINE INTERFACE (HMI) STANDARD
for the Ground Control Station Digital Twin Console
================================================================================
Document Version: 1.0
Date: 27 August 2026
Classification: Internal Technical Document
Applies to: `layer5_viz/gcs_console` (GCS Console) and every operator-facing
            surface of the Digital Twin system, including PDF mission reports.
================================================================================

PURPOSE
-------
PRD Parts 1–3 specify *what* the system computes. This document specifies *how
that information is presented to a human being who may have to act on it in
seconds*, and it does so by binding the interface to published military and
airworthiness human-engineering standards rather than to contemporary web-design
fashion. Every rule below is traceable to a source in §1.

This is a compliance document. Requirements use SHALL / SHOULD / MAY in the
MIL-STD sense. A rule marked [SHALL] is not a style preference and must not be
overridden for visual effect.

================================================================================
TABLE OF CONTENTS — PART 4
================================================================================
1.  Normative references and how they were obtained
2.  Design philosophy — the six principles
3.  Colour standard (the single most-regulated aspect)
4.  Alerting model — MIL-STD-411F applied to engine health
5.  Typography and legibility
6.  Layout, grouping and information architecture
7.  Data integrity, staleness and failure annunciation
8.  Motion, flashing and attention management
9.  Interaction, controls and confirmation of critical actions
10. Role-based views (STANAG 4586 alignment)
11. Screen inventory and wireframes
12. Component library specification
13. Accessibility, colour-vision deficiency and NVIS considerations
14. Anti-patterns — explicitly forbidden
15. Verification checklist

================================================================================
1. NORMATIVE REFERENCES AND HOW THEY WERE OBTAINED
================================================================================

All primary sources below were retrieved and read in full during this project
(text extracted from the source PDFs); paragraph numbers quoted in this document
were verified against those documents, not recalled from memory.

  [R1] MIL-STD-1472H, "DoD Design Criteria Standard: Human Engineering",
       15 September 2020. Retrieved from everyspec.com (456 pp).
       Governs: colour meanings (Table XL), colour coding rules (5.17.25),
       brightness coding (5.17.26), flash coding (5.17.27), size coding
       (5.17.28), character height/stroke/width (5.4.7), system response times
       (Table V), touchscreen criteria (5.1.3.1), information grouping (5.17.17).

  [R2] MIL-STD-411F, "Design Criteria Standard: Aircrew Station Alerting
       Systems", 1997. Retrieved from cevians.com (24 pp).
       Governs: warning/caution/advisory definitions (3.13), colours (5.1.3.1,
       5.1.4.1, 5.1.5.1), integrated alert display behaviour (5.2), message
       syntax and prioritisation (5.2.5), overflow memory (5.2.5.3), minimum
       message duration (5.2.5.5), inhibit logic (5.2.6.2), maintenance record
       (5.2.10), audio master warning (5.3.1).

  [R3] FAA Human Factors Design Standard general-guidance compilation,
       Chapter 3.7 "Color" (Nov 2013 CHG 1), consolidating AC 25-11A/B
       §31.c(5), AC 23.1311-1C §22, TSO-C165/RTCA DO-257A §2.1.6,
       TSO-C113a/SAE AS8034B §4.3.3, AMC 25.1302 §5.4.2, 14 CFR 25.1322.
       Retrieved from hfcc.dot.gov.
       Governs: the recommended colour-per-function table, the ≤6 colour limit,
       forbidden colour pairs, redundant coding, chrominance separation.

  [R4] 14 CFR 25.1322 / 23.1322 — flight-deck alert colour law: red = warning,
       amber/yellow = caution, green = safe, advisory = any colour except red
       or green (and preferably not amber/yellow). Quoted via [R3].

  [R5] STANAG 4586 (Ed. 4), "Standard Interfaces of UAV Control System (UCS)
       for NATO UAV Interoperability". NATO STO educational note
       STO-EN-SCI-271-03. Governs: the CUCS / HCI / DLI / VSM functional
       decomposition and the five Levels of Interoperability (LOI 1–5) that our
       role model and fleet view align to.

  [R6] SAE ARP4102/7 "Electronic Displays" and its Appendix C "Electronic
       Display Symbology for Engine Displays" — referenced for engine-display
       symbology conventions. NOTE: this is a paywalled SAE document; it was
       NOT obtained. Where this PRD states an engine-display convention, the
       traceable source is [R3]'s consolidation of AC 25-11A, not ARP4102/7.
       Do not cite ARP4102/7 as a verified source in the pitch.

  [R7] Referenced-but-not-obtained, listed for the production hardening plan
       only: MIL-STD-3009 (NVIS lighting), MIL-L-85762A (NVIS compatibility),
       DEF STAN 00-250 (UK Human Factors for Defence Systems), DO-178C/DO-330.
       These are named as the *certification path*, never as evidence.

HONESTY RULE [SHALL]: In any presentation, the system is described as
"designed in conformance with" these standards. It has not been certified
against them by any authority, and no claim of certification shall be made.

================================================================================
2. DESIGN PHILOSOPHY — THE SIX PRINCIPLES
================================================================================

P1. DARK-CONSOLE, QUIET-WHEN-NORMAL.
    A healthy engine produces an almost featureless display. MIL-STD-411F 4.1.1a
    requires that the system "should not give audible and visible caution and
    warning alerts when all systems are operating normally" [R2]. Consequence:
    there is no green "everything is fine!" confetti, no decorative status
    badges, no animated hero numbers. Attention is a budget; normal operation
    spends none of it.

P2. THE DISPLAY IS AN INSTRUMENT, NOT A REPORT.
    The operator reads values, trends and limits — not prose. Numeric readouts
    are monospaced, fixed-width and fixed-position so that a changing digit is
    the only thing that moves. Nothing reflows while it is being read.

P3. COLOUR IS RESERVED, NOT DECORATIVE.
    Red and amber belong to the alerting system and to nothing else [R3, R4].
    A chart series, a brand accent or a "primary button" may not be red or
    amber. Extensive use of red/amber "diminishes the attention-getting
    characteristics of warnings and cautions" [R3].

P4. COLOUR IS NEVER THE ONLY CHANNEL.
    "Whenever color is used to code information, it shall be used redundantly
    with another means of coding" [R3, RTCA DO-256 2.1.3.6]. Every alert
    carries a shape/icon, a text legend and a position. The display must remain
    unambiguous in monochrome.

P5. UNCERTAINTY AND STALENESS ARE FIRST-CLASS DATA.
    Every prediction is shown with its confidence interval; every value carries
    an age. A value that has stopped updating is annunciated as invalid, never
    left frozen and plausible-looking. (See §7.)

P6. THE OPERATOR IS ACCOUNTABLE, SO THE SYSTEM IS EXPLAINABLE.
    Every alert must answer "why?" in one interaction, with the evidence that
    produced it (SHAP contributions, the residual, the rule that fired), and
    every acknowledgement is written to the audit log.

================================================================================
3. COLOUR STANDARD
================================================================================

3.1 Semantic colour set [SHALL]
--------------------------------
The console SHALL use exactly the following semantic colours. No other hue may
carry meaning. The ≤6 coding-colour rule of TSO-C165/RTCA DO-257A §2.1.6 [R3] is
respected: six meaning-bearing colours (red, amber, green, cyan, white, magenta)
plus neutral greys, which are not coding colours.

  TOKEN        ROLE                          SOURCE
  ───────────────────────────────────────────────────────────────────────────
  --alert-warn      WARNING (Level 5 / RED)      Aviation red. MIL-STD-411F
                    Hazard requiring immediate   5.1.3.1 [R2]; 14 CFR 25.1322
                    action.                      [R4]
  --alert-caut      CAUTION (Level 4 / ORANGE    Aviation yellow. MIL-STD-411F
                    and Level 3 / YELLOW)        5.1.4.1 [R2]; [R4]
                    Action required, not
                    immediate.
  --alert-advis     ADVISORY (Level 2 / BLUE)    MIL-STD-411F 5.2.5.4 permits a
                    Information; no action.      third colour, green preferred,
                                                 blue/white for non-flight-deck
                                                 stations [R2]. Green is taken
                                                 by "normal", so ADVISORY uses
                                                 cyan — allowed by 14 CFR
                                                 25.1322 ("any colour except red
                                                 or green") [R4] and by
                                                 MIL-STD-1472H Table XL, which
                                                 lists cyan → "Advisory" [R1].
  --state-normal    NORMAL / in-tolerance /      MIL-STD-1472H Table XL: green =
                    engaged mode (Level 1)       "Normal, Safe, In tolerance,
                                                 Ready, proceed" [R1]; [R3]
                                                 Table 3.7.1 "Engaged modes/
                                                 normal conditions: Green".
  --ink             Scales, labels, current      [R3] Table 3.7.1: "Scales and
                    values, primary text         associated figures: White";
                                                 "Current data, values: White"
                                                 (Colour Set 1).
  --ref-selected    Operator-selected targets,   [R3] Table 3.7.1: "Pilot
                    bugs, "fly-to"/setpoint      selectable references (bugs):
                    references, active plan      Magenta"; "Active route/flight
                                                 plan: Magenta" (Colour Set 1).
  --ink-dim         Divisor lines, units,        [R3] Table 3.7.1: "Divisor
  --ink-mute        inactive controls            lines, units and labels for
                                                 inactive soft buttons: Light
                                                 Gray"; MIL-STD-1472H Table XL:
                                                 grey = "Inactive or unavailable
                                                 options" [R1].
  --phys            Physics-model prediction     Not an alerting colour. Rendered
                    overlay (predicted CHT/EGT)  as a dashed neutral-grey line;
                                                 distinguished by LINE STYLE
                                                 first, colour second (P4).

3.2 Concrete values [SHALL]
----------------------------
Defined once in `layer5_viz/gcs_console/src/theme/tokens.css`. The console is
dark-primary; a high-ambient (daylight) palette is provided because MIL-STD-411F
5.2.3 requires readability "even in illumination up to 10,000 fc through the
aircraft windows" [R2].

  Dark console (default)
    --bg-void        #05070A     deepest background
    --bg-panel       #0B1018     panel surface
    --bg-raised      #121A25     raised surface / table header
    --line           #1E2A38     hairline separator
    --ink            #E8F0F8     primary text / current values (white)
    --ink-dim        #9BAABB     units, labels
    --ink-mute       #77889D     inactive / disabled
    --state-normal   #37D17A     green
    --alert-advis    #35C6E8     cyan — ADVISORY
    --alert-caut     #FFB302     aviation-yellow family — CAUTION
    --alert-caut-hi  #FF8C33     CAUTION, escalated (Level 4)
    --alert-warn     #FF3B30     aviation-red family — WARNING (LAMPS, BARS,
                                 ICONS AND STROKES ONLY — see below)
    --ref-selected   #E056C9     magenta — operator setpoints
    --phys           #8A9BB0     physics prediction overlay

    --alert-warn-ink   #FF8A82   WARNING as TEXT
    --ref-selected-ink #E78FD6   setpoint as TEXT

  Why two reds. §3.4a requires 7:1 on alert legends, and the certified
  aviation red reaches only 4.93:1 as text on --bg-raised. Lightening it far
  enough to pass turns it into coral, which is the wrong answer for the master
  warning lamp — whose entire job is to be the most saturated thing on the
  panel. §3.3c already resolves this ("a solid left status bar carries the
  saturated hue"); the split is now explicit in the tokens so it cannot be
  forgotten. It is also the human-factors answer rather than a concession to a
  contrast table: fully saturated red on near-black focuses at a different
  depth from the surrounding white text (longitudinal chromatic aberration),
  which is why avionics practice lightens red legends rather than deepening
  them. Not a §3.3e violation — that rule forbids shades of one colour carrying
  DIFFERENT meanings; these carry the same meaning in a different medium.

  High-ambient (day) palette
    --bg-void        #E9EDF2     --ink            #0A0F16
    --bg-panel       #F6F8FB     --ink-dim        #3D4A5A
    --bg-raised      #FFFFFF     --ink-mute       #5C6675
    --line           #C3CCD8     --phys           #55637A
    --state-normal   #065428     --alert-caut     #664300
    --alert-advis    #034F64     --alert-caut-hi  #802F00
    --alert-warn     #960B04     --ref-selected   #8C1479

  On a light background, deepening a hue keeps it recognisably that hue, so
  the day palette needs no separate text tokens and its -ink aliases point at
  the certified values.

  ALL OF THE ABOVE ARE MEASURED, NOT CHOSEN. §15 lists a CONTRAST TEST as
  automated; it did not exist, so the palette drifted — 28 failing pairs across
  the two palettes when `scripts/hmi_check.py` first measured them, the WARNING
  red among them in both. Every value here now meets §3.4a against all three
  surfaces of its own palette, and the check runs in CI.

  Rationale for the two caution tints: PRD Part 2 §9.5 defines five alert levels
  (GREEN/BLUE/YELLOW/ORANGE/RED) whereas MIL-STD-411F defines three urgency
  categories. Levels 3 and 4 are both CAUTION in 411F terms; they are separated
  by luminance/saturation within the same hue family, plus by icon and by
  position in the alert stack — never by hue alone. This is compliant with
  MIL-STD-1472H 5.17.26.2 (no more than two brightness levels, separated by at
  least a 2:1 ratio) [R1] and avoids introducing a seventh coding hue.

3.3 Forbidden colour usage [SHALL NOT]
---------------------------------------
  a. Red, orange or amber SHALL NOT be used for any non-alerting purpose —
     including chart series, focus rings, primary action buttons, logos or
     "accent" fills. [R3]: "limit the use of red, yellow, and amber for
     functions other than flightcrew alerting… Extensive use… diminishes the
     attention-getting characteristics of warnings and cautions."
  b. Green SHALL NOT be used for an advisory-level alert. [R4]: advisories may
     be "any color except red or green"; [R3]: "Green is usually used to
     indicate 'normal' conditions; therefore, it is not an appropriate color for
     an alert."
  c. The following adjacent colour pairs SHALL NOT be used (AC 25-11A
     31.c(5)(g) via [R3]): saturated red/blue, saturated red/green, saturated
     blue/green, saturated yellow/green, yellow-on-purple, yellow-on-green,
     yellow-on-white, magenta-on-green, green-on-white, blue-on-black,
     red-on-black.
       → Practical consequence: our red and amber alert text is NEVER placed
         directly on the near-black void. Alert rows use a raised surface
         (#121A25 or a 12%-alpha tint of the alert hue) so the pairing is
         red-on-dark-slate, not red-on-black, and a solid left status bar
         carries the saturated hue.
  d. Saturated colours SHALL NOT be used as large background fills
     (TSO-C113a/SAE AS8034B 4.3.3 note via [R3]: "saturated colors should be
     saved for smaller items such as symbols, icons, targets"). The only
     exception is the master WARNING bar, which is a deliberate, temporary,
     mission-critical annunciator (a direct analogue of the MIL-STD-411F
     master warning light, 5.1.3).
  e. Meaning SHALL NOT be carried by shades of one colour. [R3], AC 25-11A
     31.c(5)(i): "Requiring the flightcrew to discriminate between shades of
     the same color for distinct meaning is not recommended." (The Level-3/4
     tints of §3.2 are exempt only because they are additionally coded by icon,
     legend text and stack position.)
  f. Gradients, glassmorphism, neon glow, and colour-shifting animated fills
     SHALL NOT be used anywhere. They defeat chrominance separation and
     luminance-contrast requirements [R3, R1 5.17.25.16].

3.4 Contrast [SHALL]
---------------------
  a. MIL-STD-1472H 5.17.25.16.1: coloured symbols "shall differ from their
     background by not less than 100 ΔE (CIE L*u*v*)" [R1]. We adopt the
     practical proxy of WCAG 2.2 contrast ratio ≥ 4.5:1 for all body text and
     ≥ 7:1 for all numeric readouts and alert legends, and verify it in CI.
  b. MIL-STD-1472H 5.17.25.9: when colour coding is used, luminance shall be
     more than 10 cd/m² [R1] — a hardware/brightness setting, recorded in the
     RUNBOOK as a deployment requirement rather than enforced in software.
  c. A symbol SHALL NOT be placed on a background of equal luminance regardless
     of colour difference [R3].

================================================================================
4. ALERTING MODEL — MIL-STD-411F APPLIED TO ENGINE HEALTH
================================================================================

4.1 Category mapping [SHALL]
-----------------------------
PRD Part 2 §9.5's five levels map onto MIL-STD-411F's three urgency categories:

  PRD LEVEL        411F CATEGORY   COLOUR         MEANING (411F 3.13)
  ─────────────────────────────────────────────────────────────────────────────
  L5 RED           WARNING         red            "existence of a hazardous
                                                   condition requiring immediate
                                                   corrective action"
  L4 ORANGE        CAUTION         amber (hi)     "condition requiring immediate
  L3 YELLOW        CAUTION         amber          attention but not immediate
                                                   corrective action"
  L2 BLUE          ADVISORY        cyan           "a safe or normal
                                                   configuration… or information
                                                   for routine purposes"
  L1 GREEN         (no alert)      green          normal — annunciated only as
                                                   state, never as a message

4.2 Master WARNING / master CAUTION [SHALL]
--------------------------------------------
Per MIL-STD-411F 5.1.3 and 5.1.4 [R2]:
  a. A master WARNING annunciator SHALL be energised simultaneously with any
     individual warning-level alert, and a master CAUTION annunciator with any
     caution-level alert.
  b. Both SHALL be located in the operator's primary field of view — in our
     console, the fixed top bar, which is never scrolled away.
  c. Both SHALL provide push-to-reset: pressing it de-energises the *master*
     annunciator while the underlying individual alert remains displayed
     (411F 5.1.3.5 / 5.1.4.5). Reset SHALL NOT clear the alert itself.
  d. After reset, the master annunciator SHALL re-arm automatically so that a
     subsequent new alert re-energises it (411F 4.1.3.8).
  e. 411F 5.1.3.4 / 5.1.4.4 make the master steady-ON "unless a flashing
     presentation is approved by the acquiring activity". APPROVED for this
     console (23 Sep 2026, at the project owner's request: a steady lamp in a
     bar of steady text was being read past). While energised the master
     SHALL flash -- WARNING at 3 Hz, 50 % duty; CAUTION at 1 Hz, 70 % on
     (MIL-STD-1472H 5.17.27 visual alert table and 5.17.27.3: two rates, at
     least 2 Hz apart) -- each rate from one shared clock (§8.2d). The legend
     SHALL NOT flash (1472H 5.17.27.5): the lamp alternates filled/outlined
     with its words legible in both. Push-to-reset (c) de-energises it, so the
     flash ends on acknowledgement. Reduced-motion users get a steady lamp.

4.3 Alert list behaviour [SHALL]
---------------------------------
  a. Ordering: warnings at the top, then cautions, then advisories
     (411F 5.2.5.2). Within a category, most recent first, with the occurrence
     time displayed.
  b. Persistence: a warning SHALL remain displayed until the causative
     condition is corrected (411F 5.2.4.1). Cautions and advisories may be
     moved by the operator to a recall/overflow store (411F 5.2.4.2/5.2.4.3),
     never silently dismissed.
  c. Overflow: if active alerts exceed the visible capacity, an explicit
     "+N MORE" indicator SHALL be shown and the stored alerts SHALL be
     recallable (411F 5.2.5.3). New alerts displace lower-criticality ones,
     which move to overflow — never the reverse.
  d. Minimum display time: any warning or caution SHALL remain visible for at
     least 3 seconds even if the condition self-clears (411F 5.2.5.5). This is
     implemented as a per-alert `min_display_until` timestamp.
  e. Precedence: warning presentation SHALL take precedence over caution,
     advisory and routine display information (411F 5.2.4.1) — in layout terms,
     the warning region may overlay non-critical panels.

4.4 Message syntax [SHALL]
---------------------------
411F 5.2.5.1: messages "shall concisely convey the nature of the problem and the
specific subsystem or location." Our standard syntax:

    <SUBSYSTEM> <CONDITION> [<LOCATION>]        ≤ 24 characters, upper case
    e.g.  CHT HIGH CYL 3
          OIL PRESS LOW
          COOLING DEGRADED
          VIB BEARING BPFO

  a. The legend line SHALL be upper case, ≤24 characters, and SHALL NOT contain
     punctuation or sentence case.
  b. A secondary line MAY carry the plain-language advisory and the time-to-act
     (from PRD Part 2 §15.4), in sentence case.
  c. Legends SHALL NOT flash (MIL-STD-1472H 5.17.27.5: "Characters that must be
     read shall not flash") [R1].

4.5 Inhibit logic [SHOULD]
---------------------------
411F 5.2.6.2 [R2]: non-critical messages should be inhibited during critical
phases and multiple-failure situations. Implemented as:
  a. Ground/pre-start phase inhibits cold-engine cautions (low oil temp, low
     CHT) until the warm-up criterion in `configs/thresholds.yaml` is met.
  b. An active WARNING inhibits new ADVISORY-level messages for its duration.
  c. Every inhibit is logged and is visible on an "INHIBITS ACTIVE" indicator —
     an inhibit that the operator cannot see is a defect.

4.6 Maintenance record [SHALL]
-------------------------------
411F 5.2.10 [R2]: all warning and caution messages SHALL be recorded to
non-volatile storage for maintenance; advisory messages SHALL NOT be. Recording
SHALL be inhibited during the "on ground" pre-start condition, and any alert
still active at the ground→air transition SHALL then be recorded. Implemented in
`layer4_core/storage.py::AlertRecorder`.

4.7 Audio [SHALL]
------------------
PRD Part 2 §9.5 specifies audio per level. MIL-STD-411F 5.3.1 specifies the
non-verbal master warning tone: "fundamental audio output frequency shall sweep
from 700 to 1,700 Hz in 0.85 seconds… interruption interval shall be 0.12
seconds", repeating until de-energised [R2]. The console synthesises exactly this
via WebAudio for WARNING (layer5_viz/gcs_console/src/lib/audio.ts), repeating
until MSTR WARN is reset or the warning clears. CAUTION is a double 1 kHz pip
repeated every 5 s until MSTR CAUT is reset or the caution clears. (PRD Part 2
§9.5 specified a single beep, repeated every 30 s at Level 4; in use a caution
raised while the operator looked elsewhere was one beep and then silence, and
was missed. A tone now stops only when someone has acknowledged it.) Audio
SHALL be mutable, the mute state SHALL be visibly annunciated, and mute SHALL
NOT persist across a new WARNING.

================================================================================
5. TYPOGRAPHY AND LEGIBILITY
================================================================================

5.1 Character size [SHALL]
---------------------------
MIL-STD-1472H 5.4.7.1 [R1]: character height should subtend ≥ 15 minutes of arc
(viewing distance × 0.004), with 20 minutes (× 0.006) preferred. For colour
symbols requiring accurate colour perception, 5.17.25.14 requires ≥ 20 minutes
of arc [R1].

  Design viewing distance for a seated GCS console operator: 700 mm.
    15 arcmin → 700 × 0.004 = 2.8 mm   (absolute minimum)
    20 arcmin → 700 × 0.006 = 4.2 mm   (required here, since all coded text is
                                        colour-coded → 5.17.25.14 applies)

  At a typical 96 dpi console display (1 mm ≈ 3.78 px):
    MINIMUM any text          4.2 mm  →  16 px      [SHALL]
    Numeric readouts (primary) 8.0 mm  →  30 px      [SHALL]
    Alert legends             5.5 mm  →  21 px      [SHALL]
    Labels / units            4.2 mm  →  16 px      [SHALL]

  There is NO 12 px or 14 px text anywhere in this console. MIL-STD-1472H
  5.4.7.2 gives the same answer dimensionally: ~5 mm at 710 mm viewing
  distance [R1].

5.2 Typeface [SHALL]
---------------------
  a. All numeric data SHALL be rendered in a monospaced face with tabular
     figures and unambiguous 0/O and 1/l/I glyphs. Selected: **JetBrains Mono**
     (slashed zero), with `ui-monospace, "Cascadia Mono", Consolas` fallback.
  b. Labels and prose use a neutral grotesque: **Inter**, fallback
     `"Segoe UI", system-ui`.
  c. Width-to-height ratio of 3:5 for numerals and letters (5.4.7.5.1) and
     stroke width of 1/7 to 1/8 of height for light-on-dark (5.4.7.4.2) [R1]
     are satisfied by selecting the *Medium* weight for readouts on the dark
     console; Regular is too thin and Bold too heavy at these sizes.
  d. `font-variant-numeric: tabular-nums` SHALL be set on every numeric
     element so digits do not shift horizontally as values change (P2).

5.3 Units and precision [SHALL]
--------------------------------
  a. Every numeric value SHALL display its unit, in `--ink-dim`, at a smaller
     size, positioned consistently to the right of the value.
  b. Displayed precision SHALL match sensor resolution from PRD Part 1 §3.1 and
     no further: RPM 1 rpm (integer), CHT/EGT 0.1 °C, oil pressure 0.1 psi,
     oil temperature 0.1 °C, fuel flow 0.01 L/hr, vibration 0.01 m/s²,
     battery 0.01 V, current 0.1 A, injection timing 0.1 °BTDC.
     Rendering more digits than the sensor produces is a falsification of
     accuracy and is a defect.
  c. Health indices are displayed as 0–100 % with one decimal; RUL in flight
     hours with one decimal, always accompanied by its interval.

================================================================================
6. LAYOUT, GROUPING AND INFORMATION ARCHITECTURE
================================================================================

6.1 Grouping rules [SHALL]
---------------------------
MIL-STD-1472H 5.17.17 [R1]: information shall be ordered by (a) natural
sequence, (b) criticality/importance, (c) function, (d) frequency of use.
Applied:

  Zone A — MASTER ALERT BAR        (top, fixed, full width, never scrolls)
           Master WARNING / master CAUTION annunciators + reset, mission clock
           (UTC), link status, twin id, inhibit indicator, audio state.
           Justification: 411F 5.2.3 requires warning/caution/advisory messages
           within the operator's 30° forward cone on a single display surface.

  Zone B — PRIMARY ENGINE STRIP     (below A, fixed)
           The four highest-criticality parameters, always visible on every
           page: RPM, CHT (max of 4), EGT (max of 4), OIL PRESS.
           Justification: criticality ordering, 5.17.17.2 [R1]; these four are
           the precursors of every FAILURE MODE in PRD Part 1 §5.3.

  Zone C — WORK AREA                (page-specific)

  Zone D — ALERT STACK              (right rail, fixed, ordered per §4.3)

  Zone E — STATUS FOOTER            (bottom) — data source, ingest rate,
           pipeline latency (median/p95), model versions, storage state.

6.2 Spatial stability [SHALL]
------------------------------
  a. A parameter SHALL occupy the same screen position on every page and in
     every state. Values change; positions do not.
  b. Panels SHALL NOT resize, reorder or animate in response to data.
  c. Alerts SHALL NOT appear as transient toasts that self-dismiss. Every alert
     lands in the alert stack and stays until §4.3(b) is satisfied.
  d. No modal dialog may cover Zone A or Zone B.

6.3 Density [SHOULD]
---------------------
The console targets a 1920×1080 operator display at 100 % scale, and must remain
usable at 1366×768 (a common ruggedised panel resolution) by collapsing Zone D
to a badge count, never by shrinking text below §5.1 minima.

================================================================================
7. DATA INTEGRITY, STALENESS AND FAILURE ANNUNCIATION
================================================================================

This section exists because the most dangerous failure mode of a monitoring
console is a plausible-looking frozen number.

7.1 Value states [SHALL]
-------------------------
Every displayed value SHALL be in exactly one of five states, each with a
distinct, non-colour-dependent rendering:

  VALID      value shown normally.
  STALE      age > 3 × expected update interval. The value SHALL be dimmed to
             `--ink-mute` AND overlaid with a diagonal-hatch mark AND the age
             shown ("4.2 s"). It SHALL NOT be shown as if current.
  INVALID    failed the range or rate-of-change plausibility check of PRD
             Part 1 §8.3. Rendered as amber dashes `- - -` in place of digits,
             with an `INVALID` legend. Never a zero, never a last-good value.
  MISSING    no data ever received. Rendered as `— — —` in `--ink-mute`.
  SUSPECT    passes plausibility but the sensor-drift estimator (PRD Part 1
             §8.4) reports bias > 2 % FS. Value shown with a small `Δ` marker
             and its estimated bias on hover/focus.

7.2 Removal of misleading data [SHALL]
---------------------------------------
When a computed output depends on an INVALID input, the output SHALL be removed
and annunciated rather than computed from a substituted value. Example: if
fuel flow is INVALID, BSFC and FSHI are shown as `INVALID — fuel flow`, not
computed from the last-good flow.

7.3 Link loss [SHALL]
----------------------
PRD Part 3 §21.4 defines edge offline mode. The console SHALL annunciate:
  a. `LINK: DEGRADED` (cyan advisory) when telemetry gaps exceed 2 s.
  b. `LINK: LOST — EDGE AUTONOMOUS` (amber caution) after 5 s, together with
     the local buffer depth and the time since last sync.
  c. On restoration, a `SYNC` progress indicator and an explicit statement of
     the recovered time span. Back-filled history SHALL be visually
     distinguishable from live data on trend charts (lighter stroke + a
     "backfilled" band label) so the operator never mistakes replayed history
     for live telemetry.

7.4 Model confidence [SHALL]
-----------------------------
  a. Every RUL figure SHALL be displayed with its 95 % interval; the bare
     number is forbidden. Rendering: `47.5 h` with `42.3 – 52.7` beneath in
     `--ink-dim`, plus a horizontal interval bar.
  b. When AI confidence falls below the configured floor, the console SHALL
     display `RULE-BASED FALLBACK ACTIVE` (advisory) — implementing the
     graceful-degradation requirement of PRD Part 0 §0.11 and Part 3 RISK 2.
  c. Simulated, predicted and measured quantities SHALL be visually distinct:
     measured = solid `--ink`; physics-predicted = dashed `--phys`;
     AI-projected = dotted with a confidence band.

================================================================================
8. MOTION, FLASHING AND ATTENTION MANAGEMENT
================================================================================

8.1 Motion budget [SHALL]
--------------------------
  a. MIL-STD-1472H 5.2.1.1.3 [R1]: graphic display items shall not move faster
     than 60°/s of visual angle, 20°/s preferred. Practically: no element
     traverses more than ~250 px in under 1 s.
  b. Decorative animation is forbidden: no entrance transitions, parallax,
     skeleton shimmer, spinning loaders, count-up animations, or hover lifts.
  c. Permitted motion is limited to: (i) trend traces advancing in time,
     (ii) a needle/bar moving to a new value with ≤150 ms linear easing,
     (iii) alert-stack insertion (a 100 ms opacity step, no slide),
     (iv) the compliant flash of §8.2.
  d. `prefers-reduced-motion` SHALL disable (ii) and (iii) entirely.

8.2 Flash coding [SHALL]
-------------------------
MIL-STD-1472H 5.17.27 [R1] and MIL-STD-411F 4.1.3.5 [R2]:
  a. Flashing SHALL be used only for mission-critical events (1472H 5.17.27.1)
     — in this system: a *new, unacknowledged* WARNING-level alert row, and
     an energised master annunciator (§4.2e, approved 23 Sep 2026).
  b. No more than two flash rates (5.17.27.3); we use two, 2 Hz apart:
     **3 Hz** for warnings (row and master), which satisfies both 1472H
     (≥0.8 Hz, ≤5.0 Hz) and 411F 4.1.3.5 (3–5 Hz); **1 Hz at 70 % on** for
     the master CAUTION only (1472H caution: ≤2 Hz, 70 % on).
  c. Duty cycle 50 % (5.17.27.2); ON time equal to OFF time (411F 4.1.3.5).
  d. Simultaneously flashing items SHALL be synchronised (5.17.27.4,
     411F 4.1.3.5) — implemented from a single shared clock, not per-component
     timers.
  e. Text SHALL NOT flash (5.17.27.5). The flashing element is the alert row's
     status bar / background tint, never the legend.
  f. Acknowledgement SHALL stop the flash while the alert remains displayed
     (5.17.27.6). This is the master-warning reset of §4.2(c).
  g. Only a small area of the display flashes at any time (5.17.27.7).

8.3 Refresh rate [SHALL]
-------------------------
PRD Part 1 §2.2 requires dashboard refresh ≤ 2 s; PRD Part 3 §26.1 targets < 2 s
(acceptable < 5 s). This console streams over WebSocket and renders at the
telemetry rate (10 Hz) for Zone B, throttled to 4 Hz for trend charts and 1 Hz
for derived indices — well inside the requirement, while keeping the render
budget low enough to avoid dropped frames on GCS-class hardware.

================================================================================
9. INTERACTION, CONTROLS AND CONFIRMATION
================================================================================

9.1 Response time [SHALL]
--------------------------
MIL-STD-1472H Table V [R1] governs; the binding entries for this console:
    key press → positive response ........... 0.1 s
    XY entry → visual verification .......... 0.2 s
    error feedback .......................... 0.2 s
    local update (menu/panel from buffer) ... 0.5 s
    host update (rescale existing view) ..... 2.0 s
    simple inquiry .......................... 2.0 s
    complex inquiry (e.g. what-if sim) ...... 10 s
5.1.2.1.6.4.3: if a response will exceed 1 s, the user SHALL be shown a
processing indication. 5.1.2.1.6.3: every input SHALL produce a perceptible
response.

9.2 Critical actions [SHALL]
-----------------------------
MIL-STD-1472H 5.1.3.1.7 [R1]: a control used for a critical task SHALL require
an additional confirmatory action. Critical actions in this system:
    • Acknowledge / reset a WARNING-level alert
    • Approve a mission with an active Go/No-Go NO-GO verdict
    • Change any threshold in `configs/thresholds.yaml` at runtime
    • Ground / return-to-service a twin
    • Trigger the simulated automatic power reduction
Each SHALL use a two-step confirm with an explicit statement of consequence,
SHALL NOT be the default focus target, and SHALL be written to the audit log
with user, UTC and change hash (PRD Part 1 §2.5).

9.3 Touch [SHALL, when touch is enabled]
-----------------------------------------
MIL-STD-1472H 5.1.3.1 [R1]:
  a. Minimum actuation area 13 mm; preferred 19 mm (figure 3). At 96 dpi that
     is a **minimum 48 px, preferred 72 px** touch target.
  b. Touch SHALL NOT be the sole input device for a mission- or safety-critical
     function (5.1.3.1.1.3) — every critical action also has a keyboard route.
  c. Display response latency ≤ 100 ms (5.1.3.1.4).
  d. A positive indication of actuation SHALL be provided (5.1.3.1.3).
  e. Colour coding on targets SHALL be redundant with another form
     (5.1.3.1.16).

9.4 Keyboard [SHALL]
---------------------
Full keyboard operability, visible focus ring (2 px, `--ink`, never red/amber
per §3.3a), logical tab order following Zone A→B→C→D, and documented shortcuts:
`M` master reset, `A` acknowledge selected alert, `1–7` page switch,
`Space` replay play/pause, `?` shortcut help.

================================================================================
10. ROLE-BASED VIEWS (STANAG 4586 ALIGNMENT)
================================================================================

PRD Part 3 §19.5 defines four roles; PRD Part 1 §2.5 defines the same four as
RBAC roles. STANAG 4586 [R5] separates the Core UCS (CUCS) from the Human
Computer Interface (HCI) and defines Levels of Interoperability LOI 1–5. Our
console is an HCI over a CUCS-analogous twin core, and is scoped to **LOI 1–2
semantics**: receipt and display of telemetry and derived products. It issues no
vehicle or payload commands (LOI 3–5), which is the correct and honest scope for
a health-monitoring twin — state this explicitly rather than implying flight
control authority.

  ROLE_OPERATOR     Zones A,B + Engine, Health, Alerts, Replay (read-only).
                    May acknowledge alerts. No thresholds, no simulation.
  ROLE_ENGINEER     + Physics (residuals, degradation factors), Prognostics
                    (SHAP, model versions), Simulation/what-if. May edit
                    simulation parameters; threshold edits require confirm.
  ROLE_MAINTENANCE  + Advisory queue, maintenance action library, parts
                    forecast, mission reports. May schedule maintenance.
  ROLE_COMMANDER    + Fleet view, mission approval, user management,
                    full audit log.

Rules [SHALL]:
  a. The UI SHALL NOT render controls the role cannot use. Hiding is preferred
     to disabling for authority-bearing actions, so the operator's mental model
     of their own authority stays accurate.
  b. The active role SHALL be displayed persistently in Zone A.
  c. Authorisation SHALL be enforced server-side regardless of UI state; the UI
     is a convenience, never the security boundary.

================================================================================
11. SCREEN INVENTORY AND WIREFRAMES
================================================================================

  1. ENGINE      — 9-parameter instrument cluster; per-cylinder CHT/EGT bars
                   with spread indicator; measured-vs-physics overlay.
  2. HEALTH      — CHI + THI/MHI/EHI/CombHI; six degradation factors with
                   trend arrows; CUSUM onset marker.
  3. PROGNOSTICS — RUL with CI band, physics-vs-data-driven decomposition,
                   SHAP contribution chart, plain-language advisory.
  4. SIMULATION  — environmental condition selector (high altitude, endurance,
                   hot-weather, rapid throttle, maritime, cold), what-if inputs,
                   predicted envelopes, Go/No-Go verdict with reasons.
  5. REPLAY      — transport (1×/10×/100×/event), scrubber with event markers,
                   recomputed residuals, annotations.
  6. FLEET       — twin roster sorted by RUL ascending, readiness summary.
  7. AUDIT       — append-only log view (Commander only).

Wireframe — ENGINE page (1920×1080):

  ┌────────────────────────────────────────────────────────────────────────┐
  │ A │ ⬤ MSTR WARN  ⬤ MSTR CAUT │ UAV-ENG-001 │ 14:22:07Z │ LINK OK │ 🔇 │
  ├────────────────────────────────────────────────────────────────────────┤
  │ B │  RPM 5 480  │ CHT 198.4 °C │ EGT 664.1 °C │ OIL P 54.2 psi        │
  ├──────────────────────────────────────────────────┬─────────────────────┤
  │ C  ┌── CYLINDER TEMPS ─────────────────────────┐ │ D  ALERT STACK      │
  │    │ CHT  1▮▮▮▮ 2▮▮▮▮ 3▮▮▮▮▮ 4▮▮▮▮  spread 9 │ │ ▌WARN CHT HIGH CYL3│
  │    │ EGT  1▮▮▮▮ 2▮▮▮▮ 3▮▮▮▮  4▮▮▮▮  spread 14│ │ ▌CAUT COOLING DEGR │
  │    └───────────────────────────────────────────┘ │ ▌ADVS BSFC TREND   │
  │    ┌── TREND (measured ── / physics ─ ─) ──────┐ │                     │
  │    │                                           │ │  +2 MORE            │
  │    └───────────────────────────────────────────┘ │                     │
  ├──────────────────────────────────────────────────┴─────────────────────┤
  │ E │ SRC vcan0 │ 10.0 Hz │ p50 62 ms  p95 148 ms │ MDL v1.2 │ REC ●     │
  └────────────────────────────────────────────────────────────────────────┘

================================================================================
12. COMPONENT LIBRARY SPECIFICATION
================================================================================

Each component below is a required implementation artifact under
`layer5_viz/gcs_console/src/components/`.

  Readout          Label + tabular value + unit + value-state rendering (§7.1).
  BarGauge         Horizontal bar with normal band, caution band, warning band
                   drawn as *zones with tick marks and printed limits*, so the
                   limits are legible without colour (P4).
  ParamTile        Readout + BarGauge + trend sparkline + limit annunciation.
  CylinderArray    4-element per-cylinder bar set with spread readout and the
                   spread limit printed.
  TrendChart       Time series; solid measured, dashed physics, dotted
                   projection with band; alert events as vertical rules with
                   category glyphs; no gradient fills, no smoothing that hides
                   a spike (step or linear interpolation only).
  AlertRow         Category glyph + saturated left status bar + legend (≤24 ch,
                   upper) + secondary advisory + timestamp + ACK control.
  MasterAnnunciator Steady-ON master WARNING / CAUTION with push-to-reset,
                   re-arm, and the §8.2 synchronised flash for unacknowledged
                   warnings.
  HealthIndexDial  0–100 % arc with printed band boundaries (per PRD Part 2
                   §9.3 CHI interpretation table) and numeric centre.
  RULIndicator     Value + interval bar + interval numerals + source split
                   (physics/data) + fallback annunciation.
  ShapContribution Signed horizontal bar chart; positive contributions toward
                   the fault, negative toward normal; feature names spelled out
                   in engineering terms, not model feature names.
  ConfirmAction    Two-step critical-action control per §9.2.
  ValueState       The shared renderer implementing §7.1 for all five states.

Every component SHALL be built to render correctly with `--alert-*` tokens
replaced by greys (the monochrome test of §15).

================================================================================
13. ACCESSIBILITY, COLOUR-VISION DEFICIENCY, NVIS
================================================================================

  a. MIL-STD-1472H 5.17.25.10/.11 [R1]: if the user population may include
     colour-blind users, non-confusable colours shall be used, and where that
     is impossible, redundant coding SHALL be used. Approximately 8 % of men
     have a colour-vision deficiency [R3]. Our alert set is therefore coded by
     hue + glyph + legend + position + (for warnings) flash.
  b. MIL-STD-1472H 5.17.25.12 [R1]: laser-protective eyewear can induce
     selective colour blindness, so colour SHALL NOT be the only coding channel
     in any operational system — an independent argument for P4.
  c. High colour confusion exists between magenta/red, magenta/purple,
     yellow/amber and cyan/green [R3, DO-257A App. E]. Consequences honoured in
     §3.1: magenta is used only for operator setpoints (never near alert
     elements), and cyan advisories are always accompanied by the `ADVS` legend
     to separate them from green normal states.
  d. NVIS: night-vision-compatible operation (MIL-L-85762A / MIL-STD-3009)
     requires filtered emission and is a *hardware and lighting* problem, not a
     CSS problem. The console provides a `NIGHT` brightness profile that caps
     luminance and removes blue-heavy hues; full NVIS compatibility is recorded
     in the production hardening plan, NOT claimed as implemented. [R7]

================================================================================
14. ANTI-PATTERNS — EXPLICITLY FORBIDDEN
================================================================================

The following are common in contemporary dashboard UI and are defects here.
This list exists so that "make it look modern" can never override §3–§9.

  ✗ Purple/indigo/violet gradient headers or "hero" panels.
  ✗ Glassmorphism, blur backdrops, neon glow, drop shadows used for depth
    theatre.
  ✗ Emoji as status icons.
  ✗ Rounded "pill" badges in saturated colour used decoratively.
  ✗ Toast notifications that auto-dismiss (violates §4.3b and 411F 5.2.5.5).
  ✗ Count-up/odometer animation on numeric values (violates P2 and §8.1b).
  ✗ Skeleton shimmer loaders (violates §8.1b; use a static "ACQUIRING" state).
  ✗ Chart libraries' default rainbow categorical palettes (violate §3.3a).
  ✗ Colour-only legends and colour-only status dots.
  ✗ Text below 16 px anywhere (violates §5.1).
  ✗ Green used to mean "advisory information" (violates §3.3b).
  ✗ Red or amber used for a focus ring, link, or primary button (§3.3a).
  ✗ A frozen last-good value displayed as if live (§7.1).
  ✗ A bare RUL number with no interval (§7.4a).
  ✗ Marketing copy, taglines or product branding in the operational view.

================================================================================
15. VERIFICATION CHECKLIST
================================================================================

Run before every demo and in CI where automatable.

  [ ] MONOCHROME TEST — with all `--alert-*` tokens set to greys, every alert
      remains unambiguously identifiable by glyph, legend and position. [R3
      redundancy requirement; CAP 708 method: design monochrome first.]
  [ ] CONTRAST TEST — automated: every text/background pair ≥ 4.5:1, numerics
      and alert legends ≥ 7:1. (§3.4a)
  [ ] TYPE TEST — automated: no rendered font-size below 16 px. (§5.1)
  [ ] RESERVED-COLOUR TEST — automated: grep the built CSS/JS for the red and
      amber token values outside alert components. (§3.3a)
  [ ] FLASH TEST — exactly one flashing element class, 3 Hz, 50 % duty,
      synchronised, stops on acknowledge, never on text. (§8.2)
  [ ] MASTER RESET TEST — reset extinguishes the master annunciator, leaves the
      individual alert, and re-arms for the next event. (§4.2c,d)
  [ ] 3-SECOND TEST — inject a 200 ms transient caution; it must remain visible
      ≥ 3 s. (§4.3d)
  [ ] STALE TEST — stop the telemetry feed; within 3 update intervals every
      value must render STALE with an age, and link status must escalate. (§7)
  [ ] INVALID TEST — inject an out-of-range CHT; the value must render as amber
      dashes and every dependent computed value must annunciate INVALID. (§7.2)
  [ ] OVERFLOW TEST — raise more alerts than fit; "+N MORE" appears and stored
      alerts are recallable. (§4.3c)
  [ ] ROLE TEST — log in as each of the four roles; unauthorised controls are
      absent, and the API rejects the call even if the control is forced. (§10)
  [ ] KEYBOARD TEST — every function reachable without a pointer, focus always
      visible. (§9.4)
  [ ] REDUCED-MOTION TEST — with `prefers-reduced-motion`, no element animates
      except the compliant warning flash. (§8.1d)

================================================================================
END OF PRD PART 4
================================================================================
