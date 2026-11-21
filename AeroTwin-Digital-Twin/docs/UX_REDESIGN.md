# Console redesign: research, audit, and specification

Status: **built, awaiting review** — committed locally, not pushed. Section 10 records what was built and measured.

This document is the plan the console redesign is built to. It starts from
how the world's operational and defence interfaces are designed, measures the
current console against them, and specifies the new one. It does not relax
anything in `PRD_Part4_Defence_HMI_Standard.md` (type floor, colour meaning,
flash, zones) or `WHO_READS_THIS_SCREEN.md` (who is addressed by what); it
applies them more strictly.

---

## 1. What the best operational interfaces do

| Source | What it is | The rule we take |
|---|---|---|
| **Airbus "dark cockpit"** (A310 onward) | Flight deck philosophy | When everything is normal, the panel is dark. Light appears only for what needs attention. |
| **Honeywell / ASM Consortium** (Experion, *Effective Operator Display Design*) | Process-control HMI research | Grey is normal; colour appears only for abnormal conditions. A four-level display hierarchy. Operators needing ten or more screens is evidence of poor design. No pop-ups over the process. |
| **ISA-101 High-Performance HMI** | Industrial standard | Level 1 overview → Level 2 unit → Level 3 detail → Level 4 diagnostics. Each level answers one question. You drill down without re-orienting. |
| **Honeywell Anthem** flight deck | Aerospace HMI | Configure by mission and phase of flight. Tasks presented in "what's next" order, with the fewest touches for the key task. |
| **F-35 panoramic display** | Fighter cockpit | Pilot-selectable portal layouts by mission phase; show what the phase needs, not everything. |
| **AFRL Vigilant Spirit** (multi-UAV control station) | USAF research GCS | Include only what preflight, the mission objective and emergencies need. Vehicle calibration and engineering detail move to a separate engineering interface. |
| **Astro UXDS** (US Space Force ground systems) | Design system | One global status bar for global things only (app name, navigation tabs, clock, monitoring, actions). A single status vocabulary where every status symbol is colour plus shape, and an aggregate takes the highest. An application state tag (LIVE / TRAINING / SIMULATION) so no one commands a live asset by mistake. Don't add colours. 4 px spacing system, 16 px base type. |
| **Palantir Blueprint / Gotham** | Defence analytics UI | Built for data-dense desktop interfaces. Medium-high density that stays structured: sections by spacing and background, low radii, crisp boundaries. Intent colours used only with meaning. Interfaces "designed for decisions, monitoring and action". |
| **Palantir Maven Smart System** | US DoD targeting workflow | The workflow is on the screen: items move across a board of columns, one per stage, from observation to action. |
| **Anduril Lattice** | C2 platform | One pane of glass. The system presents decisions at key moments rather than streams to watch. |
| **Endsley situation awareness** | Human factors theory | Design for perception, then comprehension, then projection. The twin's RUL and Go/No-Go are projection, so they sit next to the thing they project. |
| **ISA-18.2 / EEMUA 191** | Alarm management | Every alarm carries a response. Aim for under one alarm per 10 minutes at steady state, and no chattering alarms. |

Sources: Airbus dark cockpit ([Simple Flying](https://simpleflying.com/airbus-boeing-cockpit-philosophies/), [Avia Pro](https://aviaproconsulting.com/article/post/engineering-spotlight-the-ergonomics-of-annunciation-%E2%80%93-airbus-lights-out-vs-boeing-quiet-and-dark)); ASM grey backgrounds ([Honeywell ASM paper](https://process.honeywell.com/content/dam/process/en/documents/document-lists/doc_asm-consortium/white-papers/February%2028%202011%20-%20Why%20Gray%20Backgrounds%20for%20DCS%20Operating%20Displays.pdf)); ISA-101 levels ([Yokogawa](https://www.yokogawa.com/us/library/resources/media-publications/isa-101-toward-a-more-effective-hmi-strategy/), [Malisko](https://malisko.com/isa-101/)); Honeywell Anthem ([Honeywell Aerospace](https://aerospace.honeywell.com/us/en/about-us/blogs/four-things-that-make-anthem-different)); F-35 PCD ([SLD](https://sldinfo.com/2012/04/the-f-35-cockpit-enabling-the-pilot-as-a-tactical-decision-maker/)); AFRL VSCS ([Applied Nav](https://appliednav.com/vigilant-spirit/), [DTIC](https://apps.dtic.mil/sti/pdfs/ADA594380.pdf)); Astro UXDS ([status system](https://www.astrouxds.com/patterns/status-system/), [global status bar](https://www.astrouxds.com/components/global-status-bar/), [application state](https://www.astrouxds.com/components/application-state/)); Blueprint ([GitHub](https://github.com/palantir/blueprint), [Palantir blog](https://blog.palantir.com/scaling-product-design-with-blueprint-25492827bb4a)); Maven Smart System ([Spatial Intelligence](https://www.spatialintelligence.ai/p/inside-palantirs-maven-smart-system), [CSIS](https://www.csis.org/analysis/what-maven-smart-system-and-what-does-it-do)); Anduril Lattice ([Anduril](https://www.anduril.com/lattice/command-and-control)); Endsley SA ([NCBI](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7287818/)).

## 2. What the current console does (measured, 1920 × 1080)

| Role | Sidebar pages | Words on the busiest screen | Buttons on screen |
|---|---|---|---|
| Operator | 7 | 293 | 16 |
| Maintainer | 9 | 353 | 22 |
| Engineer | 14 | 337 | 27 |
| Commander | **19** | **400** | **32** |

Defects found in the audit:

1. **The HEALTH page crashes the whole console to a blank screen**, for every
   role, whenever the aircraft on the station is parked (a null health value
   reaches `.toFixed`). The pipeline is unaffected; the display is gone.
2. Every page has the same heavy frame: a 224 px sidebar, a two-row header,
   a live engine strip showing 0 rpm for a parked aircraft, a 300 px alert
   rail that is empty most of the time, and a developer footer (frames,
   p95 latency) shown to every role.
3. Every panel is a bordered box with an uppercase, letter-spaced title and a
   MORE button. The dashboard has nine of them. When the engine is parked,
   six say "not available", "collecting data" or "not yet".
4. Colour is spent on normal: green readouts and green chips everywhere, so a
   real caution has less contrast against the page than it should.
5. The commander sees every page there is (19), including simulation, test
   rig and fault injection, which are not a commander's job.
6. Forms and confirmations use browser `prompt()`/`confirm()` pop-ups; long
   forms expand inside cards and push content around.
7. "Waiting on you" is a panel on four different pages, in four positions.

## 3. Principles for the new console

1. **Quiet when normal.** Neutral greys for everything normal. Colour means
   status and only status (Airbus, ASM, Astro). A healthy screen has almost
   no colour; a problem is the brightest thing on it.
2. **One status vocabulary.** Six statuses, each a shape plus a colour plus a
   word (Astro). OFF (dash), STANDBY (ring), NORMAL (dot), ADVISORY (dot),
   CAUTION (triangle), WARNING (square). Aircraft states, missions, alerts and
   checks all use it. An aggregate takes the highest.
3. **Each role sees its job, and only its job** (AFRL VSCS). At most five
   destinations per role, named for the job ("Mission", "Fleet",
   "Review"), not for the data.
4. **Level 1 → Level 4** (ISA-101). Each role's home is its Level 1: the one
   screen that answers "is anything wrong, and what do I do next?". Detail is
   one click down, inside the same workspace, via tabs.
5. **What's next, first** (Anthem, Maven). Every home leads with the next
   action. One primary button per state. Workflow is shown as stages.
6. **Drawers, not pop-ups** (ASM: no pop-ups over the process; Part 4 s6.2d:
   nothing covers Zones A/B). Secondary tasks (plan, allot, rectify,
   disposition) open in a side drawer inside the work area.
7. **Structure by space, not boxes** (Blueprint). Sections are separated by
   whitespace and a surface tone. Titles are sentence-case, 18 px. Uppercase
   is kept for data labels only.
8. **Every number with its limit, every alert with its action**
   (WHO_READS_THIS_SCREEN R4/R5, ISA-18.2).
9. **Honest empty states.** An empty region collapses to one line; it never
   holds a full panel of "not available".
10. **Always know what is live.** A persistent application-state tag, SIMULATED
    ENGINE (Astro application state), plus the aircraft on the ground station and
    its phase, in the global status bar.

## 4. Information architecture

### Before → after

| Role | Before (sidebar) | After (workspaces, tabs inside) |
|---|---|---|
| Operator | Flight, Aircraft, Overview, Engine, Health, Mission, Replay (7) | **Mission** · **Engine** (Dashboard · Instruments) · **History** (My sorties · Replay) — **3** |
| Maintainer | Aircraft, Overview, Engine, Health, Prognostics, Mission, Report, Replay, Maintenance (9) | **Fleet** · **Aircraft on GCS** (Maintenance plan · Prognostics · Health) · **Reports** — **3** |
| Engineer | 14 pages | **Review** · **Engine** (Dashboard · Parameters · Health · Prognostics) · **Simulate** (Faults · Scenarios · Mission profiles · Test rig) · **Records** (Reports · Replay · Fleet data) · **Engines** — **5** |
| Commander | 19 pages | **Operations** · **Live** (Dashboard · Engine) · **Fleet** · **Records** (Reports · Replay · Audit) · **Admin** (Accounts · Engines) — **5** |

What each role no longer sees, and why:
- **Operator:** no technical log, health indices or prognostics machinery. They get
  the state word, the margins and the Go/No-Go (WHO_READS: "a state word, the
  parameters against their limits, and any alert with the action attached").
- **Maintainer:** no fault injection, simulation, replay or mission planning.
- **Commander:** no fault injection, simulation, test rig or engine
  instruments by default. Readiness and missions are the job; the live
  dashboard is one workspace away when a sortie is flying.
- **Engineer:** no mission tasking, allotment or accounts.

## 5. The shell

```
┌ GLOBAL STATUS BAR (Zone A) ─────────────────────────────────────────────────────────┐
│ ASTRA │ Mission  Engine  History │ SIMULATED ENGINE │ MALE-03 · CRUISE │ ▣WARN ▣CAUT │ 10:44Z │ LINK │ op.rao ▾ │
├ ENGINE STRIP (Zone B) ──────────────────────────────────────────────────────────────┤
│ RPM 5 463 /5 800 │ CHT 114 /135 °C │ EGT 821 /950 °C │ OIL P 55 psi ≥29 │ 8 400 ft · 175 km/h · −2 °C · 80 % │
├──────────────────────────────────────────────────────────────┬──────────────────────┤
│ WORK AREA (Zone C)                                           │ ALERTS (Zone D)      │
│  Page title                         [secondary] [PRIMARY]    │  ▲ CHT RISING        │
│  Tabs: Dashboard · Instruments                               │    reduce power      │
│                                                              │ ─────────────────────│
│  content …                                                   │ WAITING ON YOU       │
│                                                              │  ● Debrief MSN-0003  │
├──────────────────────────────────────────────────────────────┴──────────────────────┤
│ virtual CAN · 2 Hz · link OK                          (engineer: + latency, frames) │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

- **No sidebar.** With three to five destinations, navigation fits in the status bar as tabs
  (Astro GSB order: app, tabs, clock, monitoring, actions). This gives the work area back
  240 px of width.
- **Zone B** stays on every page (Part 4 s6.1). It becomes one compact row with the
  limit printed beside each value. When the engine is off it shows `ENGINE OFF`
  in place of meaningless zeros, instead of flagging oil pressure LOW.
- **Zone D** holds alerts, and below them **Waiting on you**, the role's task
  queue. Both are in the same place on every page, so each is the one place to
  look.
- **Zone E** is one quiet line. The engineer's version adds pipeline latency and
  frame counts; nobody else needs them.
- A crash in one page shows an error card in that page. It never blanks the
  console.

## 6. Role homes (Level 1)

### Operator — Mission

A single column that changes with the sortie's phase (Anthem, F-35), with one
primary action.

```
MSN-0003 · ISR patrol                               MALE-03 ● SERVICEABLE
[Brief]──[Pre-flight]──[Engine]──[Airborne]──[Debrief]

┌ NOW: ENGINE WARMING UP ─────────────────────────────────────┐
│  Oil 38 °C → 50 °C needed for take-off                      │
│  ● Engine holding at warm-up            ok                  │
│  ▲ Oil at take-off minimum              38 / 50 °C          │
│  ● No warning active                    ok                  │
│  ● Twin verdict for 10 h                GO WITH LIMITS      │
│                                    [Abort]   [LAUNCH]       │
└─────────────────────────────────────────────────────────────┘
Task 10 h ISR patrol at 18,000 ft · standard · area North ridge
Aircraft Rotax 915 iS · health 97 % · 960 h · limited to ≤ 4 h missions
```

### Maintainer — Fleet

Master and detail. On the left, the aircraft, ordered by what needs doing.
On the right, the selected aircraft's technical log in tabs: **Status ·
Defects · Work · Logbook**. The primary action is the one this aircraft
needs next: *Sign release*, *Rectify #4* or *Record 100 h inspection*.

### Engineer — Review

The twin's findings queue first (Level 1 for engineering). Each finding shows
its evidence and a single decision control (Confirm / Defer … h / No fault
found) that opens in a drawer. Below it, the squadron's engines side by side,
and the concessions in force.

### Commander — Operations

- A readiness row: each aircraft is one tile showing status, the longest
  mission it can take, and health band.
- A **mission board** in the Maven style, one column per stage: Planned →
  Approved → In progress → Debrief → Done.
- **Plan mission** opens a drawer. Clicking a planned card opens the
  allotment drawer, which ranks candidates by the twin's predicted success
  for that mission.

## 7. Visual system

- **Surfaces:** page `--bg-void`; work surfaces `--bg-panel`; raised items
  `--bg-raised`; separation by tone and 24 px gaps. Borders only where two
  equal surfaces meet.
- **Type:** 16 px floor (Part 4). Section titles 18/600 sentence case; page
  title 24/700; numeric readouts 30 px+ in the tabular face. Uppercase
  letter-spaced text only for data labels.
- **Colour:** readouts in `--ink`. `--state-normal` only on NORMAL status
  symbols, never on numbers. Amber and red only on CAUTION and WARNING. Cyan
  for ADVISORY and for the selected tab.
- **Spacing:** the existing 4 px scale (4, 8, 12, 16, 24, 32). Content max
  width 1280 px on the home pages so lines stay readable.
- **Buttons:** one primary per view (filled `--ink`, legend in the
  background colour), secondary buttons outlined, quiet buttons text-only.
  No amber or red buttons (s3.3a).
- **Status symbol:** an SVG of shape plus colour plus word, the only way
  status is shown.

## 8. Compliance

All of `scripts/hmi_check.py` passes: the 16 px type floor, 30 px readouts,
reserved colours, contrast in both palettes, no forbidden patterns, the zone
layout (Zone B readouts and the Zone D rail in the shell), no transitions
over 150 ms, visible focus, reduced motion, and authenticated fetches.

## 9. Scope

Rebuilt from scratch:
- the shell (status bar, strip, rail, footer)
- navigation and role workspaces
- the design components
- the four role homes (Mission, Fleet, Review, Operations)

The detailed analysis pages (Dashboard, Parameters, Health, Prognostics,
Simulation, Scenarios, Test rig, Replay, Reports, Audit, Engines, Accounts)
keep their content and inherit the new frame and components. None of the
API, the rules or the twin changes.

## 10. As built

### Measured (1920 × 1080, same squadron state for every role)

| Role | Destinations before → after | Home screen before (words · buttons) | Home screen after (words · buttons) |
|---|---|---|---|
| Operator | 7 pages → **3** workspaces | Flight desk 154 · 11 | Mission 179 · 8, one primary action |
| Maintainer | 9 → **3** | Technical log 353 · 19 | Fleet 189 · 19, one primary action |
| Engineer | 14 → **5** | Engineering 302 · 22 | Review 176 · 14, one primary action |
| Commander | 19 → **5** | Operations 400 · 32 | Operations 230 · 15, one primary action |

Word counts are for the whole screen, status bar and rail included. The
operator's home carries slightly more words than before because the mission's
task and aircraft now sit beside the one action, instead of on another page.

### Beyond the section 9 scope

- **Maintenance plan rebuilt.** It listed all seven jobs expanded, each with
  a note field and a button (613 words). Now: the jobs the twin recommends in
  full, the rest one line each, and recording in a drawer (243 words).
- **No browser pop-ups anywhere.** `confirm()`, `prompt()` and `alert()`
  are gone: cancelling a mission, resetting a password, fitting an engine and
  recording work use drawers or two-step buttons. The prognostics page's
  second set of record buttons is removed; work is recorded in one place.
- **Commander's "Waiting on you" is command work only** (`OpsStore.tasks`).
  It used to carry every rectification and engineering review in the
  squadron; grounded aircraft reach the commander as readiness instead.
- **Aircraft context moved into the engine strip.** The four readouts now
  say which aircraft they belong to and what it is doing, and the status bar
  is left to global items only (Astro).
- **The detailed pages sit in a one-row frame**: their views as tabs, the
  aircraft on the station at the right, no second title. They keep their
  content and pick up the new panel style (sentence-case titles, no grey band).
- A clicked task opens the exact aircraft or mission it is about.
- One date format everywhere: `25 Sep 11:11Z`.

### Removed

`pages/Flight.tsx`, `pages/Aircraft.tsx`, `pages/Engineering.tsx`,
`pages/Operations.tsx`, `components/OpsParts.tsx`, `components/Shell.tsx`
(the sidebar). Their work lives in `pages/home/`.

### Verified

`tsc --noEmit`, `vite build`, `scripts/hmi_check.py` (COMPLIANT), and
`layer4_core/tests/test_ops.py` plus `test_admin_api.py`. Every workspace
and view was opened for all four roles in a browser with no page errors.

## 11. Second round: alerting, procedures, detail pages

- **Audio master warning.** PRD Part 4 s4.7 said the console synthesised the
  MIL-STD-411F 5.3.1 tone; nothing did. `lib/audio.ts` now plays the 700 to
  1,700 Hz sweep (0.85 s, 0.12 s gap) while the master warning is lit, and a
  1 kHz / 200 ms beep when the master caution lights, repeated every 30 s for a
  Level-4 caution. Mute is shown in the status bar ("AUDIO MUTED"), a new
  warning cancels it, and "Test alert sound" in the user menu checks the
  speaker.
- **Electronic checklists.** `configs/checklists.yaml` holds a procedure for
  every alert the rule engine can raise, in-flight and on-the-ground steps
  each; `layer4_core/tests/test_checklists.py` fails if a new alert has none.
  Every alert row has a Procedure button, and a new WARNING opens its procedure
  by itself for the operator and the maintainer (ECAM practice).
- **Health, Prognostics, Fault injection and Replay rebuilt** in the new
  components (`pages/detail/`, `pages/Replay.tsx`): one scrolling document per
  page instead of boxes clipping their content, quiet when normal.
- **Replay shows the flights flown on this station**
  (`layer4_core/sortie_replay.py`), cropped to the engine run, with engine
  start, airborne, peaks, exceedances, landed and shutdown found in the data.
  It used to replay only the synthetic fleet data set.
- **A parked engine no longer reads EMERGENCY.** The advisory graded the
  subsystem indices before the engine had ever been assessed warm; a stopped
  alternator made the electrical index "unsafe". The advisory now waits for the
  same assessment gate as the health index.
- **`run.py` self-check** flies a short sortie before checking health, since
  the engine now starts parked and cold (it crashed comparing `None`).
