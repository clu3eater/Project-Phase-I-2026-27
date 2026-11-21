# The engine view: floating parts, washed-out light, and a frame-rate cap

26–27 Sep 2026. Three complaints about `Engine ▸ Parameters`: components floating
away from the engine, a light theme that looked washed out with a model that was
not clean or smooth, and low frame rates while orbiting "across different
devices". All three were traced to root cause before anything was changed, and
all three are fixed. Everything below was measured on this machine — Chrome
headless on an RTX 3090 through ANGLE/D3D11, against the real console at
1920×1080 — not estimated.

---

## 1. Nine parts floated because the shipped "assembled" pose is not assembled

**What was wrong.** Nine of the 72 parts sit off the engine with clear air all
around them. Measured as the shortest distance from each part's real geometry to
the rigid engine core (crankcase, cylinders, heads, covers, mounts, gearbox):

| part | gap to the engine |
|---|---|
| `OVERBOOST_VALVE` | 0.607 |
| `OIL_TANK` | 0.385 |
| `FUSEBOX` | 0.333 |
| `BOOST_CONTROL_SOLENOID_VALVE` | 0.323 |
| `INTERCOOLER` | 0.291 |
| `AMBIENT_AIR_SENSOR` | 0.279 |
| `ECU` | 0.255 |
| `AIR_BAFFLES` | 0.201 |
| `GEARBOX` | 0.111 |

Against a scene 2.64 across, the air baffles hung a quarter of the model away.
Nine parts touched *nothing at all* — not another part, not even a hose.

**Root cause.** Not random scatter. Every one of the nine is displaced **along
its own EXPLODE axis**: the direction that closes the gap and the direction the
GLB's `EXPLODE` clip throws that part are the same line, cos **0.87 to 1.00**
across all nine. The pose the model ships in is a *partially exploded* pose —
the export kept a residual offset on exactly the parts that travel furthest.

Three things were checked and ruled out first: the rest pose is bit-identical to
the final frame of `REPACK` and the first frame of `EXPLODE` (72/72 nodes), so
the GLB is internally consistent and nothing in the console had displaced them;
every node's parent chain is the identity, so nothing was a transform error; and
all 72 mesh nodes are reachable from the default scene.

**The fix.** The correction the model itself defines: slide each part back down
its own explode axis until its geometry touches the engine. Solved offline
against the GLB's **613,885 vertices** by binary search on first contact at a
2.5 mm tolerance. All eight islands seated along the explode axis — none needed
the fallback "shortest path to the nearest surface", which is itself strong
evidence the diagnosis is right.

Applied **at load, not in the asset** (`SEATED` + `seatFloatingParts` in
`EngineModel.tsx`). The GLB, the registry and the fault matrix come from the
`ROTAX_915IS_FAULT_INTEGRATION` package under a published contract with its own
test suite, and `repaintToConsolePalette` already adjusts that package as it
loads rather than forking it. This follows the same rule. No geometry, no name
and no registry id changes — only where nine nodes sit.

The deltas are applied to the rest pose **and to every keyframe of both clips**,
because the clips carry absolute positions: patch only the rest pose and the
first frame of `EXPLODE` would snap each part straight back out.

**Verified.** Bounding radius **1.3203 → 0.7751**. After a full EXPLODE and
REPACK cycle the parts return to the seated pose with a worst-case error of
**0.00e+0** — bit-exact.

---

## 2. The light theme was washed out, and the camera was inside the engine

Two separate faults behind one complaint.

**The light rig was over-driven.** A hemisphere at 2.2 plus a key at 1.1, on
r160 lighting that is already physically scaled, drove the pale castings past
white while leaving the dark ones at black — a silhouette with blown edges.
Now: a procedural `RoomEnvironment` supplies the ambient (built once, one cube
lookup per fragment, `envMapIntensity` 0.5), with hemisphere 0.5, key 1.25 and a
0.3 back-fill. That is what makes the aluminium read as aluminium rather than a
grey blob, without becoming a showroom — the rule that even light matters more
than flattering light still holds, because the lit part is the reason the model
is there.

**No tone mapping, deliberately.** ACES or Reinhard would roll the highlights
off nicely and would shift every fault colour on the way. The six coding colours
in `theme/tokens.css` have to leave the renderer as they entered it. Verified:
a `COOLING_DEGRADATION` highlight renders at emissive **`#ff3b30`** — exactly
`--alert-warn`.

**The backdrop was read once and never again.** Switch day/night and the 3D
panel kept whichever ambient was set when the page first opened — a night
backdrop inside a light console for the rest of the session. Now a
`MutationObserver` on `data-ambient` repaints it.

**The camera was buried in the crankcase.** The default view called
`focusComponent("ROTAX_915IS_CRANKCASE", 2.6)`, which showed a cylinder barrel
and half a generator cover with no way to tell what you were looking at. That
framing existed *because* nine parts floated: a whole-model fit had to take them
in, so the engine came back as a thumbnail ringed by empty panel. With the nine
seated the honest fit is also the good one, so the default view is now the whole
engine at a 6 % margin.

Getting that fit right took three goes, and the first two are worth recording
because both looked correct on paper:

1. **Fit the scene's bounding box against both fields of view.** Covered 60 %
   of the panel width. The box's extreme corner projected to 1.087 of the
   frame — apparently a snug crop — while the engine sat marooned in the
   middle. A single box around an irregular assembly seen obliquely is a bad
   stand-in for its silhouette: the corners stick out into empty air, and the
   near ones are closer to the camera than the engine is, so perspective throws
   them wider still.
2. **Fit each mesh's own bounding box, projected through the real camera.**
   69 %. Tighter, but a pipe running diagonally still puts its box corners in
   empty air.
3. **Fit sampled real vertices.** 93 % of the width, 65 % of the height (the
   height is limited by a wide engine in a portrait panel, which is correct).
   Each mesh contributes ~48 evenly spaced vertices, about 3,000 points for the
   whole engine — a fraction of a millisecond, and only when the view is framed,
   never per frame while orbiting.

The distance is solved by iteration: projected extent scales as roughly
1/distance near the target, so scaling the distance by the measured overshoot
converges in two or three passes and stops within a percent.

A second, separate bug was found in the same place: the first fit runs while the
effect is still setting up, before React has necessarily laid the panel out, so
`clientWidth` can be 0 and the aspect falls back to a floor. The ResizeObserver
then corrected the aspect *without ever re-fitting*, so a bad distance stuck for
the session. Any resize now re-frames, until the operator first touches the
camera — which also keeps the engine framed when the window changes size or the
alert rail appears, something it never did before.

`CLEAR FOCUS` also now restores the framing. It used to drop only the ghosting,
leaving the operator nose-down on a fuel rail with no way back but orbiting out
by hand; it eases back along whatever direction they are currently looking from,
so it restores the framing without confiscating the angle they chose.

---

## 3. The frame rate was capped in software, which is why every device was slow

**Root cause.** `MIN_FRAME_MS = 1000 / 20`. The old loop painted a fixed 20 fps
for as long as the page was open. Measured before: **19.0 fps idle, 18.1 fps
orbiting — on an RTX 3090.** It would have orbited at 18.1 fps on any machine
ever built, which is exactly the "slow on every device" that was reported.

The instinct behind the cap was right and is preserved: a 3D view has no
business competing with the data path. But a fixed cap is wrong in both
directions at once — it spends a whole frame every 50 ms redrawing a picture
nobody is touching (212 draw calls, 539k triangles, forever), and it caps the
one moment that has to feel immediate.

**The fix — render on demand.** The loop is driven by change:

| state | behaviour |
|---|---|
| idle | nothing is painted at all |
| orbit / zoom / pan | every frame the display will take |
| pulse / explode | 30 fps, ample for a 0.8 Hz annunciator |
| tab hidden | nothing, as before |

Anything that changes the picture from outside the loop asks for a frame
(`paint`): the fault effect, `CLEAR FOCUS`, explode, resize, click, wheel.

**Adaptive resolution.** `devicePixelRatio` alone is a poor predictor — a 2×
panel in front of an integrated GPU and a 2× panel in front of a discrete one
want different buffers. The renderer starts at the display's ratio and steps the
buffer down only when the frames it is *already* delivering fall behind budget,
and steps back up when they do not. Antialiasing is enabled only below DPR 1.5,
where it is not already paid for.

**The 4 Hz repaint.** The fault effect runs on every snapshot and used to
re-apply every active fault each time, rewriting materials the layer had already
set and asking for a frame on every tick — a static engine cost 4 fps of GPU and
a layer flush per tick. The wanted state is now hashed to the nearest 1 % of
magnitude and an unchanged tick returns before touching anything.

### Measured, before and after

| | before | after |
|---|---|---|
| idle | 19.0 fps · 212 draws · 539k tris | **0.0 fps · 0 draws** |
| orbiting | 18.1 fps | **59.8 fps** |
| zooming | 18.4 fps | **26.7–34.6 fps** ¹ |
| after interaction | 18.7 fps | **0.0 fps** |
| buffer at DPR 2, 20× CPU throttle | 1162×1434 fixed | **871×1075** (auto, 1.5×) ² |

¹ limited by the synthetic wheel-event rate in the harness, not by the renderer.
² the ladder settles wherever the machine can hold the budget; runs landed at
1.25× and 1.5× on repeats of the same throttled test, which is the point of it.

Orbiting is **3.3× faster** and idle GPU cost went to **zero**, so total work is
far below the old cap — the data path still wins, which was the point of the cap.

---

## 4 · Second pass: reaching the faults, and reading the cylinders

Three additions once the view itself was sound.

**A fault list, not a stepper.** The camera flies to the worst fault the moment
it lights. Every *other* lit fault was unreachable — somewhere on the engine,
with nothing naming it and no way to bring the view round. A next/prev stepper
was considered and rejected: you get one to three faults at a time, and the
correlated ones co-occur, so a stepper would have hidden both the count and the
names while costing the same space. Instead there is a list under the buttons,
worst first, `StatusSymbol` + name + probability, click to fly there, the one
the camera is on marked with `aria-current` and a raised background.

It doubles as the legend, which the view had never had: nothing on the panel
explained that a dim grey part is *related to* the fault rather than a second
broken one. No back button — back to the whole engine is CLEAR FOCUS, and back
to another fault is that fault's own row. The block is absent entirely when
nothing is lit, which is the common case.

**Cylinder numbers on the model.** The Cylinders panel sits immediately beside
this view listing CYL 1–4, and the detector names faults per cylinder —
"misfire, cylinder 3", and above magnitude 0.5 its coil partner too. The model
lit a barrel and there was no way to tell *which* barrel, so the two halves of
the same fact sat side by side unable to refer to each other. The registry
already maps `CYLINDER_01..04` to cylinders 1–4, so this is a label, not a
modelling job.

Drawn as DOM, not sprites or 3D text: the 16 px type floor covers glyphs too,
and real CSS type in `--font-num` stays crisp at any zoom and themes itself from
the tokens. The bank turned away from the camera is hidden — its number would
float over the parts in front of it and point at nothing — by a facing test,
not a raycast, because four rays against 613k triangles every time the camera
moved would have cost more than the labels are worth.

**The explode prompt now tells the truth.** It used to appear whenever anything
was lit. That is not the same claim: only **two of the eight** faults light a
part an operator cannot see — `COMBUSTION_INSTABILITY` (the four pistons) and
`ABNORMAL_VIBRATION` (the crankshaft). For the other six it was telling people
to take the engine apart to see parts already in plain sight. It now counts the
lit components the registry flags `internal` and says nothing when there are
none.

**On the backdrop.** A gridded floor was asked for and not built. A grid puts
faint grey texture directly behind `HIGHLIGHT_CONTEXT`, which *is* a faint grey
glow at 0.25 emissive and is the quietest thing this view has to say; on the day
ambient it would also have needed tuning twice to avoid becoming grit on a
near-white panel. A painted contact shadow was the other candidate and is a lie
that breaks the moment the operator orbits underneath, which OrbitControls
allows. What shipped instead: the background darkens by 12 % towards the bottom
and nowhere else, with the top half left at exactly `--bg-panel` so the canvas
still meets its card with no seam. It is correct from every angle because there
is no geometry in it to be wrong. If it is not wanted, `paintBackground` goes
back to a flat colour in one line.

## 5 · The Cylinders card beside it

Reported as looking bad, and it was, for three reasons that are worth naming
separately because only one of them was the card's own fault.

**The comparison was left to the operator.** Per-cylinder temperatures exist to
find the odd cylinder. The card listed four head temperatures in one column and
four exhaust temperatures in another, most of a panel apart, so reading one
cylinder meant crossing the card and holding a number in your head. Meanwhile
the one comparative figure it did compute — the spread — sat alone in the
header, far from the values it describes.

**The empty lower third was not the card's fault.** Its height comes from the
page grid: it stretches to match *Engine systems* beside it. Every candidate
layout left the same gap until the content was told to fill the height.

**What shipped.** Two columns of two, laid out the way the engine is — 1 and 3
on one bank, 2 and 4 on the other. That is how the ignition coils are grouped
(`COIL_1_3` / `COIL_2_4`) and how a misfire progresses to its partner cylinder
above magnitude 0.5, and it is the same arrangement as the cylinder numbers now
drawn on the 3D model, so "cylinder 3 is hot" can be read on the panel and
pointed at on the engine without translating between them. Head and exhaust for
one cylinder sit together, each tile carries its own departure from the
four-cylinder mean, and the tiles stretch to fill the card.

**A limit bar per tile.** A head temperature of 14.5 says nothing on its own
unless you happen to know this engine runs 80–120 and is certified to 135, and
that is not knowledge anyone supplies from memory at 3 a.m. The track runs 0 to
`critical_max`, so its right-hand end is the number the engine may not exceed;
two faint ticks mark `normal_min` and `normal_max` and an amber tick marks
`alert_max`. Every line is read from the engine definition that `/api/engine`
publishes — nothing on the bar is a threshold chosen here.

The fill is coloured by the threshold the value has actually crossed, so it can
never disagree with the alert engine: muted below the band, ink in it, caution
amber at `alert_max`, warning red at `critical_max`. A cold engine therefore
draws a short bar well short of the band, which is the truth rather than a
fault, and the fill walks up into the band as it warms. Verified by driving
each cylinder into a different band: 95 → ink, 125 → ink, 133 → amber,
136 → red, with widths proportional to value ÷ 135.

`HIGH` is still spelled out next to a value over its limit rather than only
coloured — colour is not a coding channel on its own here, and the value has to
survive being read on a monochrome display. It sits pushed to the right of its
own line rather than running on after the unit: inline, the longer string
wrapped, which pushed the bar down a line and broke the alignment across the
row — on exactly the tiles an operator is scanning hardest.

**Two other layouts were built and rejected**, both as real code in the real
panel rather than as mock-ups, because this card sits inside a design system
that `hmi_check.py` enforces and anything drawn outside it would have lied about
the result. Deviation bars on a fixed ±12 °C / ±50 °C scale read best for
spotting an outlier — four markers stacked on the centre line is the healthy
case stated positively — but the two bar columns came out unequal and the whole
card read as busy. A tightened table with Δ columns was the safe option and is
the one to revisit if the tiles ever feel too large.

## 6 · Engine ▸ Health

Reported as looking off. Two of the three findings were wrong output, not taste.

**The page printed a machine token where the operator's instruction belongs.**
`Health.tsx` rendered `band.action` — `"none"` — so a healthy engine displayed
the bare word **"None"** under its band, unlabelled, reading like a bug. Every
band in `configs/thresholds.yaml` carries `instruction` *beside* `action`, with
a comment saying why they live together: `action` "is the machine token the
advisory logic branches on", `instruction` "is what the OPERATOR is told to do".
The page now reads **"No action required."**

**`Trend` collapsed on a flat series.** The pad was `(hi - lo) * 0.15 || 1`, and
the `|| 1` is the whole problem: when nothing has changed `hi - lo` is 0, so a
ratio between 0 and 1 was plotted on an axis running −0.03 to 1.97. A held
composite health index — 240 identical samples, which is exactly what a
shut-down engine reports — drew as a lone flat line adrift in an empty band,
labelled **"1.0 / 1.0"** because both ends rounded to the same figure. The pad
is now proportional to the data rather than to its spread, the label carries
enough figures to tell the ends apart, and a genuinely flat series says
**"0.936, not changing"** and draws no chart at all: a straight rule across an
empty band is not a smaller chart, it is a chart-shaped hole that occupies the
height of real evidence while carrying none. This also repaired
`Overview.tsx`'s degradation-trend card, which used the same component at 140 px
and had the same hole in it.

**The top four numbers were the nine below, repeated.** `layer3_ai/health.py`
makes each subsystem the **minimum** of its contributors, so `thermal = min(thi,
oti)` *is* THI to the decimal, `combustion` is CSI, `mechanical` is MHI,
`electrical` is EHI. Every headline percentage was one of the nine, shown twice
with nothing to say they were the same fact — while the figure that actually set
each subsystem sat unranked among nine, and at a healthy 97 % nothing carried a
symbol at all, because `healthLevel` only marks below 0.90.

So the duplication became the explanation. One area, **"What sets this score"**,
replaces both: each subsystem states its value, carries a bar, and **names the
index that set it** ("Thermal — set by THI"), with its contributors nested
underneath, worst first, the limiting one in full ink and the rest dimmed. Above
it, the composite is written out — `0.30 × 88.9 thermal + 0.25 × 96.0
mechanical + …` — so the headline number can be checked rather than believed.

The grouping is not invented in the front end: it mirrors `SUBSYSTEM_INPUTS` in
`layer3_ai/explain.py`, which the backend already keeps beside the estimator
"so the explanation cannot drift away from the computation it claims to
explain". The weights are now served on `/api/engine` beside `chi_bands`, for
the reason that endpoint's own docstring gives — a console carrying its own copy
of the numbers "will disagree with the system eventually, and the operator will
believe the console".

**Verified against a flown engine, not a parked one.** A mission was released,
planned, approved, prepared, started and launched (MSN-0005, MALE-02) so chi
actually moved — 86 distinct values across the session. Checked in both states,
day and night: running (91.2 %, climb, a live INJ TIMING DEV caution) and held
after shutdown (93.6 %, "Held from last warm running"). All four subsystems
equalled their named limiting index exactly: thermal 0.8791 = THI, mechanical
0.8750 = MHI, electrical 0.9639 = EHI, combustion 0.9680 = CSI.

**And then the visual redesign, which the first pass had not actually done.**
Everything above reorganised the *information* and left the page looking like
the same stack of bordered boxes with text in rows. Two instruments replaced the
text:

*Against the bands.* A scale carrying the seven `chi_bands` at their own
boundaries, the fill coloured by the band it lands in, and the edges cut through
the fill in the panel colour so they stay legible on the dark side — drawn in
`--line` they vanished exactly where the score was, which is the half of the
scale that matters. Beneath it the one figure nothing on the page carried:
**"3.6 to give before Good"**, the distance to the edge at which the instruction
changes from "no action required" to "monitor". (First attempt read "3.6 above
Excellent", which says the wrong thing — 93.6 is not *above* Excellent, it *is*
Excellent, with 3.6 to give.)

*What it is costing, out of 100.* The composite was a line of arithmetic that is
true and that nobody reads. Now the bar **is** the sum: its full width is 100
points of health, each subsystem owns a slice as wide as its weight and fills it
to its own score, so the filled length across the whole bar is exactly chi and
the gap at the end of each slice is the points that subsystem is costing. The
gaps total 100 − chi. It changes the question from "which subsystem has the
lowest percentage" — not the same thing — to "which one is taking the most off
the total": a 0.20-weighted electrical fault and a 0.30-weighted thermal one do
not cost the same, and on a row of four percentages they look as if they do.
Held state reads Thermal −3.3, Mechanical −1.0, Electrical −0.8, Combustion −0.5.

**Revert point.** This project is not a git repository, so the four files were
copied to `_backup/health-redesign-2026-09-27/` before any edit, with
`restore.ps1` / `restore.sh` beside them.

## 7 · Engine ▸ Health, the layout

The station is run at **80 % browser zoom**, which on a 1920×1080 screen gives a
2400×1310 viewport and a 2064×1071 work area. Measured there, the page was using
about **half of it**: the content column was capped at `--content-max` (1480 px)
leaving **584 px unusable to the right**, and the content stopped **314 px short
of the bottom**, with the small cards 24–35 % empty inside their own boxes.

**The cap went, on this page only.** `--content-max` holds prose to a readable
measure and seven other pages want it; this one is an instrument panel whose
longest string is "Head and coolant temperature against the as-new model". The
token is untouched.

**Three full-width bands** replace the card stack: the verdict, the four
subsystems, then the trend and the two standing measurements side by side rather
than stacked in a narrow column where each kept a third of its box empty.

**Each subsystem became an instrument, and that is what fills the screen** — with
evidence rather than padding. Every sub-index is a judgement about a signal the
station is already recording at 240 samples a session, and the page was showing
only the judgement. "THI 65.6 %" is an opinion; cylinder head temperature
plotted against the as-new model — which is the literal definition of THI — is
the evidence for it. So the limiting index of each subsystem now brings its own
trace: `cht` with `cht_pred` dashed for THI, `vibration_rms_total` for MHI,
`oil_pressure` for LHI, `egt` for CSI, and so on. EHI has no channel in the
session history, and that panel says so rather than plotting something adjacent
and letting it look like proof.

One correction on the way: the third band was first set to `align-items:
stretch`, which padded Fuel efficiency and Battery to match the taller trend card
beside them — 61 % empty each, which is the exact fault this pass exists to
remove. Natural heights and a ragged bottom edge are the honest shape of three
cards with different amounts to say.

### Measured, before and after — at the zoom it is run at

| | before | after |
|---|---|---|
| unusable width | **584 px** | **4 px** |
| empty height (engine running) | 314 px | **76 px** |
| *Fuel efficiency* internal waste | 35 % | 24 % |
| *Battery* internal waste | 24 % | 24 % |
| *What sets this score* | — | 10 % |

Verified at both 2400×1310 (80 %) and 1920×1080 (100 %), day and night, with the
engine running and held after shutdown — and against a genuinely degraded engine
(MALE-03, 77.9 % FAIR), where the contribution bar shows Thermal −10.3 and
Mechanical −7.8 in red and the thermal trace shows measured head temperature
running well clear of the dashed as-new line. That gap is the fault, on the page,
without anybody having to know what THI stands for.

**Revert points.** Two, since the project is not a git repository:
`_backup/health-layout-2026-09-27/` goes back one step to the page before this
layout pass; `_backup/health-redesign-2026-09-27/` goes all the way to the
original.

## 8 · Engine ▸ Health, the visualisations

The layout pass filled the screen; it filled part of it with sparklines that
answered nothing. A line with no baseline, no band and no reference is not a
small chart, it is a chart-shaped assertion — and three of the four were
exactly that. This pass audited every figure against the data behind it and
replaced the ones that could not justify themselves.

**The rule applied to each: what engineering question does this answer?**

| card | before | after | why |
|---|---|---|---|
| Thermal | measured and model as two wandering lines | **deviation on a zero baseline** | THI scores the GAP between them; plotting both made the reader estimate it by eye |
| Mechanical | one noisy RMS trace | **per-axis bars + kurtosis + dominant frequency** | MHI is "level and impulsiveness"; a rise on one axis is a different fault from a rise on three |
| Combustion | an EGT time series | **cylinder balance against the allowed spread** | CSI *is* the spread across cylinders — a time series of one aggregate cannot show imbalance at all |
| Electrical | an empty chart frame | **bus volts and alternator current on their certified bands** | there is no session history for the bus, but "is this reading where it should be" is still answerable |
| Battery | a list of numbers | **state of health against the replacement point** | a pack is judged against end-of-life, not against zero |
| Fuel efficiency | two numbers in a list | **measured beside as-new on one scale** | the question is a comparison, not a reading |

**Three findings the audit turned up that were not about drawing at all.**

*`oil_pressure` publishes `normal_max` and `alert_max` at the same figure*
(both 72.5), so ticks keyed by value collided and React warned about duplicate
keys. Keyed by role now.

*The engine definition publishes `battery_voltage`, which is not the reported
`electrical.bus_voltage`.* Mapping one onto the other to get a scale would have
asserted an equivalence nothing establishes, so the bus reading is shown
without a band instead.

*Subtracting the as-new model from a stopped engine gives about −85 °C* — not a
fault, just the engine being off, and drawn as a deviation it reads as a
catastrophe. The samples where the engine was not turning are masked out of the
trace rather than the whole chart being withheld: a session that included
running time still has real evidence in it, and hiding that because the
aircraft is descending right now would throw away the thing the card exists for.

**Limited-data states are one line, not an empty frame.** `NoTrace` takes the
room one line takes and says what is missing and why, in the estimator's own
words where it has them — "judged with the oil at or above 50 °C and the engine
above 3500 rpm" is the system's published gate, not a phrase invented here.

**Four across, or two by two, never three.** `repeat(auto-fit, minmax(...))`
passes through a three-column stage on the way down, stranding the fourth card
alone beside two empty tracks. `.hx-drivers` sets explicit steps instead.

### Verified

Against a live engine at 5468 rpm in the climb, and again held after shutdown;
at 2400×1310 (80 % zoom, the station's normal setting), 1920×1080 and 1280×900;
day and night. Every card under 20 % internal waste, "What sets this score" at
8 %. No console errors. `tsc`, `npm run build`, `hmi_check.py` COMPLIANT, every
view of all four roles renders.

**Nothing outside presentation was touched.** Three files changed — `Health.tsx`,
`HealthIndices.tsx` and the new `HealthFigures.tsx` — plus one CSS rule. No
formula, threshold, telemetry value, health-score, fault or simulation code was
modified; all data is read as served. Revert point:
`_backup/health-dataviz-2026-09-27/`.

## Files modified

| file | change |
|---|---|
| `layer5_viz/gcs_console/src/components/EngineModel.tsx` | sections 1-4 |
| `layer5_viz/gcs_console/src/pages/detail/Cylinders.tsx` | new; section 5 |
| `layer5_viz/gcs_console/src/pages/Pages.tsx` | the Cylinders card body |
| `layer5_viz/gcs_console/src/pages/detail/Health.tsx` | section 6 |
| `layer5_viz/gcs_console/src/pages/detail/HealthIndices.tsx` | new; section 6 |
| `layer5_viz/gcs_console/src/components/Core.tsx` | `Trend` flat-series fix |
| `layer4_core/twin_api.py` | serves `composite_weights` on `/api/engine` |
| `docs/PRD_DEVIATIONS.md` | DEV-257 |
| `docs/ENGINE_3D_OVERHAUL.md` | this report |

The GLB, `faultLayer.js`, the registries and the fault matrix are **untouched**.

## Verified

- assembled model has no floating components — 9 seated, radius 1.3203 → 0.7751
- explode → repack returns bit-exact (worst node error 0.00e+0)
- component selection works (picked "Cylinder head 1")
- fault highlighting works and is anatomically right — `COOLING_DEGRADATION`
  lights the four heads, expansion tank, hoses, water pump and coolant sensor;
  `MISFIRE` lights cylinders 1/3, their heads, covers, coils, leads and plugs
- alert colours exact through the new lighting (`#ff3b30` = `--alert-warn`)
- light and dark both clean; the backdrop now follows the ambient
- the engine fills 93 % of the panel width (was 60 %), measured from pixels
- orbit/zoom/pan smooth (59.8 fps); adaptive buffer proven under 20× throttle
- no console or runtime errors anywhere
- every view of all four roles still renders — `ALL VIEWS OK`
- the fault list orders worst-first, marks the focused fault, and moves the
  camera on click; verified by rewriting snapshot frames in flight so the real
  component ran on the real WebSocket path
- cylinder numbers track the parts through EXPLODE and hide the far bank
- the explode prompt appears for pistons and the crankshaft, and for nothing
  else
- `tsc -b` clean, `npm run build` clean, `hmi_check.py` **COMPLIANT**

## Remaining limitations

- **Fault highlighting could not be driven end-to-end from the live twin**, and
  this is the twin's designed behaviour, not a fault in the view. A parked
  engine reports `fault_probability_source: "not judged: waiting for this
  engine's first level flight to set its reference"` with
  `rule_based_fallback: true` and `model_confidence: 0.0`, so every probability
  is 0.000 and nothing crosses a threshold. Injecting a 0.95-severity cooling
  fault changes nothing while the engine is at 0 rpm. The highlight path was
  therefore verified against the real fault layer, the real registry and the
  real model rather than through a flown sortie. To see it on the live console,
  fly a mission (`/api/ops/missions/{id}/start`) until the reference sets.
- **The seating is first-contact, not CAD-correct.** Each part is brought until
  its geometry touches the engine at a 2.5 mm tolerance. It removes every
  visible gap and cannot cause a part to sink into another, but it is not a
  claim about where Rotax bolts them. If the package ever ships a corrected
  assembled pose, delete `SEATED` and the table becomes a no-op.
- **240 draw calls and 613k triangles per frame** are unchanged; no geometry was
  decimated and no part was merged, deliberately, since merging would cost the
  per-component selection and highlighting the whole view exists for. This is
  comfortable at 60 fps here and the adaptive buffer covers weaker machines.
- **8 `data/models/*` files are still Git LFS pointers** (`tier3.pt`,
  `tier2_extended.joblib`, `rul_lstm.pt`, `survival_head.pkl`, `ood.npz`,
  `fault_namer.joblib`, `tier3_edge.onnx`, `tier3_edge_int8.onnx`). Unrelated to
  this work and unreachable from here — `git lfs pull` fetches them.
