# Promo / explainer video — production brief

**PS 26054 · AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs**

Target: **90 seconds, 1920×1080, 30 fps** (2,700 frames) in Remotion.
Extends to a 3-minute explainer by adding the four optional scenes at the end.

The spine of the film is one idea, and everything else serves it:

> A fixed limit tells you an engine has failed. A digital twin tells you it is
> *failing*. That difference is measured in hours, and hours are what save the
> aircraft.

---

## 1. Scene plan

Frame ranges are exact so they can go straight into a Remotion `<Series>`.

| # | Scene | Frames | Secs | What is on screen | Motion |
|---|---|---|---|---|---|
| 1 | **Cold open** | 0–240 | 8 | Black. A vibration trace draws left to right, steady, then develops one small spike. Type: *"An engine 6,000 m up is beginning to fail."* → *"Nothing on board knows it yet."* | Trace draws on a path; spike arrives at frame 190; one red flash at 235 |
| 2 | **The problem** | 240–600 | 12 | Four cards chain in: Engine operates → Sensor reading → Fixed threshold → **Alarm raised**. Fourth card turns red; *TOO LATE* stamps across it. Line: *"Threshold-based monitoring reports failure after the damage."* | Cards spring in 12f apart; connector lines draw between; stamp scales 1.4→1.0 with overshoot |
| 3 | **Title / the turn** | 600–840 | 8 | Hard cut, dark → light. One frame of white at 600. Title, subtitle, DRDO seal. | Title mask-wipes up; seal fades; everything settles by 700 |
| 4 | **The idea — the residual** | 840–1260 | 14 | Banner: *SAME FLIGHT CONDITIONS*. Split: **REAL ENGINE 112 °C** ‖ **PHYSICS TWIN 103 °C**. Both slide to centre → **THE DIFFERENCE = +9 °C**. Then three cards fan out: *What is wrong · How bad · How long you have*. | Numbers count up; the two panels converge on a spring; difference card scales in; three cards stagger 8f |
| 5 | **The system** | 1260–1680 | 14 | Six layers stack from the bottom: L0 Engine → L1 Acquisition → L2 Physics → L3 AI/ML → L4 Twin core → L5 Dashboard. A data pulse travels up through them. | Each layer slides up + fades, 40f apart; pulse is a gradient sweep on a mask |
| 6 | **The product** | 1680–2160 | 16 | Real console screens in a thin device frame: Overview → Fleet → Replay → Scenarios → Test rig. Callouts: *Live engine health · Fleet readiness · Mission replay · Environmental simulation*. | Slow Ken Burns per screen (scale 1.0→1.06); cut on the music beat; callouts wipe in from the edge |
| 7 | **The payoff** | 2160–2460 | 10 | Horizontal timeline: as-new → wear → health falls → fault begins → **ADVISORY** → failure avoided. A marker slides along it; at *ADVISORY* everything freezes. Card: *"Hours of warning, not seconds."* | Marker eases along a path; at 2340 the world desaturates except the advisory node |
| 8 | **Close** | 2460–2700 | 8 | *Predict the failure. Save the mission.* Then: *Indigenous · Open source · Engine-agnostic*. SIH 2026 · PS 26054 · DRDO, Ministry of Defence. | Line 1 types on; line 2 fades; hold 60f on the lock-up |

### Optional scenes, to reach ~3 minutes

| Scene | Secs | Content |
|---|---|---|
| Vibration order analysis | 20 | Raw vibration → envelope → kurtogram band → the named bearing race. Ends on *"Not 'vibration high'. Which bearing."* |
| Failure probability | 15 | A dial from 0–100 % with the question *"Will it survive the next sortie?"* and a GO / NO-GO stamp |
| Resilience | 15 | Datalink drops, the edge node keeps working, 72-hour buffer fills, reconnects and forwards |
| Impact | 20 | Three columns counting up: social, economic, environmental |

---

## 2. Asset manifest

### A. Already in the repo — capture, do not generate

These are real, which is worth more in a defence submission than anything a
model can invent. I can produce all of these on request.

| ID | Asset | Source | Notes |
|---|---|---|---|
| `R1` | Six diagram PNGs, 2× | `docs/diagrams/*.drawio` → `scripts/preview_diagrams.py` → Playwright | Architecture, working flow, residual, timeline, tech stack, problem/solution |
| `R2` | Seven console screenshots, 2× | `layer5_viz/gcs_console` — Overview, Fleet, Replay, Scenarios, TestRig, Audit, Login | Scene 6 depends on these |
| `R3` | Console screen recordings, 8–10 s each | Same, via Playwright video capture | Better than stills for scene 6 if the dev server runs |
| `R4` | DRDO seal | `layer5_viz/gcs_console/src/assets/drdo-seal.svg` | Already vector |
| `R5` | Real telemetry series | `data/` | Drives the scene-1 trace and any live-looking chart — real numbers, not noise |
| `R6` | Colour tokens | `scripts/gen_diagrams.py` | Ink `#14212F`, accent `#0D8B7C`, layer colours L0–L5, red `#C0392B`, amber `#C87E10` — the film must match the deck |

### B. To generate — images

Aspect **16:9, 1920×1080** unless noted. Style must stay consistent: cool,
desaturated, documentary rather than glossy, no lens flares, no chrome.

| ID | Asset | Used in |
|---|---|---|
| `G1` | MALE UAV in cruise, high altitude, dusk | Scenes 1, 8 |
| `G2` | Aero-piston engine on a test stand, technical | Scenes 2, 4 |
| `G3` | Engine wireframe / digital twin abstraction | Scene 4 |
| `G4` | Ground control station interior | Scene 6 |
| `G5` | Maintenance engineer at an engine, torque wrench | Scene 7 |
| `G6` | Dark background texture, brushed metal | All dark scenes |
| `G7` | Light background texture, paper/blueprint | All light scenes |
| `G8` | Bearing race close-up, spall visible | Optional vibration scene |

### C. To generate — video clips (optional, 4–6 s each)

| ID | Clip | Used in |
|---|---|---|
| `V1` | UAV taking off from a runway, tracking shot | Scene 1 or 8 |
| `V2` | Piston engine running, propeller turning, shallow depth of field | Scene 2 |
| `V3` | Slow orbit around a static engine on a stand | Scene 4 |

### D. Audio

| ID | Asset | Spec |
|---|---|---|
| `A1` | Music bed | 90 s, cinematic tech/defence. Sparse and tense to 0:20, lifts hard at the title, drives through the product section, resolves at 1:22. Needs a clear beat at 1:00–1:12 for the screen cuts |
| `A2` | Low drone | Under scenes 1–2, fades out at the title |
| `A3` | UI ticks | Card entries, counter ticks |
| `A4` | Whooshes | Scene transitions, 3 variants |
| `A5` | Alert tone | Scene 2 red flash. Restrained — one soft pulse, not a klaxon |
| `A6` | Voiceover | Script in section 4. Indian English, measured, calm authority. Not an ad read |

---

## 3. Generation prompts

Written for a photoreal image model. Each has a negative list, because the
failure mode here is glossy stock-photo rendering, which reads as fake.

> **One caution.** Keep every aircraft generic and unmarked. Do not prompt for
> a named platform, and remove any insignia, serial or roundel a model invents.
> An AI-generated aircraft that looks like a real DRDO asset is a problem in a
> defence submission, and it is not a claim the project needs to make.

### G1 — MALE UAV in cruise

```
A medium-altitude long-endurance unmanned aerial vehicle in level cruise,
photographed from a chase aircraft at 6000 metres. Slender high-aspect-ratio
wings, twin tail boom, rear-mounted propeller turning. Late afternoon, sun low
and behind, cold blue haze below, thin cloud deck far under the aircraft.
Muted grey airframe, no markings, no insignia, no serial numbers. Shot on a
long lens, shallow depth of field, slight atmospheric diffusion. Documentary
aerial photography, restrained colour, cool tones.
Negative: logos, text, national markings, roundels, missiles, weapons, glossy
finish, lens flare, HDR, oversaturation, cartoon, 3D render look.
```

### G2 — Aero-piston engine on a test stand

```
A four-cylinder horizontally opposed aero piston engine mounted on a steel
test stand in a clean engineering test cell. Exposed cylinder heads with
cooling fins, visible fuel injection lines, exhaust manifold, sensor cabling
loomed and tied. Neutral grey concrete floor, soft overhead industrial
lighting, one instrumentation rack blurred in the background. Technical
documentation photography, sharp, even exposure, no drama.
Negative: sparks, fire, smoke, dirt, rust, motion blur, neon lighting,
dramatic rim light, text, watermarks, people.
```

### G3 — Digital twin abstraction

```
A translucent wireframe of a piston aero engine floating on a near-black
background, rendered in fine teal-green lines, cylinders and crankshaft
readable as geometry rather than solid surfaces. Faint contour lines suggest
temperature across the cylinder heads. Sparse, technical, restrained — an
engineering visualisation, not science fiction. Large areas of empty dark
space around the engine for text.
Negative: glowing particles, energy beams, blue neon cyberpunk, holographic
UI panels, circuit-board patterns, human figures, text.
```

### G4 — Ground control station

```
Interior of a ground control station for unmanned aircraft. Two operators
seen from behind at a curved desk of matte displays showing muted telemetry
readouts and map views. Dim room, screens the main light source, cool blue-grey
cast. Acoustic panels on the wall, cable management visible under the desk.
Calm and procedural. Documentary photography, natural, slightly grainy.
Negative: futuristic holograms, red alert lighting, glass touch walls, faces
visible, text on screens, dramatic silhouettes, film-set look.
```

### G5 — Maintenance engineer

```
An aircraft maintenance engineer in a plain dark work shirt kneeling beside a
piston aero engine in a hangar, torque wrench in hand, tablet resting on the
cowling beside them. Morning light through a hangar door, long soft shadows.
Focused and unhurried. Documentary photography, natural colour, shallow depth
of field on the hands.
Negative: staged smiling, corporate stock photography, hard hat and hi-vis
cliché, sparks, dramatic lighting, text, logos.
```

### G6 — Dark background texture

```
Seamless dark surface texture for a video background: brushed anodised
aluminium in near-black charcoal, very fine directional grain, matte, lit by a
broad soft source from the upper left so the tone falls off gently to the lower
right. Almost no contrast. No focal point.
Negative: rivets, panel lines, scratches, logos, vignette, pattern repetition,
carbon fibre weave, high contrast.
```

### G7 — Light background texture

```
Seamless light surface texture for a video background: cold white technical
paper with a barely visible blueprint grid, faint paper fibre, evenly lit,
almost flat. No focal point, nothing to read.
Negative: coffee stains, folds, torn edges, drawings, text, heavy grid lines,
warm yellow tone, vignette.
```

### G8 — Bearing race (optional)

```
Macro photograph of a disassembled rolling-element bearing outer race lying on
a clean grey bench, one small spall visible on the raceway surface as a shallow
irregular pit. Even diffuse lighting, no reflections, forensic clarity, shallow
depth of field falling off at the edge of the frame.
Negative: heavy rust, grease, dirt, dramatic lighting, tools, hands, text.
```

### V1–V3 — video clips

```
V1: Tracking shot alongside an unmarked medium-altitude long-endurance UAV
lifting off a runway at dawn, camera moving with the aircraft, gear retracting.
Long lens, heat shimmer over the tarmac. 5 seconds, steady, no cuts.

V2: Close shot of a running four-cylinder aero piston engine on a test stand,
propeller turning, slight vibration visible in the frame. Shallow depth of
field on the cylinder heads. 5 seconds, locked off.

V3: Slow orbit around a static aero piston engine on a stand in a test cell,
even lighting, camera moving right to left at constant speed. 6 seconds.

All three: documentary, muted colour, no music, no text, no people, no
markings on the aircraft.
```

### A1 — music

```
Instrumental cinematic technology score for a defence engineering film, 90
seconds. Opens sparse and tense: low sustained strings, a slow pulse, space
between the notes. At 20 seconds a clear lift into a driving mid-tempo section
with a steady percussive pulse around 100 BPM, restrained and purposeful
rather than triumphant. Holds through to 72 seconds, then resolves into a
sustained calm close. Serious, credible, no vocals, no orchestral hits, no
dubstep drop, no cheerful corporate ukulele.
```

---

## 4. Voiceover script

Timed to the scene plan. Roughly 150 words, which is comfortable at a measured
pace over 90 seconds.

> **(0:00)** An aero piston engine, six thousand metres up, is beginning to
> fail. Nothing on board knows it yet.
>
> **(0:08)** Engine monitoring today works on fixed limits. A reading crosses a
> line, an alarm sounds — and by then the damage is done.
>
> **(0:20)** So we built a digital twin.
>
> **(0:28)** A physics model of the same engine, as new, running the same
> mission, second by second. Every reading is compared against what a healthy
> engine would do at that exact altitude, load and temperature. The difference
> between the two is the health of the engine.
>
> **(0:42)** Six layers turn that difference into a decision. From the CAN bus
> on the airframe, up through physics, AI and the twin, to the operator.
>
> **(0:56)** Which fault. How severe. How long you have. And the answer a
> commander actually needs — will it survive the next sortie.
>
> **(1:12)** The warning arrives in hours, not seconds.
>
> **(1:22)** Predict the failure. Save the mission.

---

## 5. Remotion structure

```
src/
  Root.tsx              registerRoot, one <Composition> 1920x1080 @30fps, 2700f
  Video.tsx             <Series> of the eight scenes, in the frame ranges above
  scenes/
    ColdOpen.tsx        SVG path draw driven by real telemetry from R5
    Problem.tsx         card chain + stamp
    Title.tsx           mask-wipe title, DRDO seal
    Residual.tsx        the split-to-centre comparison — the key scene
    Architecture.tsx    six layers, pulse travelling up
    Product.tsx         console screens in a device frame
    Timeline.tsx        marker along a path, freeze on advisory
    Close.tsx           lock-up
  components/
    Card.tsx            one card, spring entry, used everywhere
    Counter.tsx         interpolate + round, for the temperatures
    DeviceFrame.tsx     thin bezel around console captures
    Pulse.tsx           gradient sweep on a mask
  theme.ts              the R6 colours, one source of truth
  assets/               R1–R5, G1–G8, V1–V3, A1–A6
```

**Rules that keep it from looking amateur**

- Motion comes from `spring()`, not `interpolate()` with linear easing.
  Linear movement is the single clearest tell of a first Remotion project.
- Nothing fades in from opacity 0 alone. Combine opacity with a small
  translate or scale — 12–20 px, or 0.96→1.0.
- Stagger everything. Elements in a group enter 6–12 frames apart, never
  together.
- One accent colour doing the work: `#0D8B7C`. Red only for the failure beat.
- Text is never on screen for less than 40 frames.
- Transitions carry meaning: the white flash at frame 600 is the turn from
  problem to solution, so it happens exactly once.
- Captions burned in for the whole film. Most people will watch it muted.

---

## 6. Order of work

1. Capture `R1`–`R6` from the repo — I can do this now.
2. Generate `G1`–`G7`, review, regenerate the ones that look like stock photos.
3. Get `A1` and cut the scene timings to its beats before animating anything.
4. Build scenes 4 and 6 first. If the residual scene and the product scene
   work, the film works; the rest is connective tissue.
5. Record `A6` last, against the finished picture.
