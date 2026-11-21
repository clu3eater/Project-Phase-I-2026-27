# Squadron operations: who does what, and the rules between them

The engine twin answers *what condition is this engine in, and will it
complete the mission*. This is how a squadron acts on that answer. It is
built to the chain a MALE UAV flight line actually runs — tasking, allotment,
airworthiness release, pre-flight, engine start, launch, recovery, debrief,
defect, engineering disposition, rectification — with each decision owned by
one role and every one of them written to the aircraft's technical log.

Code: `layer4_core/ops.py` (rules and record), `layer4_core/twin_api.py`
(`/api/ops/*`), `configs/fleet.yaml` (the squadron). Console: each role's home
workspace -- Operations, Mission, Fleet, Review (`src/pages/home/`). Tests: `layer4_core/tests/test_ops.py`,
`test_admin_api.py`, `test_sortie_control.py`.

---

## The squadron

`configs/fleet.yaml` lists the aircraft. Each has a **tail** (airframe), a
**twin_id** (the engine's serial — its twin's identity), an **engine_key**
(its engine definition), and the engine hours it arrives with. MALE-03 is
registered with a cooling fault beginning to develop, and nothing tells the
system: the twin has to find it.

One ground station flies **one aircraft at a time**. The aircraft "on the
GCS" has its engine twin running; the others are parked, represented by the
condition their last engine run measured, and their engine lives are kept in
`data/twin_state/<twin_id>.pkl` across restarts (hours, wear, trends, the
work done on them, and the logbook hours: total, since inspection, since
overhaul).

**Signing in does not start an engine.** An engine starts because an operator
started it for an approved mission, or a maintainer ran it on the ground.

## Roles

| Role | Home workspace | Decides |
|---|---|---|
| Commander | Operations | what is flown, on which aircraft, by whom; engine changes; accounts |
| Operator | Mission | whether to start, launch and recall the aircraft allotted to them |
| Maintainer | Fleet | whether an aircraft is airworthy (release), and what work is done |
| Engineer | Review | what a defect the twin raised means; operating limitations |

The right-hand rail carries **Waiting on you** on every screen: the actions
that person owes, most urgent first (`OpsStore.tasks`), each opening the
aircraft or mission it is about. It lists a person's OWN work only; the
commander sees allotment decisions, not the squadron's maintenance backlog,
which reaches them as readiness on the Operations board.

## Aircraft status (derived, never stored)

| Status | When |
|---|---|
| FLYING / ENGINE RUNNING / GROUND RUN / ON GCS | the ground station is working this aircraft |
| UNSERVICEABLE | any grounding reason (below) |
| AWAITING INSPECTION | no maintenance release signed since the last engine run or work |
| SERVICEABLE | released, nothing grounds it |

**Grounding reasons**: an open or confirmed defect marked grounding; a
deferred defect past its hours limit; the 100 h inspection due
(`inspection_interval_h`); TBO reached. A maintenance release is refused while
any exists. The release is **withdrawn** automatically after every engine run
(after-flight inspection due), after any maintenance work, when a grounding
defect is raised, and on an engine change.

## Mission states

```
PLANNED ─approve(tail, operator)─▶ APPROVED ─prepare─▶ PREFLIGHT ─start(checklist)─▶ ENGINE_RUNNING
   │                                  │  ▲ handback        │                          │    │
   └─cancel─▶ CANCELLED ◀─cancel──────┘  └──────────────────┘                     launch  abort
                                                                                      ▼    ▼
                          COMPLETED / ABORTED ◀─debrief─ AWAITING_DEBRIEF ◀─shutdown─ AIRBORNE ─rtb─▶ RTB
                                                                               ▲─────────── ABORTING
```

- **Approve** (commander): the aircraft must be SERVICEABLE, not allotted to
  another open mission, inside its operating limitations, and not **NO-GO** in
  the twin's assessment for *this* mission's endurance and altitude
  (`OpsStore.assess`, the same `MissionReliability` the live twin uses, fed
  with the aircraft's last measured condition). Candidates are ranked GO,
  GO WITH LIMITS, NOT ASSESSED, then by predicted success. An approved
  mission can be re-allotted if its aircraft becomes unserviceable.
- **Prepare** (the allotted operator): the aircraft is loaded onto the ground
  station, engine off. Only one mission or ground run occupies the station.
- **Start**: every item of `preflight_checklist` confirmed; the engine starts
  from cold and holds at the warm-up setting. An engine not cleared to launch
  within 30 minutes of engine time is shut down.
- **Launch** (refused otherwise): holding at warm-up, oil at the take-off
  minimum, engine running steadily, **no warning** active, twin verdict not
  NO-GO. Active cautions are shown to be weighed, not blocking.
- **RTB** from take-off, climb or cruise: the aircraft descends from where it
  is. **Abort** before launch: cool down and shut down.
- **Shutdown** (the engine stops): the mission waits for debrief, the
  aircraft's release is withdrawn, and the twin's maintenance advisories of
  CAUTION and above are written to the technical log as **TWIN defects**
  (WARNING and EMERGENCY ground the aircraft). A repeat advisory does not
  duplicate an open defect.
- **Debrief** (operator): outcome, remarks, and snags, each of which becomes a
  defect on the aircraft.

## Defects

| Source | Raised by |
|---|---|
| TWIN | the engine twin, at the end of every engine run |
| OPERATOR | a debrief snag, or reported from the aircraft's technical log |
| MAINTENANCE / ENGINEER | found on inspection, or grounding the aircraft |

Engineer's disposition: **CONFIRM** (optionally grounding), **DEFER** with an
hours limit (the aircraft may fly; past the limit it is grounded again), or
**NFF** (closed). Every disposition needs its reasoning. Maintainer's
**RECTIFY** closes a defect with the maintenance actions done (A1–A7); the work
reaches the aircraft's engine twin immediately if it is on the ground station,
otherwise at its next engine run, with its "before" reading taken from the
condition the squadron log kept.

## Ground runs

Start, 3 min warm-up, 2 min run-up at 45 % (held where the twin can judge the
engine warm and loaded, inside every limit for a sound engine with no ram air),
90 s cool-down, shutdown. How rectification is verified, and how an aircraft
that has not flown gets a measured condition. A ground run ends like a flight
does: the twin's findings are written as defects.

## Endpoints

| Method | Path | Scope |
|---|---|---|
| GET | `/api/ops/board` | read:ops |
| GET | `/api/ops/aircraft/{tail}` | read:ops |
| POST | `/api/ops/missions` | plan:mission |
| GET | `/api/ops/missions/{id}/candidates` | plan:mission |
| POST | `/api/ops/missions/{id}/approve`, `/cancel` | plan:mission |
| POST | `/api/ops/missions/{id}/prepare`, `/handback`, `/start`, `/launch`, `/rtb`, `/abort`, `/debrief` | fly:mission |
| POST | `/api/ops/aircraft/{tail}/release`, `/maintenance`, `/ground_run` | write:maintenance |
| POST | `/api/ops/defects/{id}/rectify` | write:maintenance |
| POST | `/api/ops/defects/{id}/disposition`, `/api/ops/aircraft/{tail}/limitations` | review:defects |
| POST | `/api/ops/aircraft/{tail}/defects`, `/ground` | raise:defect |
| POST | `/api/ops/aircraft/{tail}/connect` | read:ops (commander, maintainer, engineer) |
| POST | `/api/ops/aircraft/{tail}/engine` | admin:fleet |

Scopes are assigned to roles in `configs/thresholds.yaml` (`security.roles`);
the commander holds all through `*`. Mission, maintenance, engine-change and
account actions are also in the hash-chained audit log.

## Honest limits

- One aircraft is simulated at a time; parked aircraft are their last
  measured condition, not a parallel simulation.
- The tasked cruise is compressed (`ops.simulated_cruise_hours`, or
  `DT_CRUISE_HOURS`); reliability is assessed for the planned endurance.
- An aircraft's condition is unknown until the twin has run its engine on this
  station; its hours, inspection and TBO position are known from its log.
