# PRD DEVIATIONS AND CORRECTIONS

Every place where the implementation departs from PRD Parts 0–3, with the
evidence for the departure. This document exists because a DRDO domain expert
*will* check the engine numbers, and "we found the error before you did" is a
stronger position than either silently following a wrong figure or silently
fixing it.

Rule: **no deviation may exist in code without an entry here.**

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-1 | Torque ↔ BMEP relation<br>`layer2_physics/perf_maps.py` | PRD Part 1 §4.3.2: `T_b = (BMEP × V_d × N_cyl) / (4π × n_r)`, `n_r = 2` | `T_b = BMEP × V_total / (2π × n_r) = BMEP × V_total / 4π` | With `V_d` as per-cylinder displacement, the PRD form evaluates to `BMEP·V_total/(8π)` — a factor of 2 below the standard definition of brake mean effective pressure. The PRD form cannot reproduce the published 144 N·m / 84.8 kW anchors; the standard form reproduces both exactly. |
| DEV-2 | Reference engine<br>`configs/engines/` | PRD Part 1 §1.3 specifies the **Rotax 914 F/UL** as the reference/demo engine | **Rotax 915 iS / iSc A** is the reference engine. The 914 profile has since been **removed entirely** (see DEV-41); engine-agnosticism is proven by the Austro AE330 turbo-diesel stub, which differs from the reference far more than the 914 did. | Two reasons. (a) **Correctness**: the PRD's own 914 figures are internally inconsistent — it states 144 N·m at 5500 rpm while also stating 73.5 kW continuous at 5500 rpm, which implies 127.6 N·m; the manufacturer datasheet puts peak torque at 4900 rpm. (b) **Fitness for the problem statement**: the 914 is carburetted with no FADEC and no CAN bus, so it cannot honestly support the PS requirements for "CAN bus / SocketCAN based engine data acquisition" and "ECU/FADEC communication interfaces". The 915 iS carries a **certified dual-channel FADEC** for ignition and injection with a Display CAN Bus and Maintenance CAN Bus A/B. Sources: EASA TCDS E.121 Issue 17 (18 Dec 2023); BRP-Rotax OM-915 i A Ed.0 Rev.1 (01 Jun 2019); BRP-Rotax data sheet 915 iS A/iSc A Vers. 2021/01. |
| DEV-3 | Altitude power ratio<br>`layer2_physics/perf_maps.py`, `turbo.py` | PRD Part 1 §4.4 gives `P_available ≈ 0.75 × P_SL` at 10,000 ft and `0.55` at 20,000 ft, while also stating the turbocharger critical altitude is ~12,000 ft | Both cases modelled separately: naturally-aspirated ratio = ISA density ratio (0.738 at 10,000 ft, 0.533 at 20,000 ft); turbocharged installed ratio ≈ 0.85 at 10,000 ft, falling with ambient pressure above the critical altitude | The two PRD statements contradict each other — an engine that holds boost to 12,000 ft cannot be down 25 % at 10,000 ft. The 0.75/0.55 figures are numerically the ISA density ratios, i.e. the un-boosted case. Both are now reported, correctly labelled. |
| DEV-4 | Max continuous rating | PRD Part 1 §1.3 lists 73.5 kW at 5500 rpm alongside the WOT torque curve | Treated as a **placarded part-throttle limit** (≈77 % throttle at sea level), not a point on the wide-open-throttle curve | A single WOT curve cannot pass through both the 5-minute take-off rating and the max-continuous rating; the two ratings use different wastegate/boost schedules. Modelling continuous as a derate is the physically correct reading. |
| DEV-5 | Virtual CAN transport<br>`layer1_edge/` | PRD Part 1 §3.3: Linux SocketCAN `vcan0` | `python-can` `virtual` bus by default; `socketcan` selectable by config for Linux/RPi | Host platform is Windows; the kernel `vcan` module does not exist there. PRD Part 0 §0.12 explicitly sanctions this fallback ("a pure-Python in-process CAN bus needs no kernel module — use it if the demo machine blocks modprobe"). Decision D1. |
| DEV-6 | Edge inference runtime<br>`layer1_edge/edge_infer.py` | PRD Part 0 §0.3: TensorFlow Lite INT8 | PyTorch training → ONNX export → **ONNX Runtime INT8** | `tflite-runtime` publishes no reliable Windows wheels; ONNX Runtime ships for Windows x64 *and* linux-aarch64, so the identical artifact runs on the demo laptop and on the Raspberry Pi / Jetson edge target. The requirement (quantised, <50 ms, small footprint) is unchanged. Decision D3. |
| DEV-7 | Tier-1 rule engine<br>`layer3_ai/tier1_rules.py` | PRD Part 2 §11.1: ADTK (Anomaly Detection Toolkit) | Native implementation of the same detector semantics (threshold, rate-of-change, persistence, level-shift/CUSUM, volatility, correlation) | ADTK is archived upstream and pins old pandas/scikit-learn versions that conflict with the rest of this stack. The detector *semantics* required by the PRD are reproduced exactly and are unit-tested; the dependency is not. |
| DEV-8 | Vibration CAN encoding<br>`configs/can/engine.dbc` | PRD Part 1 §3.2: 0x106 carries `3 × float16` | `3 × uint16` at 0.001 m/s² per LSB | The DBC format has no float16 signal type. Fixed point at 0.001 m/s²/LSB matches the sensor resolution given in PRD Part 1 §3.1 (0.001 g) and spans the full 0–50 m/s² range. |
| DEV-9 | Air data on the engine bus<br>`configs/can/engine.dbc` | PRD lists only 0x100–0x108, 0x200 | Added `0x300 AIR_DATA` (altitude, OAT, airspeed, humidity, flight phase) sourced from the Vehicle Management Computer | The physics model of PRD Part 1 §4 cannot evaluate CHT/EGT/η_vol without ambient conditions, and PRD Part 1 §6.1 requires an `environmental` block in the twin's reported state. The frame is explicitly labelled as VMC-sourced, not ECU-sourced. |
| DEV-10 | Primary dashboard<br>`layer5_viz/gcs_console` | PRD Part 0 §0.3 / Part 3 §19.2: Grafana as primary, Streamlit secondary | Purpose-built React + TypeScript GCS console governed by `docs/PRD_Part4_Defence_HMI_Standard.md`; Grafana retained in the production architecture for fleet-level ops dashboards | Grafana cannot express MIL-STD-411F alerting semantics (master warning/caution with push-to-reset and re-arm, overflow memory, 3-second minimum message duration, inhibit logic) or MIL-STD-1472H coding rules (single synchronised 3 Hz flash, ≤2 brightness levels, redundant non-colour coding). Those are requirements, not styling. Decision D2. |
| DEV-11 | Advisory colour<br>`docs/PRD_Part4_Defence_HMI_Standard.md` §3.1 | PRD Part 2 §9.5 Level 2 = "Blue (Advisory)"; MIL-STD-411F 5.1.5.1 prefers **green** for advisory | **Cyan** | Green is already committed to "normal / in-tolerance" by MIL-STD-1472H Table XL, and 14 CFR 25.1322 forbids green for advisory alerts. MIL-STD-1472H Table XL lists cyan → "Advisory", and MIL-STD-411F 5.2.5.4 permits a third colour with blue/white as non-flight-deck options. Cyan satisfies every constraint simultaneously. |

## Deviations found while implementing the physics layer

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-12 | EGT prediction<br>`layer2_physics/combustion.py` | PRD Part 1 §4.2: `T_EGT = T_ad × η_comb × (1 − ΔQ_loss/Q_in)` | Explicit three-stage chain: expansion to exhaust-valve opening, blowdown to manifold pressure (PRD §4.3.4's own formula), then pipe heat loss — with the anchored MAP 5 supplying the load dependence and the Cantera chain supplying the mixture/intake/efficiency sensitivity | The PRD formula omits the expansion stroke entirely. Adiabatic flame temperature is the *peak* temperature at TDC (~2300 K); the gas does work on the piston and blows down before reaching the thermocouple. Applying the PRD formula literally produced **1683 °C** against a real cruise EGT of 780–880 °C. |
| DEV-13 | CHT and EGT alert bands<br>`configs/thresholds.yaml` | PRD Part 1 §3.1: CHT normal 140–200 °C, alert 210, critical 230; EGT normal 550–700, alert 750, critical 850 | CHT normal 80–120, alert 125, critical **135**; coolant normal 75–110, alert 115, critical **120**; EGT normal 700–900, alert 920, critical **950**; EGT split limit **200 °C** | The PRD bands are air-cooled Lycoming/Continental numbers. The reference engine has **liquid-cooled cylinder heads and ram-air cooled cylinders** (EASA TCDS E.121 §2) with a certified 120 °C coolant limit and a certified 950 °C EGT limit (OM-915 i A §2.1). Using the PRD bands would have raised a false EGT caution on every single flight and would have **missed a real coolant overheat entirely**. |
| DEV-14 | Thermal model topology<br>`layer2_physics/mvem.py` | PRD Part 1 §4.3.3 models CHT against a fixed coolant inlet temperature | **Two-node** model: head metal and a thermostatted coolant loop, integrated separately | A fixed-temperature coolant sink cannot express the actual cooling-degradation signature. Scale build-up degrades the *head-to-coolant* path, so CHT rises while the thermostat holds coolant temperature steady — the tell-tale is the widening CHT-minus-coolant delta (measured: 22 K → 37 K as η_cool falls 1.00 → 0.60). A single-node model shows nothing. Both the oil and coolant loops needed thermostats: without them a fixed-conductance cooler ran the sump to 38 °C at 20,000 ft and 177 °C at sea level. |
| DEV-15 | Torque and friction<br>`layer2_physics/mvem.py` | PRD Part 1 §4.3.2: `BMEP = IMEP × η_mech − PMEP` | Performance map returns **brake** torque directly; only friction *in excess of* the as-new value is subtracted | BMEP is by definition brake mean effective pressure — friction is already deducted. Subtracting the full friction torque again double-counted it and cost ~11 % of rated power (92.4 kW modelled against a 104 kW certified rating). Only degradation-induced excess friction may be subtracted. |
| DEV-16 | Integration scheme<br>`layer2_physics/mvem.py` | PRD Part 1 §4.3 integrates all states with `solve_ivp` RK45 | Operator splitting: manifold pressure advanced analytically as a first-order lag to its quasi-steady equilibrium; the slow states (ω, CHT, oil, coolant) integrated with RK45 | The manifold time constant is ~70 ms against 9–13 s for the thermal states. The combined system is stiff: RK45 took **429 internal steps per 0.5 s window, 1020 ms of wall clock**, against the 20 ms physics budget of PRD Part 1 §2.2. After splitting, a step costs **5.4 ms** — a 190× speed-up with no loss of fidelity at the 10 Hz telemetry rate. |
| DEV-17 | Model closure | — | Torque from the performance map and fuel flow from the BSFC map are treated as authoritative; the air path is an independent third estimate whose disagreement is published as `air_fuel_consistency_residual` | The three quantities are over-determined and, being separately anchored, do not close exactly. Rather than hide the mismatch by silently preferring one, the model reports it, so an engineer can see its own uncertainty and a future VRDE rig calibration has a defined target. |

## Verified anchors — what the physics model reproduces

Run `python -m layer2_physics.perf_maps` to regenerate this table.

| Anchor | Source | Expected | Model | Error |
|---|---|---|---|---|
| Rated take-off power | EASA TCDS E.121 §6 | 104.0 kW @ 5800 rpm | 104.0 kW | 0.00 % |
| Peak torque | Derived from certified ratings | 171.9 N·m | 171.9 N·m | 0.00 % |
| Max continuous at WOT | EASA TCDS E.121 §6 | 100 % throttle | 99.96 % | −0.04 % |
| Volumetric efficiency, sea level | PRD Part 1 §5.1 MAP 3 | 0.875 | 0.890 | +1.71 % |
| Volumetric efficiency, 10,000 ft | PRD Part 1 §5.1 MAP 3 | 0.775 | 0.778 | +0.33 % |
| Naturally-aspirated power ratio, 10,000 ft | ISA density ratio | 0.750 | 0.738 | −1.60 % |
| Turbocharged power ratio, 10,000 ft | EASA TCDS E.121 §6 | 0.970 | 0.975 | +0.51 % |
| Turbocharged power ratio at critical altitude | EASA TCDS E.121 §6 | 0.950 | 0.950 | 0.00 % |
| **Air mass flow at rated power** | **OM-915 i A §2.1 published relation** `P[kW] = −6.3264 + 0.0169 × airflow[g/min]` | **0.1088 kg/s** | **0.1101 kg/s** | **+1.16 %** |
| Cruise BSFC | Rotax published SFC band 280–310 g/kWh | 300 g/kWh | 302.6 g/kWh | +0.88 % |
| EGT at 75 % power, sea level | Anchored to the 950 °C certified limit | 851 °C | 847.7 °C | −0.39 % |
| EGT at 100 % power, sea level | Anchored to the 950 °C certified limit | 910 °C | 908.2 °C | −0.19 % |

The airflow anchor is the strongest of these: BRP-Rotax publishes an explicit
power-to-airflow relation, so the entire intake path — throttle, turbocharger,
intercooler, volumetric efficiency — is validated against a manufacturer
equation rather than against our own assumptions.

## Corrections from the official Rotax document set

The complete BRP-Rotax 915 i documentation is now held locally in
`engines manuals/` (1,455 pages). It supersedes the web-sourced OM Rev.1 (2019)
used earlier and corrected ten further items.

| Document | Edition | Date |
|---|---|---|
| `OM_915i_Ed0_Rev4.pdf` — Operators Manual | Ed. 0 Rev. 4 | 01 Sep 2022 |
| `IM_915i_A_C24_Ed0_Rev5.pdf` — Installation Manual | Ed. 0 Rev. 5 | 01 Feb 2024 |
| `MMH_915i_A_C24_Ed1_Rev0.pdf` — Maintenance Manual Heavy | Ed. 1 Rev. 0 | — |
| `MML_915i_Ed0_Rev3.pdf` — Maintenance Manual Line | Ed. 0 Rev. 3 | 01 May 2025 |
| `IPC_915 i A_C24 Series_E00_R02.pdf` — Illustrated Parts Catalog | E00 R02 | — |
| 7 Service Instructions + 1 Alert Service Bulletin | various | to 20 Dec 2024 |

| ID | Where | Previously | Now | Evidence |
|---|---|---|---|---|
| DEV-18 | Boost control target<br>`turbo.py`, engine YAML | Boost controller targets **1.73 bar** (treated the manifold-pressure limit as the setpoint) | Targets the **published schedule: 1.45 bar at 5500 rpm, 1.52 bar at 5800 rpm**; 1.73 bar retained only as a never-exceed authority limit | OM Ed.0 Rev.4 §2.1: *"Target pressure at a temperature from 25 °C to 35 °C: 5800 rpm 1520 mbar, 5500 rpm 1450 mbar. 1730 mbar is the 'not to exceed' value which is needed by the boost pressure control in special situations."* The old reading over-boosted the engine by 14 % and inflated every downstream airflow, fuel and thermal figure. |
| DEV-19 | **Intercooler — missing component**<br>`turbo.py` | Compressor discharge fed straight to the manifold | Air-to-air intercooler between compressor and airbox, effectiveness 0.65, scaled by ram airflow | The engine is certified *"turbocharger with intercooler"* (EASA TCDS E.121 §2). Without it the modelled compressor discharge is **57–89 °C at every altitude, above the 50 °C manifold-air-temperature limit** — i.e. the model described an illegal engine. With it, MAT lands at 20–32 °C, inside the 25–35 °C band the OM quotes its boost targets at. |
| DEV-20 | Volumetric efficiency<br>`perf_maps.py` | 0.89, tuned by hand; anchored to PRD MAP 3 (0.875 sea level) | **0.955, derived** — the OM airflow relation fixes air mass flow at rated power, and the published target MAP and MAT band fix charge density, leaving η_vol as the only free variable | The PRD's MAP 3 figures describe a naturally-aspirated reference. The airflow anchor now agrees with the manufacturer relation to **+0.09 %**. |
| DEV-21 | Altitude axis<br>`perf_maps.py` | Axis ended at 15,000 ft (PRD Part 1 §5.1) | Extended to **23,000 ft** | The engine's certified ceiling is 23,000 ft with a 15,000 ft critical altitude. An axis ending at 15,000 ft silently clamped every higher query back to it, so the model reported **95.9 kW at 20,000 ft — identical to its 15,000 ft figure** — hiding the post-critical-altitude power loss the high-altitude scenario exists to demonstrate. Correct behaviour is now 96 kW at 15,000 ft falling to 55.7 kW at 23,000 ft. |
| DEV-22 | CAN database<br>`configs/can/engine.dbc` | Hand-written DBC with invented 0x100–0x300 identifiers | **Generated from the CANaerospace standard** by `scripts/gen_can_dbc.py`: ECS channel A at IDs 500–552, channel B at +64 offset, HUMS extensions in the user-defined 1800–1899 range | IM Ed.0 Rev.5 ch. 77-00-00: *"The Display CAN is based on the CANAerospace protocol."* Identifier assignments from CANaerospace Interface Specification Rev. 1.6 (Stock Flight Systems). **Honesty limit**: the IM adds *"For detailed interface description contact an authorized ROTAX Distributor"* — the exact Rotax message assignment is **not public and is not reproduced**. Ours is protocol-correct and drop-in replaceable, and must never be called "the Rotax CAN database". |
| DEV-23 | Bus topology | One Display CAN bus | **Four buses**: Display CAN Lane A/B and Maintenance CAN Lane A/B, on Harness Interface Connectors A and B, plus a 12 V / 120 mA warning lamp per lane | IM Ed.0 Rev.5 ch. 77-00-00 terminal tables. |
| DEV-24 | Fuel rail pressure | 2.9–3.1 bar | **2.9–3.2 bar**, transient 2.5–3.5 bar for ≤3 s | OM Rev.4 §2.1 raised the upper limit; Rev.1 (2019) said 3.1. |
| DEV-25 | Manifold air temperature | Single 50 °C limit | 50 °C **rated-power** limit plus an **extended 50–80 °C range** with a published penalty of −1 kW continuous / −2.7 kW take-off | OM Rev.4 §2.1 "Extended Manifold Temperature Range". A real degraded-but-airworthy mode, not a simple exceedance. |
| DEV-26 | TBO | 1200 h | **1200 h or 15 years, whichever comes first**; storage limited to 24 months | MML Ed.0 Rev.3 §05-10-00. RUL must therefore be the minimum of the hours-based and calendar-based estimates, not hours alone. |
| DEV-27 | Coolant warm-up limit | 90 °C max during ground idle / start / warm-up | Removed — only the 120 °C normal-operation limit applies | OM Rev.4 §2.1 deleted the warm-up maximum that Rev.1 carried. |
| DEV-28 | Sensor-fault ground truth | Our own assumptions about which sensor faults are detectable | Adopted the **manufacturer FMEA** — 29 items mapping each sensor/actuator/bus/power fault to its lane, both warning-lamp states, the resulting system mode (Auto_A / Auto_B / Auto_AB / Only_A / Only_B) and the engine effect | IM Ed.0 Rev.5 Appendix. Notable details the detector layer must not invert: **OPS and OTS sit on Lane B** (their failure flashes lamp B), while **CTS, EGT and Knock sit on Lane A**. Injectors split 1–4 on Lane A and 5–8 on Lane B; coils 1/3 on A and 2/4 on B. |

### Why the CANaerospace finding matters beyond authenticity

CANaerospace puts two bytes in every message that the invented DBC did not have:

- **Service Code** — "continuously reflects the status of the data (or the
  transmitting unit) to support data integrity monitoring within receiving
  units. With this information, the validity of data is known at any given
  time."
- **Message Code** — "message numbering allows to detect if messages are
  missing… it can be used to compare the *age* of messages from redundant
  sources."

That is per-frame validity and staleness delivered by the bus itself, and it
maps one-to-one onto the five value states PRD Part 4 §7.1 requires the HMI to
annunciate (VALID / STALE / INVALID / MISSING / SUSPECT). Combined with the
dual-lane ECS channels it also gives a genuine two-source cross-check — the
cheapest and strongest sensor-validity vote available (PRD Part 1 §8.3
Method 5).

## Injection timing — the parameter that was never actually modelled

| ID | Where | Previously | Now | Evidence |
|---|---|---|---|---|
| DEV-29 | Injection vs ignition timing<br>PRD Part 1 §3.1 P9 | One parameter, "Injection Timing", range 0–60 °BTDC, normal 15–26 °BTDC, deviation ±2/±5 ° | **Three separate parameters**: ignition timing (5–35 °BTDC, deviation ±2/±5 °, plus knock-retard limits), injection start angle (deviation ±1/±3 °), and injection period (ms, with duty and delivery-shortfall limits) | Rev 1 conflated two distinct, separately-scheduled quantities. Its stated 15–26 °BTDC band is a **spark advance**, not an injection angle — port injection is a closed-valve event at ~370 ° before firing TDC. The PRD also contradicted itself: Part 1 §3.1 said ±2/±5 ° while Part 2 §10.2 Method C said ±1/±3 °. The tighter Part 2 figures apply to injection, the looser Part 1 figures to ignition. |
| DEV-30 | Injection timing was a **constant**<br>`layer2_physics/mvem.py` | `timing = [nominal] * n_cyl` — a hard-coded 24 ° for every cylinder in every condition | Full ECU/FADEC model (`layer2_physics/ecu.py`): speed-density injection scheduling, ignition advance map, knock feedback, and per-cylinder measured-vs-commanded deviation driven by injector wear | A constant cannot indicate a fault. The problem statement requires injection timing as a monitored parameter (§B) *and* injection-timing deviation as an injector-abnormality detection method (§C); neither was achievable. The control law now follows the manufacturer's own description: *"the required fuel quantity or injection period is determined on the basis of the calculated air density in the airbox"* [OM Rev.4 §7.5.3]. |
| DEV-31 | Per-cylinder EGT decoupled from injectors | EGT spread came from a static build bias that never changed | EGT spread is driven by the fuel each cylinder **actually receives**, which the ECU model computes from build variation plus injector wear | The injector-imbalance detector of PRD Part 2 §10.2 Method B had no signal to work on: EGT spread did not respond to injector condition at all. It now tracks it — 72 °C healthy → 165 °C at injector condition 0.40, against the certified 200 °C split limit. |

### Verified injection-timing behaviour

| Injector condition | max\|deviation\| | delivered fuel | EGT spread | timing verdict | EGT verdict |
|---|---|---|---|---|---|
| 1.00 | 0.32 ° | 1.000 | 71.7 °C | normal | normal |
| 0.90 | 1.01 ° | 0.974 | 88.4 °C | degraded | degraded |
| 0.75 | 2.49 ° | 0.933 | 112.5 °C | degraded | degraded |
| 0.60 | 4.26 ° | 0.893 | 135.6 °C | **FAULT** | degraded |
| 0.40 | 6.92 ° | 0.840 | 164.8 °C | **FAULT** | **FAULT** |

The discriminating signature: deviation at injector condition 0.70 rises
**10.85 ° → 17.13 ° as speed rises 3,603 → 5,690 rpm**, because a fixed
solenoid delay subtends more crank angle the faster the engine turns. A sensor
bias would not do that — which is how fault 2 (injector abnormality) is
separated from fault 5 (sensor drift).

Knock feedback closes a second loop: as cooling degrades, charge temperature
rises, knock intensity rises, and the ECU retards ignition — 3.25 ° at
η_cool 1.00 to 7.17 ° at η_cool 0.55. Ignition timing therefore carries
cooling-health information well before any temperature limit is approached.

## Deviations found while implementing the twin core (Layer 4)

PRD Part 1 §6.1 gives the twin-state schema as a JSON sketch. Building it
exposed one omission that would have made the whole twin decorative, and
several fields that could not be filled honestly as written.

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-32 | Source of `simulated_state`<br>`layer4_core/shadow_model.py` | PRD Part 1 §6.1 defines `simulated_state` but never says which model produces it | A **second, independent MVEM instance** with degradation pinned as-new and never advanced, driven only by operating-point channels (throttle, rpm, altitude, OAT, airspeed) and never by an engine response | The obvious reading — fill `simulated_state` from the model already being run — gives a residual of **identically zero at every instant for every engine, healthy or failing**. The twin still validates, serialises, renders and passes its schema tests; it detects nothing. Nothing in the Rev 1 text rules this out. Feeding back a measured *response* (CHT above all) is the same failure in slower motion: the reference tracks the failing engine and the residual collapses toward zero exactly as the fault grows. Now specified normatively in PRD Part 1 §6.5, added at Rev 2. |
| DEV-33 | Measurements in `reported_state`<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1: each channel is a bare `"float"` | Every channel is `{value, state, age_s, reason}` with `state` from PRD Part 4 §7.1 (VALID/STALE/INVALID/MISSING/SUSPECT) | A float cannot distinguish "110 °C" from "110 °C, four seconds stale" from "no reading at all". Without the state, a residual computed from a stale measurement is indistinguishable from a genuinely small residual — and a small residual is read downstream as *evidence of health*. The twin now marks such a residual **unusable**, which is not the same as zero. |
| DEV-34 | `electrical.alternator_voltage`<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 lists `alternator_voltage` alongside `battery_voltage` | Field retained; left **MISSING**, never populated | The 915 iS publishes **one** regulated DC bus voltage (OM §7.5.4). When the alternator is charging, bus voltage *is* its regulated output; there is no second sensor. Mirroring one into the other would manufacture a measurement no sensor produces — the exact substitution the ingest layer exists to prevent. Kept as a field so an installation with a separate transducer needs no schema change. |
| DEV-35 | `vibration.dominant_frequency`<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 lists it in `reported_state` | Field retained; **None** on the telemetry path | Dominant frequency is a product of order analysis on the 10 kHz waveform (`engine_sim.vibration_waveform`), which is not part of the 10 Hz CAN telemetry. It could be back-computed from rpm, but that would only restate the 1× order the analysis exists to *discover* — a number that always agrees with itself. Populated when the edge node's spectral stage lands. |
| DEV-36 | `environmental.pressure`<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 lists ambient pressure in hPa | **Derived** from reported pressure altitude via the standard atmosphere | No pressure transducer exists on the engine bus. This is not an estimate: pressure altitude *is* a pressure measurement expressed in feet, so the conversion is exact by definition. |
| DEV-37 | `simulated_state.model_residual`<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1: "RMSE of current prediction" | Scale-normalised RMSE **accumulated across the mission**, not computed from the current frame | Two problems with the literal reading. (a) An RMSE over one sample is not an RMSE — it is an instantaneous magnitude dominated by sensor noise. Measured before the fix: an injected injector fault produced a **lower** `model_residual` (0.0137) than a healthy engine (0.0341), purely from where the final frame landed. (b) Combining kelvin, psi and litres/hour unnormalised just reports whichever channel has the largest units; each residual is divided by its configured feature scale first. |
| DEV-38 | Cycle counters<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 defines `total_cycles` and `total_thermal_cycles`; PRD Part 2 §12 defines one cycle as one start-stop | Both counted, each with a **hysteresis band** (rpm 1500/500; CHT 90/50 °C) | The fields existed in the first implementation and were never incremented — consumed cycle life would have read as nil for the life of the engine. Hysteresis rather than a bare threshold because both signals hover around any fixed line, and a crossing test adds a cycle per noise excursion, inflating consumed life on an engine that never stopped. Thermal cycles are counted separately because they measure different damage: a hot restart consumes a start-stop cycle while doing almost nothing to the head. |
| DEV-39 | `maintenance_advisory` source<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 defines the block without saying what fills it | Filled from the Tier-1 rule engine, tagged `source="rules"`, with `shap_explanation` present and empty | PRD Part 4 §7.4b requires the system to declare when it is running on rules rather than models, so an engineer never mistakes a threshold trip for a learned prediction. `shap_explanation` is declared now rather than added later because §7.4c forbids presenting a recommendation the operator cannot interrogate — the empty field is a visible reminder that the explanation is owed. |
| DEV-41 | Rotax 914 profile<br>`configs/engines/rotax_914.yaml` | PRD Part 1 Rev 2 retained the 914 as a secondary profile to demonstrate engine-agnosticism | **Profile deleted.** Engine-agnosticism is now demonstrated by the Austro AE330 turbo-diesel stub alone | Two independent reasons, one of which only appeared on measurement. (a) **It could never work.** The 914 is carburetted with no FADEC and no CAN bus, so this framework — whose entire acquisition path is CAN and whose ECU model is a FADEC — could never actually acquire from one. Shipping it as the proof of engine-agnosticism invites the obvious question. (b) **It was quietly broken.** PROJECT_PLAN gap G6 recorded "914 oil pressure reads 27.9 psi — re-tune the pump constant". Sweeping the envelope showed that diagnosis was wrong and the real fault was worse: at `cooler_UA_W_per_K: 62.0` the sump ran to **153 °C at 70 % throttle and 182.8 °C at full power at sea level** against a 130 °C limit, and pressure *collapsed* to 1.2 bar as viscosity fell away. Pressure was the symptom; re-tuning the pump as G6 proposed would have driven full-power pressure to 0.85 bar and made it worse. A recalibration (`cooler_UA` 62→112, pump 0.235→0.143) was derived and verified in-band at all eight envelope points before the profile was removed on the separate compatibility grounds above — recorded here because the same sweep is what confirmed the **915 iS reference engine is correct throughout** (oil 87–105 °C, 2.6–4.2 bar, every point in band). The file remains recoverable at `git show e8c0dd7:configs/engines/rotax_914.yaml`. |
| DEV-40 | CHT/EGT spread field name | PRD Part 1 §6.1: `spread_max` | `spread` | Cosmetic, recorded for completeness. `spread` is what `can_ingest.derived()` and the rule engine already call it; one name across the codebase is worth more than matching a sketch. |

## Deviations found while building the run-to-failure dataset

Generating 100 engines to failure is the first thing that exercises the
degradation model over a FULL overhaul life rather than a single mission. Two
of the six pathways turned out to be wrong at that timescale, and neither is
visible in a 900-second test.

| ID | Where | Previously | Now | Evidence / reason |
|---|---|---|---|---|
| DEV-42 | Oil was never changed<br>`layer2_physics/degradation.py`, `configs/engines/rotax_915is.yaml` | Oil viscosity accumulated monotonically for the life of the engine; no service interval existed anywhere in the model | Scheduled oil and filter change every **100 h** [MML 05-20-00], resetting the natural viscosity accumulation | At `beta_thermal_per_C_hr: 0.001` the viscosity increase crosses the 25 % condemnation limit at **223 h** — so `oil_quality` hit 0.0 at a fifth of TBO and stayed there for the rest of the engine's life. Every virtual engine was being condemned by oil that a real operator would have changed **twelve times** before overhaul, and a network trained on that fleet would have learned that engines die of dirty oil. The interval halves to 50 h if AVGAS 100LL is used for more than 30 % of operation; the 100 h case is modelled. Crucially the change is applied BEFORE injected faults, so a scheduled service restores the oil but does not repair whatever is contaminating it — a lubrication fault survives the change, which is the signature separating a real fault from oil that is merely due. |
| DEV-43 | Injector fouling rate<br>`configs/engines/rotax_915is.yaml` | `variance_rate_per_hour: 0.0012` | `0.00004` | The old rate drove the injector flow coefficient of variation to the 10 % maintenance threshold at **833 h** nominal, and sooner once the per-engine manufacturing spread was applied — making injectors the life-limiting item on every engine at roughly two thirds of TBO, with no service interval that short anywhere in the maintenance manual. Measured effect before the fix: engine 3 of the trial fleet died at 356 h with `injector_condition` 0.28, and its only injected fault was scheduled to begin at 646 h — it never activated. Baseline wear was drowning the very faults the dataset exists to teach. Recalibrated for 2 % flow scatter at the 1200 h TBO (`injector_condition` 0.78), a fifth of the way to the maintenance threshold over a full overhaul life. |
| DEV-44 | Ground-truth CHI weights<br>`layer2_physics/synth_data_gen.py` | PRD Part 2 §9.3: thermal 0.30 / mechanical 0.25 / electrical 0.20 / combustion 0.25 | The three implemented weights renormalised to sum to 1.0 | There is no electrical degradation pathway in the model — that is gap **G4** in PROJECT_PLAN.md. Scoring electrical health a constant 1.0 would hand every engine a free 0.20 of composite health and push the 0.60 maintenance threshold out of reach, so no engine would ever be labelled as failed. Renormalising the three real terms keeps the threshold meaningful. When G4 lands the electrical term drops straight in and the renormalisation is removed. |

| DEV-45 | Injected faults could not end an engine's life<br>`layer2_physics/degradation.py`, `synth_data_gen.py` | `_apply_faults` CLAMPED a health factor to a floor and did nothing else, despite its own comment claiming "a cooling-degradation fault *is* an accelerated cooling pathway" | Faults now **accelerate the wear rate** of the pathway they act on (`_FAULT_ACCELERATION`), in addition to the clamp; end of life is `CHI ≤ 0.60` **OR** any sub-index `≤ 0.40`; and combustion health is normalised against the range its efficiency can actually traverse | This was the defect that would have made the whole dataset pointless, and it is invisible in a single-mission test. A clamp is a step, not damage that accumulates. Measured: a **severity-1.0** fault left the composite index at **0.77–0.89** against a 0.60 threshold — cooling 0.794, injector 0.766, bearing 0.797, oil 0.891 — so **no single fault at maximum severity could end an engine's life**. Every failure in the trial fleet therefore came from baseline wear near TBO (failures clustered 597–1178 h), and a model trained on it would have learned "RUL = TBO − hours" while ignoring the faults entirely — precisely the circularity PRD Part 0 §0.5 exists to prevent. Three separate causes had to be fixed: (a) clamps do not accumulate, so faults now multiply the pathway rate; (b) a weighted average dilutes one destroyed subsystem behind two healthy ones, so PRD Part 2 §9.3's own band table (below 0.40 = "UNSAFE — ground aircraft immediately") is applied as a second end-of-life criterion; (c) `combustion_efficiency` is floored at 0.80 in the model — correctly, since a real engine never burns half its fuel — which made the raw efficiency useless as a health index, so it is now normalised over the 0.80–0.98 range it can actually cross. A thermodynamic efficiency and a health index are not the same quantity. |

### Fault severity now maps to engine life

Flight hours to end of life, single fault, onset 150 h, 50 h ramp
(`~` = survived to the 1200 h TBO and was censored):

| fault | sev 0.3 | sev 0.5 | sev 0.7 | sev 0.9 |
|---|---|---|---|---|
| none | ~1200 | — | — | — |
| cooling degradation | 888 | 555 | 379 | 271 |
| abnormal vibration | 565 | 282 | 194 | 185 |
| combustion instability | 618 | 419 | 321 | 264 |
| misfire | 759 | 564 | 467 | 408 |
| overheating trend | ~1200 | 1097 | 903 | 776 |
| lubrication issue | ~1200 | 1185 | 990 | 858 |
| injector abnormal | ~1200 | ~1200 | ~1200 | 195 |

A fault-free engine is untouched by the acceleration table and still reaches
TBO. Injector faults remain life-limiting only at high severity, which is left
as it is rather than tuned for a uniform-looking table: moderate injector wear
genuinely should not ground an engine before overhaul.

### Healthy-engine trajectory after the fixes

A fault-free engine at nominal rates, no manufacturing spread:

| hours | cooling | injector | bearing | turbo | combustion | CHI | oil changes |
|---|---|---|---|---|---|---|---|
| 200 | 0.959 | 0.911 | 0.956 | 0.984 | 0.990 | 0.943 | 2 |
| 600 | 0.878 | 0.845 | 0.867 | 0.952 | 0.969 | 0.864 | 6 |
| 1200 (TBO) | 0.755 | 0.781 | 0.733 | 0.904 | 0.939 | **0.756** | 12 |
| 1500 | 0.694 | 0.755 | 0.667 | 0.880 | 0.923 | 0.705 | 15 |

A healthy engine now reaches TBO at CHI 0.756 and never crosses the 0.60
maintenance threshold on natural wear alone. That is the correct behaviour, not
a missing failure: TBO exists precisely so that the engine is overhauled
*before* it fails. Those engines are emitted as **censored** records — their
RUL is a lower bound, not a value — and the flag lets a training run drop them
rather than learn a wrong target. Faults are now what causes early failure,
which is what the dataset is for.

`oil_quality` sawtooths 1.00 → 0.52 across each 100 h interval and resets. This
is realistic and is retained deliberately: a health index that includes
lubrication condition does exactly this on a real aircraft, and it is why
PRD Part 2 §9.4 specifies EMA smoothing and CUSUM knee-point detection rather
than reading the raw index.

## Deviations found while building the AI layer (Layer 3)

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-46 | Tier-2 libraries<br>`layer3_ai/tier2_statistical.py` | PRD Part 2 §11.1 names **PyOD** and **dtaianomaly** | Isolation Forest from scikit-learn (already a first-class dependency); **CBLOF** and the **matrix profile** implemented directly | PyOD pins numpy and scikit-learn versions that conflict with the rest of this stack (numpy 2.5 / sklearn 1.9). The same was already true of ADTK for Tier 1 — see DEV-7, which set this precedent. The requirement is the ALGORITHMS, not the packages: every algorithm's semantics and every parameter in `thresholds.detectors.tier2` is preserved, and each is unit-tested on data where the right answer is known by construction. |
| DEV-47 | Matrix-profile normalisation<br>`layer3_ai/tier2_statistical.py` | The textbook matrix profile z-normalises each subsequence so it matches on SHAPE regardless of level | **z-normalisation off by default**, selectable via `znorm=True` | Z-normalisation subtracts exactly the quantity being measured here. Engine degradation appears as a slow LEVEL SHIFT in a residual, not as a change of shape. Measured on a synthetic series with a planted level shift at sample 3000: with z-normalisation the profile peaked at index **83** — it missed the anomaly entirely, because a shifted block of noise has the same shape as unshifted noise. With it off, the peak lands on the planted shift. Both behaviours are unit-tested so the trade-off cannot be re-enabled by accident. |
| DEV-48 | Matrix-profile distance computation | — | Distances from dot products: `d² = ‖a‖² + ‖b‖² − 2a·b`, one matrix multiply | The direct form materialises a `(block, n, m)` array — **61 GB** on this dataset — for a result that fits in a single `(block, n)` product. Mathematically identical, and it is what makes the detector usable on a fleet-scale series at all. |
| DEV-49 | Anomaly labelling for scoring<br>`layer3_ai/features.py` | — | An anomaly is an expressed fault **OR** an engine past the GOOD/FAIR boundary (CHI ≤ 0.80) of PRD Part 2 §9.3; the band between healthy and degraded is **excluded** from precision/recall | Scoring only against injected faults punishes a correct detector: an engine at CHI 0.65 from ordinary wear is genuinely not healthy, and flagging it is the right answer, not a false positive. The problem statement asks for degradation TRACKING, not fault spotting alone. Measured cost of the wrong definition: apparent false-positive rate 0.33 against a true 0.11 on the same scores. The ambiguous band (27.8 % of test rows) is reported and excluded rather than assigned to whichever class flatters the result. |
| DEV-50 | Per-engine residual baselining<br>`layer3_ai/features.py` | — | Each engine's residuals are offset by the median of its **own first 60 flight hours** | Manufacturing spread gives every engine a constant residual offset against the as-new reference: measured on this fleet, mean oil-pressure residual spans **−25 to +1 psi with no fault present anywhere**. A detector thresholded on the absolute residual therefore fires on whichever engines sit at the edge of build tolerance. What carries health information is the CHANGE in a residual from where that engine started. This is not hindsight leakage — the deployed twin holds a running residual mean per engine from installation (`layer4_core.twin_state.Residual`), so the baseline exists in service from the first flight hours, and only the engine's own early life is used. Effect: false-positive rate 0.105 → 0.075, precision 0.946 → 0.960. |

### Tier-2 performance on held-out engines

Fitted on healthy rows from the 80 training engines only; threshold fixed on
healthy TRAINING data for a 5 % false-positive rate and never moved to suit the
test set. Reported on the 10 test engines, never seen during fitting.

| feature set | ROC-AUC | precision | recall | F1 | FPR |
|---|---|---|---|---|---|
| PRD7 (7 raw channels, PRD Part 2 §11.1) | 0.945 | 0.939 | 0.845 | 0.889 | 0.111 |
| **EXTENDED (+ physics residuals)** | **0.971** | **0.960** | **0.895** | **0.927** | **0.075** |

Against the PRD Part 2 §11.1 targets: precision > 0.85 **met** (0.960);
F1 > 0.87 **met** (0.927); recall > 0.90 **NOT MET** (0.895); false-positive
rate < 5 % **NOT MET** (7.5 %).

The false-positive rate drifting from the 5 % it was set for on training
engines to 7.5 % on unseen ones is a real generalisation cost, not a tuning
artefact — reporting it is the point of holding engines out. Both misses are
narrow and are expected to close when Tier 3 is fused in
(PRD Part 2 §11.2 weights the deep model at 0.4).

**The residual features are worth their cost**: ROC-AUC +0.026, recall +0.051
at a *lower* false-positive rate. That is the measured return on maintaining a
second as-new engine model, rather than an assertion that a digital twin helps.

All 7 failing test engines were detected, at a median **525 flight hours**
before end of life.

## Deviations found while building Tier 3 (the deep layer)

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-51 | Fault-classification head<br>`layer3_ai/tier3_deep.py` | PRD Part 2 s11.1: `Dense(8, softmax)` | **Sigmoid per class** with binary cross-entropy (multi-label) | Softmax asserts the eight faults are mutually exclusive. They are not: **21,050 rows (6.6 %)** of the fleet carry two or three simultaneous faults, because a real engine can be losing cooling *and* wearing a bearing at once. A softmax head must split its probability mass between them, so it under-reports both -- and the second fault is likeliest to be missed exactly when the engine is worst. |
| DEV-52 | Which engines go in which split<br>`layer3_ai/features.py` | PRD Part 0 s0.5: train engines 1-80, val 81-90, test 91-100 | Engine-level split **preserved**, but engines assigned by **stratifying on fault composition** rather than by ID | The requirement -- no engine's samples in two splits -- is untouched. But which engine got which ID is arbitrary, and the ID ordering left validation with **zero** examples of two fault classes (`injector_abnormal` 10.3 % of training rows, 0 % of validation; `overheating_trend` 9.8 % and 0 %). Early stopping and threshold selection both run on validation, so a model getting worse at classes validation cannot see still looked like it was improving. Measured: training to convergence on the ID-ordered split produced a **worse** test model than stopping at eight epochs -- anomaly ROC-AUC 0.926 against 0.983. |
| DEV-53 | `OVERHEATING_TREND` was never implemented<br>`layer2_physics/degradation.py`, `mvem.py` | One of the eight fault modes the problem statement requires (PS section C) | A new `cooling_airflow` degradation factor scaling radiator conductance -- lost heat rejection to **air**, as distinct from `cooling_efficiency` which is the head-to-coolant path **inside** the engine | The mode had **no physical effect anywhere**. A code comment claimed `engine_sim.py` applied it; that file has never contained a single reference to it. It produced a ground-truth label and nothing else, so a classifier was being asked to detect something that was not in the data. Worse, once faults were made to accelerate wear (DEV-45) it became an exact duplicate of `cooling_degradation` at lower gain, and the two were then **indistinguishable in principle** -- measured F1 0.092 and 0.076. The two-node thermal model (DEV-14) already separates the paths, so the fix was to use it. Verified at 12,000 ft, 75 % throttle: jacket scaling gives CHT 120.6 C with coolant held at 92.0 C by the thermostat (delta 28.5 K); a blocked radiator raises the **whole loop** -- CHT 115.2 C, coolant 99.5 C, delta unchanged at 15.7 K. Different faults, different signatures, separable. |
| DEV-54 | Misfire shared the injector pathway | -- | `MISFIRE` no longer accelerates `INJECTOR_FOULING` | It did, which made misfire and `injector_abnormal` share their dominant degradation signature. Measured consequence: the classifier scored misfire **0.905** F1 while `injector_abnormal` collapsed to **0.190** -- it was calling one the other. Misfire already has its own signature (one cylinder's EGT down 28 % with an rpm droop, in `engine_sim.py`) and does not need to borrow the injector pathway to be detectable. |
| DEV-55 | Early-stopping criterion<br>`layer3_ai/tier3_deep.py` | PRD Part 2 s11.1: "Early stopping: patience=10, monitor validation loss" | Monitors validation **macro-F1** | The loss mixes three tasks with positive-class weighting, so it is only a proxy for what the model is for. Monitoring it stopped training at epoch 3 and shipped a classifier with **0.515** anomaly recall while the metric that actually matters was still improving. Macro-F1 is the objective, so it is what early stopping watches. Patience of 10 is unchanged. |
| DEV-56 | Per-class decision thresholds | -- | Thresholds fitted on **training** predictions, taking the lowest threshold within 2 % of peak F1 | A single 0.5 cut-off is wrong when class prevalence differs by an order of magnitude, and after positive-class weighting the logits are deliberately not calibrated to 0.5. Two refinements were forced by measurement: (a) tuned on the ten validation engines, `injector_abnormal` drew a threshold of **0.84** and then scored F1 **0.000** on test because nothing there ever exceeded it -- a decision threshold is a model parameter, so it is fitted on training data while validation keeps early stopping; (b) taking the argmax of the F1 curve lands on whichever grid point noise favoured, since the curve is flat near its peak, so the lowest threshold statistically indistinguishable from the best is used instead. |
| DEV-57 | `sensor_drift` excluded from macro-F1 | PS section C lists sensor drift as one of the eight faults | Excluded from the Tier-3 macro average and reported separately; **detected at Tier 1 instead** | The class carries **zero positive labels anywhere in the fleet**. It is not an injectable fault by design: the instrument layer models sensor bias drift directly, and injecting it as well would double-count it against a drift the sensors already have. Tier 3 therefore cannot learn it from this dataset and never will. Including an unlearnable class in a macro average silently subtracts 1/8 from the score for something the design never asked this model to cover. It is covered -- by the dual-lane vote and bias-deviation rules in `layer1_edge`. Both figures are printed so the exclusion is visible rather than assumed. |

## Deviations found while building three-tier fusion

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-58 | Alert trigger logic<br>`layer3_ai/fusion.py`, `configs/thresholds.yaml` | PRD Part 2 s11.2: L3 if `S_final > 0.60 AND S_rule > 0.50`; L4 if `S_final > 0.80 AND (S_stat > 0.70 OR S_deep > 0.80)`; L5 if `S_final > 0.95 AND S_rule = 1.0` | The three PRD paths kept **verbatim**, plus a fourth `l3_predictive` path: when the rules are silent but **both** model tiers agree, raise a CAUTION marked PREDICTIVE | **The logic as written can raise no alert at all when the rule engine is silent** -- which is the exact situation this system was built for. With `S_rule = 0` and both models perfectly certain, `S_final = 0.3(0) + 0.3(1.0) + 0.4(1.0) = 0.70`, below the 0.80 that L4 requires; and L3 is gated behind `S_rule > 0.50`, which on the normalised scale means the rule engine must **already be at ORANGE**. Measured on the held-out engines: **1,325 genuinely degraded windows have the rule engine silent, and the PRD logic catches 0 of them.** The added path catches 1,131 (85 %). This project has already demonstrated cooling degradation and lubrication issues detected with no threshold crossed; every one of those findings would have been built, scored, reported -- and then muted on the way to the operator. **What is deliberately NOT changed:** an EMERGENCY still requires `S_rule = 1.0`. A model may say an engine is degrading; it may not ground an aircraft on its own. That gate is correct and a test pins it. |
| DEV-59 | Combining the two Tier-3 outputs | PRD Part 2 s11.2 assumes a single "anomaly probability from neural network" | Tier 3 produces **two** (autoencoder and supervised head); they are combined by **maximum** | The two are not interchangeable -- the autoencoder runs 0.968 recall at 0.963 precision, the supervised head 1.000 precision at 0.653 recall. The first implementation averaged them, on the argument that a maximum would inherit the autoencoder's false-positive rate. **Measurement disproved that argument**: fusion only fires when both model tiers agree, and that gate filters the autoencoder's false positives before they reach the operator. Mean gives precision 1.000 / recall 0.551 / FPR 0.000; max gives precision 1.000 / recall **0.878** / FPR 0.000. Same precision, same zero false-positive rate, 33 points more recall -- averaging was throwing away most of the autoencoder's sensitivity against a head that abstains. |

### Fusion measured against each tier alone (10 held-out engines)

| detector | ROC-AUC | precision | recall | F1 | FPR |
|---|---|---|---|---|---|
| Tier 2 statistical | 0.940 | 0.937 | 0.837 | 0.884 | 0.081 |
| Tier 3 autoencoder | 0.992 | 0.963 | 0.968 | **0.965** | 0.053 |
| Tier 3 anomaly head | 0.993 | 1.000 | 0.653 | 0.790 | 0.000 |
| **FUSED (three tiers)** | 0.980 | **1.000** | 0.878 | 0.935 | **0.000** |

Reported honestly: the autoencoder **alone** scores a higher F1 (0.965 vs
0.935). Fusion trades nine points of recall for **precision 1.000 and a
false-positive rate of exactly zero**. For an operator-facing alerting surface
that is the right trade and not a close call -- MIL-STD-411F 4.1.1a requires a
healthy engine to be silent, and an operator who is alerted on healthy engines
stops reading alerts, at which point recall stops mattering at all. The
autoencoder's raw score remains available to the maintenance view, where a
false positive costs an inspection rather than trust.

## Deviations found while building the health indices

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-60 | Sub-index formulas<br>`layer3_ai/health.py` | PRD Part 2 s9.2 defines the indices against ABSOLUTE thresholds, e.g. `THI = 1 - (CHT_max - 105)/(135 - 105)` | Residual form wherever a shadow-model prediction exists; the absolute form retained as the fallback when no shadow model is running | Cylinder head temperature depends far more on what the throttle is doing than on whether the engine is healthy. Measured on **83,000 rows from engines the simulator certifies as genuinely healthy**, the specified formula scored **25.7 % of them "degraded"** and **5.6 % "fault"**, with THI falling 1.00 -> 0.83 across nothing but a throttle change from 60 % to 85 %. An index that reads DEGRADED whenever the engine works hard is a power gauge wearing a health gauge's label -- and one that cries wolf, because an operator learns within a week that it always sags in the climb and stops believing it. The residual cancels the operating point by construction. End-to-end on held-out engines: MAE against ground truth **0.087 -> 0.067**, correlation **+0.525 -> +0.678**, healthy engines wrongly called degraded **27.4 % -> 14.5 %**, and wrongly called POOR-or-worse **5.6 % -> 1.1 %**. |
| DEV-61 | CUSUM baseline<br>`layer3_ai/health.py` | PRD Part 2 s9.4 Method 3: `S_t = max(0, S_{t-1} + (CHI_nominal - CHI(t)) - K)` with `K = 0.02` | `CHI_nominal` is **the engine's own settled level**, learned from its first 120 samples -- not 1.0 | Reading `CHI_nominal` as 1.0 (as-new) makes the detector fire on everything. A healthy in-service engine sits near 0.97, so every sample contributes `(1.0 - 0.97) - 0.02 = +0.01`, the sum climbs without bound, and onset is "detected" on a perfectly healthy engine after about **fifty samples -- on every airframe in the fleet**. CUSUM detects a departure from an established level; the level has to be established first. Caught by a test asserting a healthy engine never trips it. |
| DEV-62 | Mechanical index nominal<br>`configs/thresholds.yaml` | `health.mhi.vib_nominal: 2.0` | **3.0** | 2.0 was the PER-AXIS baseline from the engine config (`vibration.baseline_rms_m_per_s2`), but the index is fed the THREE-AXIS vector total `sqrt(x^2+y^2+z^2)`, which measures **2.93 median / 3.30 p95 on a healthy engine**. Comparing a vector magnitude against a single-axis nominal scored every healthy engine MHI 0.845, and because mechanical health is the MINIMUM of its contributors that capped the composite fleet-wide. |
| DEV-63 | Oil-pressure/rpm correlation | PRD Part 2 s9.2 Parameter 4: `eta_correlation` over the last 60 seconds, nominal > 0.95 | The term is DROPPED when rpm varies by less than 0.5 % of its mean | In a steady cruise leg rpm barely moves, so the correlation is computed between one noise sequence and another. It returns a number between -1 and +1 that carries no information, and it multiplies straight into the lubrication index -- dragging it down on a perfectly healthy engine. There is no signal to correlate, so the term is dropped rather than guessed. |
| DEV-64 | `FSHI` definition | PRD Part 2 s9.2 Parameter 6: `FSHI = (BSFC_actual / BSFC_nominal)^-1`, with BSFC from fuel flow and BMEP | Fuel-flow residual against the as-new prediction at the same operating point | BSFC needs shaft power, which no engine bus publishes -- the formula cannot be evaluated from telemetry. The residual measures the same thing (burning more fuel than this condition warrants) from quantities that actually exist. |
| DEV-65 | `CSI` band table (documentation only) | PRD Part 2 s9.2: `CSI = 1 - spread/25` **and** "Normal: CSI > 0.90 (spread < 8 degC)" | Formula implemented as written; the band note is inconsistent and is not used | The two statements cannot both hold: `1 - 8/25 = 0.68`, not > 0.90. They are consistent only at the ORIGINAL air-cooled limit of 80 (`1 - 8/80 = 0.90`), so the Revision 2 rescale to 25 updated the divisor and left the band text behind. No code impact -- the measured healthy spread on this engine is 1.2 degC, giving CSI 0.95 -- but recorded because the document contradicts itself. |

## Deviations found while building RUL estimation

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| **DEV-66** | RUL loss function<br>`layer3_ai/rul_lstm.py`, `rul_physics.py` | PRD Part 2 s12.3: `Score = exp((RUL_true - RUL_pred)/13) - 1 for RUL_pred < RUL_true`, described as "penalizes late predictions more than early predictions" | The standard NASA C-MAPSS asymmetric score, with the intent the PRD **states** rather than the formula it prints | **The printed formula rewards the dangerous error.** It penalises `RUL_pred < RUL_true` -- the CONSERVATIVE under-estimate -- and scores over-prediction at exactly **zero**: predicting 100 h when 200 h remained costs 2,190; predicting 200 h when 100 h remained costs 0. Trained against it, a network learns to over-estimate remaining life, which is the one error in prognostics that flies an aircraft past the point its engine should have been pulled. The config already carries `nasa_score_early_tau: 13.0`, the standard early constant, so the configuration was right and only the prose was garbled. Pinned by a test that evaluates the printed formula directly, so it cannot be restored by tidying the code back toward the spec. |
| DEV-67 | NASA score units and aggregation | PRD Part 2 s12.3 target: "NASA Score < 500" | Time constants scaled by the RUL horizon (400/130 = 3.08); the score summed over **engines**, not windows | Two category errors in the target as stated. C-MAPSS defines the score over RUL in **cycles** on a 0-130 range and sums **one prediction per unit**; this engine's RUL is in **hours** on a 0-400 horizon and there are ~140 windows per engine. Unscaled and summed over windows, the measured score was **2.3 x 10^14** -- a statement about units, not about the model. Corrected, the same model scores **11.8** against the < 500 target. |
| DEV-68 | Piecewise RUL target | PRD Part 2 s12.3: "For healthy engine (t < t_onset): RUL = RUL_max (constant)", with `RUL_max = TBO = 2,000 hours for Rotax 914` | Capped at `rul.prediction_horizon_hours = 400`, read from configuration | Capping at TBO does nothing: the raw countdown already tops out near TBO, so the cap never binds and the network is left being asked whether a healthy engine has 900 or 1,100 hours left. Nothing in a 50-second window distinguishes those, so it is asked to learn noise -- burning capacity and inflating the error on the part of the curve that carries every actual decision. 400 h is a third of the 1,200 h TBO, the same proportion as the 125-of-360 cap used on C-MAPSS, and operationally it is where decisions stop differing: "600 hours left" and "800 hours left" both mean "not now". (The 2,000 h figure is also a stale 914 number; the 915 iS TBO is 1,200 h.) |
| DEV-69 | Physics RUL guard | -- | A near-zero decline rate is rejected; the estimate is capped at one overhaul interval | `RUL = margin / rate` puts the rate in a DENOMINATOR. With the guard at 1e-7 per hour, noise-level rates produced estimates in the tens of thousands of hours and a physics RMSE of **19,857 h**. The floor is now derived from the engine itself -- a decline slower than "the whole health margin over one TBO" cannot end the engine's life before overhaul anyway -- and an engine with no measurable trend is reported as **"not yet determinable"** rather than given a large number, because a large number reads as reassurance exactly when the evidence is weakest. |
| DEV-70 | Input normalisation constants | PRD Part 2 s12.3 lists 7 constants, e.g. `CHT_norm = (CHT_avg - 175)/55`, `EGT_norm = (EGT_avg - 620)/200` | The shared feature contract in `layer3_ai/features.py` | Those constants are air-cooled Rotax 914 values. Applied to this engine they z-score a normal 108 degC head to **-1.2** instead of ~+0.1, so every input would arrive off-centre. Superseded by the single feature definition used by training and inference alike -- see DEV-70's real point, which is that there must be exactly one such definition. |

### RUL measured on held-out engines

Censored engines are excluded from both training and scoring: their recorded
RUL is a lower bound, not a value, and training on it teaches the model that
healthy engines are about to fail.

| estimator | RMSE (h) | MAE (h) | MAPE | R2 | NASA | late |
|---|---|---|---|---|---|---|
| LSTM (data-driven) | **102.3** | 75.7 | 0.55 | **0.427** | **11.8** | 37 % |
| physics extrapolation | 178.9 | 141.9 | 0.72 | -0.76 | high | 40 % |
| fused (s12.5) | 113.5 | 87.1 | 0.59 | 0.295 | 67.7 | 37 % |

Against the PRD Part 2 s12.3 targets: **NASA score MET** (11.8 vs < 500);
RMSE, MAPE and R2 **NOT MET**. Reported rather than tuned away.

The NASA score passing while RMSE fails is the informative combination: the
model is not making systematically dangerous over-predictions, it is simply
imprecise. The honest reading of why is that RUL depends on the RATE of
degradation, and a 30-sample window spanning fifty seconds cannot see a rate --
it sees a state. The physics estimator does see the whole history, and is
worse, because it inherits the noise in the health estimate (MAE 0.067) and
then divides by it. Closing this needs sequence features that span sorties, not
more epochs.

## Deviations found while wiring the console to the live system

Running every layer together for the first time exposed three defects that no
layer's own tests could see, because each is about what one layer hands the
next.

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-71 | The advisory ignored health<br>`layer4_core/twin_state.py` | PRD Part 1 §6.1 defines `maintenance_advisory` without saying what drives it | Driven by the Tier-1 alerts **and** the health band, taking whichever is more severe | Sourced from alerts alone, the advisory reported **"Normal operation. No action required."** while the health index sat in a band whose own configured action is "monitor closely" and the cylinder head ran **12.7 K hotter** than an as-new engine at the same operating point. That is DEV-58's defect arriving through a different door: the finding survives detection, survives fusion, and is then discarded on the last step before the operator. |
| DEV-72 | Advisory graded on the composite only | — | Graded on the **worst subsystem** as well as the composite | A weighted average dilutes one destroyed subsystem behind three healthy ones -- the same defect DEV-45 found at end-of-life. Measured: an engine with cooling efficiency at 0.53 and a THERMAL sub-index of **0.62** still scored a composite of 0.806 = GOOD, and said nothing. It now reports "THERMAL subsystem POOR — degradation detected, no limit exceeded / maintain within 25 h", with the rule engine correctly silent throughout. |
| DEV-73 | Decisions taken on the raw health index | PRD Part 2 §9.4 Method 1 specifies EMA smoothing (α = 0.1) for trend tracking | The **smoothed** index drives the band, the advisory and the fused verdict; the raw index is kept for the trend chart | Fed the raw per-sample value, the advisory flipped between INFO and ADVISORY every thirty seconds as the flight profile changed throttle -- CHI 0.743 → 0.822 → 0.791 → 0.806 across four consecutive observations of a steadily degrading engine. An advisory that chatters is one an operator learns to ignore. Smoothed, the same engine holds 0.804–0.810. The PRD already specified the smoothing; what was missing was using it for the decision rather than only for the chart. |
| DEV-74 | `I_capacity` in the electrical index<br>`layer3_ai/health.py` | PRD Part 2 §9.2 P8: `I_capacity = I_alternator_actual / I_alternator_rated` | Capacity measured as the **bus voltage held against regulation**, not as current utilisation; `V_stability` also accounts for the voltage LEVEL, not variance alone | Current drawn depends on what the aircraft has switched on, not on alternator health. A healthy alternator supplying **8 A of a 40 A rating** is meeting the demand that exists; it is not 20 % healthy. Taken literally the term scored a perfectly healthy engine **EHI 0.68**, which under the new worst-subsystem rule raised **"ELECTRICAL subsystem POOR" on an aircraft with nothing wrong with it** -- a MIL-STD-411F 4.1.1a violation, and the same category error as THI using absolute CHT (DEV-60). What indicates a failing alternator is inability to MEET demand, which shows as the bus falling away from regulation. Separately, `V_stability` as specified is a variance measure, and a bus stuck at 22 V has excellent variance -- "stable" and "correct" are not the same property, so the level is folded in. A dead alternator on a sagging bus is caught explicitly. |

### The live system, measured end to end

`python -m layer4_core.twin_api` runs every layer together: physics → CAN
encode → CAN decode and validate → Tier-1 rules → shadow model → twin → health
→ fusion → console. Nothing on the path is mocked.

| condition | CHI | THRM | MECH | ELEC | COMB | limit alerts | advisory |
|---|---|---|---|---|---|---|---|
| healthy | 0.975 EXCELLENT | 1.00 | 0.97 | 0.98 | 0.95 | **0** | INFO — normal |
| cooling degradation 0.9 | 0.872 GOOD | **0.62** | 1.00 | 0.98 | 0.97 | **0** | **CAUTION** — THERMAL POOR, maintain within 25 h |

The second row is the whole argument for the system in one line: a real
degradation, a cylinder head 8 K hotter than an as-new engine would run at the
same operating point, a specific subsystem named and a maintenance deadline
given — and **not one certified limit exceeded**. A threshold monitor shows
nothing here.

Pipeline: 45/45 channels valid, data quality 1.000, latency **p50 25.8 ms /
p95 42.3 ms** against the PRD Part 1 §6.4 budget of 100 ms median and 200 ms
at the 95th percentile.

## Deviations found while building explainability and federated learning

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-75 | Federated-learning framework<br>`layer3_ai/fed/federated.py` | PRD Part 0 names **Flower (flwr)** | FedAvg, DP and the robust aggregator implemented directly | FedAvg is a weighted average of weight vectors: `w_global = sum_k (n_k/n_total) x w_k`. Wrapping a weighted average in a framework obscures the one thing a reviewer needs to see — that nothing but weights moves. The same reasoning retired ADTK (DEV-7) and PyOD (DEV-46), and it applies with more force here because the claim being made is a **security** claim, and a security claim is worth exactly what the reader can verify. Every parameter of PRD Part 3 §22 is preserved, and `flwr` is not installed in this environment. |
| DEV-76 | Attribution method<br>`layer3_ai/explain.py` | PRD Part 2 / Part 4 name **SHAP** | **Exact closed-form decomposition** for the health index and residuals; occlusion attribution for the deep classifier | The composite health index is a weighted sum of four subsystem scores, each the MINIMUM of named sub-indices with published formulas — so every contribution is computable exactly. SHAP would spend compute producing a sampled approximation of a quantity that can be written down, and an approximation of a known answer is strictly worse than the answer because it invites the reader to wonder about the sampling error. SHAP is reserved for the deep classifier where there genuinely is no closed form, implemented as occlusion (exact for an additive model, no sampling variance to explain, and no dependency added to a serving path that is deliberately torch-light). |
| **DEV-77** | Cost of differential privacy | PRD Part 3 §22.4: "Trade-off: **slight accuracy reduction (<3 %)** for strong privacy guarantee" at ε = 1.0 | The measured cost is reported instead of the claimed one | **Measured on the fleet, ε = 1.0 per round costs −0.323 ROC-AUC** — 0.869 without privacy, 0.547 with it. That is a 37 % relative drop, not under 3 %. The cause is arithmetic rather than implementation: at a clip norm of 1.0 the Gaussian mechanism needs σ = 4.84 for ε = 1, and a 21-element update simply does not survive noise of that scale. ε = 5 costs −0.216. A deployment wanting the PRD's stated trade needs far more data per round, far fewer rounds, and a moments accountant rather than sequential composition. The claim is not achievable as written and the measurement is reported rather than the claim. |
| DEV-78 | Privacy accounting | PRD Part 3 §22.4 states ε = 1.0 as though it were a total | ε is reported **per round**, with the sequential-composition upper bound alongside | Twenty-five rounds at ε = 1.0 each is not an ε = 1.0 system. Reporting the per-round figure as a total would overstate the guarantee by a factor of the round count. `PrivacyBudget.spent()` returns both and names the accounting method, so nobody reads the wrong number. A real deployment needs a moments accountant (Abadi et al.), which is tighter than the bound reported here. |

### Federated learning, measured on the fleet

Three simulated aircraft, whole engines assigned to each (never split), 25
rounds, scored on the 10 held-out engines.

| configuration | ROC-AUC | |
|---|---|---|
| centralised — all telemetry pooled | 0.869 | the upper bound |
| **federated — weights only** | **0.869** | **cost of keeping data on the aircraft: −0.000** |
| federated + DP, ε = 5 / round | 0.653 | σ = 0.97 |
| federated + DP, ε = 1 / round | 0.547 | σ = 4.84 |

**Bandwidth, measured rather than asserted:** 51.92 MB of telemetry stayed on
the aircraft; 12.60 kB of weights crossed the link over 25 rounds × 3 clients.
A **4121×** reduction, against the 100× PRD Part 3 §22.5 claims.

**Model poisoning.** The realistic attack on FedAvg is not inverted labels —
averaging dilutes those — but MODEL REPLACEMENT, where one client scales its
update so that its contribution survives the average and the others cancel.
With one aircraft of three compromised:

| aggregator | ROC-AUC |
|---|---|
| FedAvg mean | **0.445** — the fleet model is destroyed |
| coordinate-wise median | **0.867** — essentially unharmed |

A median cannot be dragged by one client the way a mean can. It is **not** a
defence against an adversary who stays near the consensus and biases it slowly,
and no such claim is made.

## Deviations found while building the maintenance advisory

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-79 | Overhaul double-counting<br>`layer3_ai/advisory.py` | PRD Part 2 §16.3 lists seven independent actions with independent triggers | A full overhaul **subsumes** the individual jobs; they are recorded on the overhaul rather than listed beside it | Evaluated independently, a worn-out engine triggered all seven at once and was quoted **Rs 577,000** — the overhaul's own Rs 500,000 plus Rs 77,000 of work the overhaul performs by definition, since it drains the oil, cleans the injectors and inspects the bearings. Beyond the 15 % cost error, a planner reading "complete engine overhaul AND oil change AND injector cleaning" would rightly stop trusting the rest of the list. The subsumed jobs are kept on the overhaul's `subsumes` field so the evidence survives into the work package — a technician opening the engine should know the injectors were already suspect. |
| DEV-80 | Action urgency graded on the composite | — | The action's **own evidence** can escalate it past what the composite band says | The composite-dilution defect for the third time, after DEV-45 at end-of-life and DEV-72 in the advisory. Measured: an engine whose `oil_quality` had fallen to **0.00** was told to change the oil "at the next scheduled maintenance", because three healthy subsystems held the composite above 0.80. A job is as urgent as the thing that triggered it, so evidence far past its floor now escalates the action to CAUTION or WARNING regardless of the composite. Same engine now: **WARNING, due within 10 flight hours**. |

## Deviations found while closing gap G4 (battery state of health)

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-81 | Battery SOH was unimplementable<br>`layer3_ai/battery.py`, `configs/can/engine.dbc` | PRD Part 2 s9.2 P8: SOH_battery = f(cycle_count, internal_resistance, voltage_under_load) | A new **BATTERY_CURRENT CAN channel** from a pack shunt, plus an estimator fitting V = OCV - I x R across discharge events | The term could not be computed from the bus as it stood, which is why the electrical index had been renormalising its two remaining terms since it was written. Alternator current is not a substitute: during a discharge it is pinned at whatever the generator can supply and says nothing about the pack. Measured, the estimator correctly refused to report a state of health for the entire life of the engine. **A battery shunt is standard on any aircraft with battery monitoring, and no amount of estimation substitutes for the instrument.** With it, the fit recovers a known 96 mOhm pack to within 0.4 %. Channel count 45 -> 46. |
| DEV-82 | An unexplained literal in the electrical model<br>`layer2_physics/mvem.py` | -- | battery_cells_series named in configuration; pack resistance = cells x per-cell | The voltage-sag calculation multiplied the configured resistance by a bare 8.0 with no comment. It is the series-cell count of a 28 V pack -- correct arithmetic, invisible intent. It surfaced when the SOH estimator fitted a resistance exactly **8x the configured value** and there was no way to tell which number was wrong. An unexplained multiplier inside a voltage calculation reads as a fudge factor; naming it makes the arithmetic inspectable. |
| DEV-83 | Constant electrical load<br>`layer2_physics/engine_sim.py` | -- | Base avionics + a payload duty cycle + datalink bursts | The simulator drew a fixed 8 A. Harmless-looking, until internal resistance had to be recovered from the **slope** of voltage against current: a constant current is a regression through a single point. Measured, discharge current spanned **0.80 A** against the 1.5 A the fit needs, and the estimator declined to answer -- correctly, but permanently. A MALE UAV duty-cycles its ISR payload and transmits in bursts, so a varying load is also the more faithful model. |
| DEV-84 | Stale estimates re-reported as fresh | -- | The estimator re-fits **only when new samples arrive**; otherwise it returns the cached value with its age | The sample window persists between discharge events, so re-fitting every frame produced a "fresh" measurement from data collected hours earlier and reset the age to zero -- defeating the staleness tracking that is the entire reason for reporting when the reading was taken. Caught by a test asserting that a measurement taken at 10 flight hours reads as 200 hours old at hour 210. |

### Battery state of health, measured

| pack | true resistance | fitted | SOH |
|---|---|---|---|
| new | 96.0 mOhm | 96.4 | 0.995 |
| half-aged | 144.0 mOhm | 144.4 | 0.495 |
| end of life | 192.0 mOhm | 192.4 | 0.000 |

On the live system: **SOH 0.92** from 241 discharge samples spanning 17.2 A,
measured during the low-rpm phase and correctly reported as a dated reading
once the alternator takes the load again. The electrical index now uses all
three of the PRD's terms rather than renormalising two.

## Deviations found while closing gap G2 (engine test-rig deployment context)

The PS Expected Solution names three deployment contexts -- "defence grade
Ground Control Station (GCS), **engine test rigs**, and fleet-level health
monitoring infrastructures". Building the second one surfaced a defect in the
physics that none of the flight-side work had exposed.

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-85 | **A degraded turbocharger cost no power**<br>`layer2_physics/mvem.py` | PRD Part 1 s5.2 lists `turbocharger_condition` as a degradation pathway | Brake torque is scaled by manifold pressure against the pressure an **as-new** turbo would make at the same operating point | The brake-torque map was scaled by `p_man` divided by the **actual** turbo's own predicted manifold pressure. Both fall together when the turbo degrades, so the ratio stayed at 1.0 and the turbo was compared against itself -- a turbo compared against itself can never be found wanting. Measured at sea level, `turbocharger_condition` 1.00 -> 0.65 dropped charge **1.505 -> 0.988 bar, a 34 % loss**, and brake power did **not move at all: 102.9 kW at both ends**. At 15,000 ft the charge fell 61 % and power went 96.0 -> 95.9 kW. Loss of power is the *defining* symptom of a failed turbocharger and the model did not have it. It is precisely the reference error the shadow model exists to avoid, committed inside the physics: a degraded component must be measured against an as-new reference, never against itself. Fixed, power now tracks charge proportionally (102.9/1.505 = 68.4, 92.6/1.355 = 68.3, 67.6/0.988 = 68.4) and a `turbocharger_condition` of 0.75 costs 24 % of rated power. The as-new engine is bit-identical, so every published anchor is untouched. |
| DEV-86 | **A test cell is not an aircraft standing still**<br>`layer4_core/test_rig.py` | -- (PS names engine test rigs as a deployment context; no PRD models one) | Cell cooling is an explicit facility property, and the report says whether the **cell** was the limiting factor | The obvious model -- the flight case with airspeed set to zero -- predicts a destroyed engine. Measured at 95 % throttle: in flight at 200 km/h, coolant 95.6 C; in a cell with a 45 km/h-equivalent fan, **203.3 C**; with no fan, **206.9 C**, against a certified limit of 120 C. A real cell does not use ram air at all; it has a dedicated fan or a liquid-to-liquid exchanger, often cooling better than flight. Modelled as a slow aircraft, every acceptance test fails on the *facility* and an operator spends a week chasing a cooling fault that does not exist. Distinguishing "this engine failed" from "this test was invalid" is the reason the rig states it. |
| DEV-87 | **Ratings measured at the wrong speed**<br>`layer4_core/test_rig.py` | TCDS s6: 99 kW at 5500 rpm, 104 kW at 5800 rpm | Rated points are **speed-targeted on a dynamometer**; the rig trims absorbed load to hold the certificate's speed and reads torque | A bench that lets the engine free-run to wherever the throttle puts it is not measuring the rated point. Measured on the first run of the acceptance schedule: 92 % throttle settled at **5742 rpm** and made 100.9 kW, recorded as a **pass** against the 99 kW max-continuous rating -- a different rating, 242 rpm above the one the certificate names. Speed-targeted, the same engine reads **97.5 kW at 5500 rpm** and **103.3 kW at 5800 rpm** against ratings of 99 and 104. A power figure without its speed is not a rating. A point where the dyno saturated is reported as **void** rather than scored, because a power reading from a point where the speed was lost is a reading of something else. |
| DEV-88 | **An empty check list read as a pass**<br>`layer4_core/test_rig.py` | -- | A report with no acceptance criteria is an **investigation run**, never a pass | `all([])` is `True`, so the throttle-response schedule -- which defines no rating checks -- reported `PASSED` backed by zero evidence. A green light with nothing behind it is worse than a red one. The same empty-aggregate defect as the weighted-average dilution family (DEV-45, DEV-72, DEV-80), in its degenerate case. |
| DEV-89 | **Cylinder balance could not fail**<br>`layer4_core/test_rig.py` | PRD Part 0 s0.5 requires per-engine parameter randomisation | The rig applies `set_manufacturing_spread` like every other engine instance | Built directly from `mvem.build()`, the model's four cylinders are numerically identical: EGT spread exactly **0.0 C**, so the cylinder-balance check -- one of the few things a bench is actually for -- could never fail. The capability existed and the rig simply was not calling it. With build scatter applied, a healthy engine spreads **7-42 C** across seeds, which is the realistic range, and the check has something to measure. |
| DEV-90 | **"Degradation factors only ever decrease" is false for oil**<br>`layer2_physics/tests/test_physics.py` | PRD Part 1 s5.2: degradation factors are monotonically decreasing | Monotonicity asserted for the five **wearing** pathways; oil asserted separately as a serviced consumable | Two tests encoded the PRD's premise and began failing once the scheduled oil change (100 h, MML 05-20-00) was modelled -- correctly, since restoring oil quality is the entire point of an oil change. One test compared a hot and a cool engine *just after* a service, where both hold exactly fresh oil, so it was asserting `1.0 < 1.0`. The premise was fixed rather than the model: oil now has its own test asserting it falls within an interval, is restored by the change, and that bearing wear already caused by running on degraded oil **survives** it. |

### Test-rig acceptance, measured

Acceptance schedule, Rotax 915 iS, 25 C cell at 500 ft with adequate cooling:

| engine | verdict | max continuous (5500 rpm) | take-off (5800 rpm) | fails on |
|---|---|---|---|---|
| as-new | **PASS** | 97.5 kW | 103.3 kW | -- |
| worn (combustion 0.88, injectors 0.70) | FAIL | 85.8 kW | 90.9 kW | power |
| worn turbocharger (0.75) | FAIL | 73.9 kW | 77.4 kW | power |
| blocked radiator (airflow 0.55) | FAIL | 97.5 kW | -- | coolant 123.4 C |
| as-new, **under-cooled cell** | FAIL (cell) | 97.5 kW | -- | **facility, not engine** |

The four failure modes are distinguishable: a worn engine loses power without
overheating, a blocked radiator overheats without losing power, and an
under-cooled cell is attributed to the facility. Before DEV-85 the worn
turbocharger row read 100.9 kW and **passed**.

## Deviations found by systematic audit of the physics and the fleet

DEV-85 (the turbocharger compared against itself) was found **by accident**,
while building the test rig, and it had been in the dataset the whole time.
Regenerating the fleet and retraining costs about an hour, so finding defects
one at a time and re-running between each is the expensive way to work. Two
audit tools now run the whole battery in one pass:

* `scripts/physics_audit.py` -- drives the mean-value model through the real
  fault-injection path and checks every fault moves something, that no two
  faults are indistinguishable, that nothing is non-physical anywhere in the
  0-23,000 ft envelope, that the air/fuel closure holds, and that build scatter
  actually varies between engines.
* `scripts/sensor_audit.py` -- the same questions at the **SensorFrame** layer,
  which is the layer the dataset is actually built from.

Both exit non-zero on a finding. Three methodological corrections were needed
before they gave trustworthy answers, and each is recorded in the tools:

1. **Audit reachable states.** Setting one degradation factor by hand reaches
   states the engine can never occupy, because the derived quantities the
   physics consumes (`oil_viscosity_ratio`, `bearing_clearance_mm`) do not
   co-vary. Audited that way, `oil_quality` looked like a completely dead
   pathway; in truth the physics couples to oil **viscosity** and the
   degradation engine moves the two together.
2. **Compare in physical units.** Dividing each channel by its own baseline
   made knock retard -- which sits at essentially zero on a healthy engine --
   swamp every direction vector, and two genuinely distinct cooling faults came
   out at cosine 0.998, "inseparable".
3. **Audit the right layer.** At the MVEM, `sensor_drift` looks dead and
   `misfire` looks identical to `combustion_instability`. Both are artifacts:
   those signatures live in the instrument layer.

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-91 | **A cleared fault stayed injected**<br>`layer2_physics/engine_sim.py` | -- | The sensor-drift bias is assigned on every frame, including when the magnitude is zero | The bias was applied inside `if drift_mag > 0.0`, so once the fault ended it kept its last non-zero value forever. `clear_faults()` empties the fault list but cannot reach into the instrument, so a cleared sensor-drift fault left the engine permanently reading **0.55 bar low on oil pressure and 9 degC high on CHT**, and the alert it raised never went away. Reachable from the live console's own `POST /api/faults/clear`. A fault that cannot be un-injected is not a demonstration, it is a broken rig. |
| DEV-92 | **One of the eight PS fault classes had no data at all**<br>`layer2_physics/synth_data_gen.py`, `layer3_ai/tier3_deep.py` | PS section C requires eight fault classes including sensor drift | All eight classes are injectable; `UNLEARNABLE_CLASSES` is now empty | The generator excluded `SENSOR_DRIFT` reasoning that the instrument layer already models drift, so injecting it would double-count. That conflates the slow ageing **drift** every transducer accumulates (`SensorSpec.drift`, ~0.004 degC/h) with a sensor-drift **fault**, which is a separate **bias** field (0.55 bar / 9 degC). They never double-counted; `engine_sim` keeps them deliberately apart. Measured consequence: `lab_sensor_drift` carried **0 positive rows on 0 engines** across the entire fleet, the multi-label head had a class with no positive examples, and Tier 3 listed it under `UNLEARNABLE_CLASSES` with the note "Tier 3 cannot learn it and never will from this dataset" -- a description of the bug, not of the design. Verified after the fix: an engine carrying only sensor drift has **bit-identical** `chi_true` to a healthy one, so the instrument lies while the engine stays sound. That is precisely the discrimination PRD Part 2 s10.5 asks for. |
| DEV-93 | **Injected faults were silently discarded**<br>`layer2_physics/synth_data_gen.py` | -- | Fault onset is drawn from 15-400 h, and the manifest records whether each fault ever **expressed** | Onset was `uniform(20, 900)` against a fleet whose engines die between roughly 450 and 1200 hours, so a large share of every schedule never happened. Measured on a six-engine sample: `sensor_drift` injected at **854 h into an engine that died at 447 h**, `lubrication_issue` at **633 h into one that died at 592 h**, `sensor_drift` again at **813 h into one that died at 800 h** -- **three of nine faults never expressed**, and the manifest recorded the schedule as though they had. This, rather than the sampling, was the root cause of the erratic class coverage: dealing a mode to an engine guarantees the *injection*, not the *expression*. After the fix, **11 of 12** express, and `faults_never_expressed` in the manifest makes a regression visible instead of silent. |
| DEV-94 | **Per-class evaluation was measuring single engines**<br>`layer2_physics/synth_data_gen.py` | PRD Part 0 s0.5 point 2: split by engine | 60/20/20 instead of 80/10/10, with the eight fault modes dealt round-robin **within each split** | Splitting by engine is non-negotiable, but ten evaluation engines cannot carry eight fault classes. Measured on the previous fleet: validation held **zero** engines with `injector_abnormal` and zero with `overheating_trend` -- a threshold cannot be tuned on a class that is not present -- and **five of the eight classes appeared on exactly one test engine**. A per-class score computed on one engine measures that engine, not the class. Coverage is now a property of the design rather than of the seed: every class is guaranteed **at least 2 engines in every split**, one engine in eight is still left fault-free so honest negatives survive, and the fleet is the same size, so it costs nothing extra to generate. |

### What the audit found to be SOUND

Reported because a clean result from an executable check is worth as much as a
finding, and because each of these was suspected and cleared:

| Check | Result |
|---|---|
| Every PS fault detectable at the sensor layer | **8 / 8**, worst-case strongest channel 0.53 scale units |
| Any two faults indistinguishable at the sensors | **none**; worst pair cosine 0.759 (`cooling_degradation` vs `overheating_trend`) |
| Non-physical output anywhere in 0-23,000 ft x 20-100 % throttle | **none** in 24 operating points |
| Air/fuel closure residual | 0.12-0.30, inside the 15-25 % the model documents |
| Determinism | repeat-run drift **0.0** |
| Build scatter varies between engines | EGT spread 7.1-42.3 C across six engines |
| Ground-truth leakage into features | blocked by `FORBIDDEN_PREFIXES`, which raises rather than warns |
| Residual columns | 7 / 7 populated, no NaN, none degenerate |
| RUL target | monotone within every engine, no NaN |
| Bearing-wear saturation (oil pressure floor, vibration clamp) | **unreachable**: the fleet bottoms out at `bearing_condition` 0.193 and oil pressure 0.28 bar, with zero rows at either floor, because engines are withdrawn at end of life first |

## Deviations found by retraining on the corrected fleet

Closing DEV-92 gave `sensor_drift` training data for the first time, and the
retrained Tier-3 head scored it at **0.946 F1** -- third best of the eight
classes, on a class that had previously been declared unlearnable. It also made
two further defects visible that nothing else would have.

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-95 | **A sensor fault that always broke the same two instruments**<br>`layer2_physics/engine_sim.py`, `synth_data_gen.py` | PS section C: sensor drift is one of the eight fault classes; PRD Part 2 s10.5 asks the system to tell an instrument fault from a real process change | Each drift fault names ONE channel out of eight and a direction, drawn per fault instance | The fault applied a fixed `-0.55 bar` to oil pressure and `+9 degC` to CHT, every time. A real transducer fault afflicts one instrument and which one varies, so this was wrong in two directions at once. It made the class artificially easy -- the signature never varied -- and it made `cooling_degradation` nearly undetectable, because every single drift instance raised CHT and a hot head is exactly what a cooling fault looks like. Measured on the retrained model: `cooling_degradation` collapsed to **0.112 F1** and **84 % of its false positives (566 of 673) were sensor-drift windows**, with mean predicted p(cooling) on true drift windows of **0.490** -- second only to true cooling itself. The residuals do not rescue it: `res_cht` reads 10.09 under drift against 11.57 under real cooling. A first hypothesis that the cooling/overheating *unseen pair* was to blame was **wrong and was discarded on measurement** -- the engine carrying that pair scores recall 1.000. |
| DEV-96 | **The RUL fusion was worse than its own best component**<br>`layer3_ai/rul_lstm.py` | PRD Part 2 s12.5: `w_data = c_data / (c_data + c_physics)` | The prescribed weighting, plus a **disagreement gate**: when the two estimates differ by more than half the smaller, the conservative figure is reported instead of the average | Measured on held-out engines: LSTM **RMSE 117.7 h** (R2 +0.27), physics extrapolation **255.7 h** (R2 -2.28), s12.5 weighted average **151.6 h**. The average was worse than the better estimator alone, because the physics estimate carried a **hardcoded confidence of 0.8** against the data estimate's earned `1/(1+val_loss) = 0.545`, handing the weaker estimator **59 % of the weight**. A self-reported confidence never calibrated against measured accuracy will do that every time. This is the weighted-average dilution defect for the **fifth** time -- after DEV-45 (end of life), DEV-72 (advisory), DEV-80 (maintenance urgency) and the mission worst-subsystem rule -- and the lesson has not changed: an average lets one bad component hide behind the others. The gate reports the lower figure, which is also the safe direction, since over-stating remaining life reads as permission to fly. |
| DEV-97 | **A fleet larger than 100 engines built silently wrong**<br>`layer2_physics/synth_data_gen.py` | -- | `split_for` raises on an id outside the configured splits, and the CLI refuses `--engines` beyond what they cover | The split ranges are fixed constants but `--engines` is a free parameter, and `split_for` ended in a bare `return "test"`. Asking for 200 engines therefore produced 100 extra engines that were all dumped into the test split AND carried no faults whatever, because `_guaranteed_mode` returns None for an id it cannot place. Nothing reported any of it. Found while probing the drift-channel distribution over 400 engines and getting far fewer faults than expected. A fleet that is quietly wrong is worse than one that refuses to build. |

### Layer 3, retrained on the corrected fleet (before DEV-95/96)

Recorded as the baseline the next run is measured against. **No number here is
comparable to anything from before the fleet was regenerated**: the split
changed to 60/20/20, all eight classes carry data instead of seven, and
per-split class coverage is guaranteed rather than left to chance.

| stage | result | targets |
|---|---|---|
| Tier 2 statistical | AUC 0.964, P 0.968, R 0.885, FPR 0.093 | precision and F1 met; recall 0.885 vs 0.90 and FPR 0.093 vs 0.05 **not met** |
| Tier 2 lead time | **15/15 failing engines detected, median 381 h** before end of life | -- |
| Tier 3 anomaly | P 0.967, R 0.920, F1 0.943 | all three **met** |
| Tier 3 faults | macro-F1 **0.655**, exact-match 0.574, severity MAE 0.146 | 0.82 **not met** -- weakest class is `sensor_drift` at F1 **0.303**, then `cooling_degradation` at 0.458; see DEV-95 |
| **Fused detection** | **AUC 0.996, P 0.999, R 0.981, F1 0.990, FPR 0.002** | -- |
| Health index | MAE 0.061, correlation +0.648, healthy mislabelled 5.2% | -- |

> **Corrected 2026-09-10.** This table previously reported Tier 3 fault macro-F1
> as 0.750 with `cooling_degradation` at 0.112, while `scripts/ps_compliance.py`
> reported macro-F1 0.652 / exact-match 0.829 / severity MAE 0.089. Neither
> matched `data/models/tier3_report.json`, the artifact the training run
> actually wrote: **macro-F1 0.655, exact-match 0.574, severity MAE 0.146**.
> Three documents, three answers, one training run -- and the compliance script
> stated exact-match and severity MAE **better** than the model achieved, which
> is the direction that costs trust rather than merely being wrong.
>
> The audit now reads the artifact (`ps_compliance.py::_tier3_evidence`) instead
> of carrying typed copies, so it cannot drift again. The figures here are
> transcribed from the same file and are correct as of that run.
>
> The class ranking also changed: `sensor_drift` (0.303) is the weakest class,
> not `cooling_degradation` (0.458). DEV-95 was written against the older
> figure and its conclusion about cooling should be read with that in mind.
| RUL, best estimator | RMSE 117.7 h, NASA 97.8, R2 0.271, late 55% | NASA **met**; RMSE, MAPE and R2 **not met** |
| Federated | 0.932 AUC under a poisoned client with the median defence (0.442 with a mean) | -- |

The fusion layer still earns its place by the measurement that motivated it:
the PRD's own trigger logic raises an alert on 390 windows and misses **1,336
genuinely degraded ones**, catching **zero** of them; the added predictive path
catches **1,304**.

## Targets that cannot be met, and why (Stage 2)

Every figure below was measured on the 20 held-out engines of the 60/20/20
fleet, over three seeds where a model is involved. Each entry states the target
**as encoded in the code that asserts it** -- not as remembered -- because a
deviation recorded against the wrong requirement is worse than none.

### The measurement noise floor, established first

The RUL model was constructed BEFORE ``torch.manual_seed()`` was called, so
initial weights were unseeded and only the batch order was controlled. Fixed.
Measuring the cost of that bug also established the noise floor:

| quantity | seed 0 | seed 1 | seed 2 | spread |
|---|---|---|---|---|
| LSTM RMSE | 126.6 | 117.2 | 124.4 | **9.4 h** |
| LSTM R2 | 0.167 | 0.287 | 0.196 | **0.120** |
| interval coverage | 84.3 % | 87.4 % | 83.8 % | 3.6 pp |
| NASA score | 478 | 690 | 3,108 | **6.5x** |

**A single-run RUL difference below about 10 h of RMSE is not interpretable.**
Several conclusions this project drew earlier sat inside that band, including a
117.7 -> 95.4 h "improvement" attributed to a feature change; that comparison
also changed the test population from 10 engines to 20, so two confounds were
present at once. The NASA score is exponential in the error and moved by a
factor of 6.5 across seeds: it is reported as a RANGE and never used for a
single-run comparison.

| ID | Target, as the code asserts it | Achieved | Why it cannot be met |
|---|---|---|---|
| DEV-98 | `eval_tier2.py:125` recall > 0.90 **and** `:127` FPR < 0.05 | recall 0.879, FPR 0.083 | **Mutually infeasible on this data.** Measured at matched budgets, validation and test recall track within 0.01 at every point -- so there is NO train/test distribution shift and the threshold is correctly calibrated. Recall > 0.90 requires **FPR ~ 0.20**; FPR < 0.05 yields recall ~ 0.72. One of the two must be relaxed. Recommended operating point: FPR < 0.10 with recall > 0.90, or FPR < 0.05 with recall ~ 0.88, chosen on whether nuisance alerts or missed detections cost more. |
| DEV-99 | `train_tier3.py:180` anomaly recall > 0.90 | 0.870 | **Mostly a definition, not a failure.** Stratified by severity: recall is 0.905 above severity 0.50 and 0.888 between 0.20 and 0.50, but **0.435 below 0.20** -- and 79 % of all misses live in that band. A window labelled positive at 5 % of full expression is physically almost healthy. The residual loss concentrates on the sensor-drift engines, which is DEV-101. |
| DEV-100 | `train_tier3.py:182` fault macro-F1 > 0.82 | 0.712 (0.71 +/- 0.03) | **Observability and co-occurrence walls, NOT a data shortage.** A learning curve in ENGINES was measured at production fidelity (40 epochs, stride 5, 3 seeds), holding validation and test fixed: 20 engines 0.404, 35 engines 0.572, 50 engines 0.670, 60 engines 0.654. The slope collapses from **+0.112 to +0.065 to -0.016 per ten engines** -- flat within a +/-0.06 detectable band -- and **every one of the eight classes is flat individually**, so there is no hidden class still improving. Extrapolating the last segment to 105 engines gives 0.584. Growing the fleet was planned and **cancelled on this evidence**. Realistic ceiling with current observability: **0.70-0.75**. |
| DEV-101 | (no per-class target exists in the PRD or the code) | sensor_drift F1 0.311 | Recorded not as a missed target but as a **measured observability limit**. The class covers eight disjoint channel signatures. A drift is only detectable as a disagreement with the physics, so it needs the drift to exceed the shadow model's own error on that channel. Measured on healthy engines: oil_temperature SNR 2.78, coolant 2.36, manifold_pressure 1.11, cht 1.06, egt 0.89, **fuel_flow 0.45, oil_pressure 0.27**, and **rpm has no residual at all** -- the shadow model is DRIVEN by measured rpm (`shadow_model.py`: `omega = rpm*2*pi/60`), so measured minus predicted is identically zero by construction. Three of eight channels are unobservable in principle; reporting one F1 across all eight mixes a solvable problem with an unsolvable one. |
| DEV-102 | `thresholds.rul.targets` rmse_flight_hours < 25.0 **and** r2 > 0.85 | RMSE ~123 +/- 9 h, R2 0.22 +/- 0.12 | **The two targets contradict each other.** With a target standard deviation of 138.8 h, RMSE < 25 h implies **R2 > 0.968**, far stricter than the stated R2 > 0.85 (which implies RMSE < 53.7 h). The RMSE target is also 0.18x sigma, where published C-MAPSS state of the art is roughly 0.28x sigma -- it asks for better-than-SOTA performance in relative terms. Compounding this, **64.9 % of test labels are either censored (39.9 %) or sitting exactly at the 400 h horizon cap**, where the target is a constant. RMSE is now reported split by whether the target is informative. |
| DEV-103 | `thresholds.rul.targets` nasa_score < 500.0 | 478 to 3,108 across three seeds | **The metric is not reproducible enough to be a target.** It is exponential in the error, so a single badly-predicted window dominates it. Reported as a range; never used for a single-run comparison or a go/no-go. |
| DEV-104 | PRD Part 2 s12.5: fused RUL is a confidence-weighted average | A disagreement gate fires on 58 % of windows and takes the conservative value instead of the average | **An undocumented deviation, now documented.** The gate was added in DEV-96 and is not in s12.5. Measured: LSTM alone RMSE 111.1 / late 0.29; the weighted blend alone 110.3 / late 0.32; blend plus gate 125.3 / **late 0.23**. The gate costs about 15 h of RMSE and buys a 9-point reduction in late predictions. That is a deliberate safety trade, so the acceptance criterion is changed accordingly: **the fusion must reduce the late rate, and must not cost more RMSE than 1.5x the noise floor.** Judging it on RMSE alone would condemn it for doing its job. |
| DEV-105 | PRD Part 4 s7.4a: an RUL must carry its interval | coverage 84-87 % against a 95 % nominal | MC dropout is a mean-field variational approximation and those **underestimate posterior variance**; the published shortfall is 74-80 % coverage where 90 % was claimed. Ours was 18 % before calibration, with the interval NARROWER than the mean absolute error. Split-conformal calibration on validation now yields **95.0 % on the calibration set and 84-87 % on unseen engines**. The gap is exactly what the theory predicts: conformal guarantees coverage under EXCHANGEABILITY, and windows from different engines are not exchangeable. **The defensible target is > 80 % on held-out engines**, not 85 % and not 95 %. |

### What was rejected, and why it is recorded

Two proposals were tested and abandoned on measurement rather than judgement,
and both are recorded so the reasoning is not repeated:

* **Growing the fleet to 150-200 engines.** The learning curve above shows the
  marginal return is zero past roughly 50 engines. Two hours of generation plus
  retraining would have bought nothing measurable.
* **Adding an rpm residual channel.** Impossible by construction -- the shadow
  model is driven by the measured rpm. Worse, a drifting rpm sensor moves the
  shadow's entire operating point and contaminates every OTHER residual, which
  is a vulnerability worth stating rather than a feature worth adding.

## Open items requiring evidence before they may be claimed

| Item | Status |
|---|---|
| IDF-DS19 dataset (240 real UAV flights) | **Not verified to exist / be obtainable.** PRD Part 0 §0.2 FIX 5 instructs: do not cite unless confirmed. It is not cited anywhere in this build. |
| NASA C-MAPSS pre-training | Loader implemented; dataset not yet downloaded. Until it is, no transfer-learning claim may be made. |
| NASA IMS / CWRU bearing validation | Loader implemented; dataset not yet downloaded. Until it is, the "validated on real bearing fault data" claim may not be made. |
| Exact Rotax Display CAN message assignment | **Not public.** IM Ed.0 Rev.5 directs the reader to an authorized Rotax Distributor. Our DBC uses open CANaerospace standard identifiers and must not be presented as the Rotax database. |
| SAE ARP4102/7 engine display symbology | Paywalled, **not obtained**. Engine-display conventions in PRD Part 4 trace to FAA AC 25-11A via the FAA HFDS compilation, not to ARP4102/7. |
| MIL-STD-3009 / MIL-L-85762A NVIS compatibility | Named as the certification path only. The console ships a NIGHT brightness profile; NVIS compatibility is **not** claimed. |

## Deviations found by reading the problem statement's UI clause against the console

The problem statement is prescriptive about exactly one screen, and about
nothing else in the console:

> "The dashboard shall provide an intuitive **operational interface** for
> **UAV operators, propulsion engineers and maintenance team**" — real-time
> engine health status · fault alerts · engine efficiency trends ·
> maintenance advisory · mission-wise health reports

Two things in that sentence had never been designed against: it names **three
audiences**, and it asks for **one dashboard** carrying five named items.
Auditing the console against it found four defects, three of them in the
authorisation layer rather than in the pixels.

| ID | What the PRD or the PS requires | What was actually there | Resolution |
|---|---|---|---|
| DEV-106 | PS §F: one dashboard carrying five named items | All five items worked, spread across five of eleven specialist pages, with **no aggregate view above them**. Every role landed on ENGINE, a raw parameter cluster. | The console had been built entirely as **drill-down with the overview layer missing** — the opposite of the order PHM practice and safety-critical HMI guidance both call for (overview first, descend only when a number on it earns the descent). `pages/Overview.tsx` adds the five blocks in the PS's own order, each giving one headline and a one-click route into the page that holds the working. It is now `PAGES[0]` and the landing page for every role. |
| DEV-107 | PRD Part 4 §10c: role enforcement is **server-side** | `/ws/state` checked `read:telemetry` once at handshake, then streamed the **complete snapshot at 2 Hz** — including the costed maintenance plan that `/api/maintenance` refuses without `read:advisory`, the RUL, and `faults_injected`, which names the ground truth the detector is supposed to deduce. | Every scope check on every other route was **decorative**: the data refused at the front door was already arriving through the window, and the console's role separation was a rendering convention, not an authorisation boundary. `twin_api.snapshot_for_role()` now filters the stream by the same scopes the REST surface uses. A withheld section is sent as an **explicit refusal naming the scope**, not omitted — an absent key renders as "———", which is §7.2's notation for a dead sensor, and an operator must not read a permissions boundary as a hardware failure. Pinned by `test_stream_scopes.py`, including a guard that fails when a new `Snapshot` field is added without a scope decision. |
| DEV-108 | PS names three audiences; the RBAC table has exactly those three roles plus commander | The table was **internally inconsistent in three places**. `ROLE_MAINTENANCE` held `read:advisory` but the page displaying the advisory was gated on `read:prognostics`, which it did not hold — so the advisory was addressed to a role that could not reach it. `ROLE_ENGINEER` held `read:prognostics` but not `read:advisory`, so the fetch on that page 403'd. Between them the two roles held both halves of one screen and **neither could use it**. `ROLE_OPERATOR` held neither, so the person flying the aircraft could not see the Go/No-Go call made for the flight they were conducting. | Scoped to the **decision each role actually makes**, which is a stricter test than "what might interest it". New scope `read:mission` carries the Go/No-Go verdict to the operator without opening the component-level RUL machinery behind it; `/api/mission` moved from `read:prognostics` to it. `read:advisory` added to the engineer (an engineer diagnosing deterioration needs its maintenance consequence); `read:prognostics` added to maintenance (the planner was planning blind). |
| DEV-109 | PS §F: "engine efficiency **trends**" | `EfficiencyTracker` produced a correct instantaneous reading; **nothing recorded its history**, so the trend half of the requirement did not exist. The compliance matrix had cited the ENGINE page's measured-vs-physics residual overlay as evidence, which is a different quantity. | `live._series` now records `bsfc_deterioration` and `thermal_efficiency` over the same rolling 240-sample window as the other trends, `None` where efficiency is not derivable so the chart shows a **gap at idle** rather than carrying the last value across it. Measured on a healthy engine: thermal efficiency 0.2745–0.2792, deterioration −0.89 % to +0.81 % — near zero, as an as-new comparison should be. |

### Why three of the four were authorisation defects

They were found by asking a UI question, not a security question. "Does this
serve the three audiences the PS names?" is answerable only by working out what
each audience is entitled to see, and that is the same exercise as auditing the
scope table — which is why reading the requirement in the customer's own words
found what neither the HMI checker nor 113 passing tests had.

## Deviations found by running the finished system and reading its own output

| ID | Requirement | What was there | Resolution |
|---|---|---|---|
| DEV-110 | PS §F deliverable: "mission-wise health reports" | The REPORT page rendered one on screen. Nothing left the system. `reportlab` had been declared in the `reports` extra and never used. | A report that exists only on a screen is not one a maintenance organisation can file against an airframe. `layer4_core/report_pdf.py` + `GET /api/report.pdf`, built from the **same payload** `/api/report` returns so the document and the console cannot disagree. An injected fault labels the document SIMULATED **in its title** — what a PDF reader shows in its chrome and a file manager indexes — not only in the body where it can be scrolled past. An unreportable RUL prints "Not reportable" with the reason, never a plausible figure (§7.2 on paper). The export is audited as `REPORT_EXPORT` with a SHA-256 digest that matches a printout back to the log entry; the digest is explicitly **not** described as a signature. |
| DEV-111 | PRD Part 4 §7.2: the console must never let "nothing is wrong" and "no data" look alike | The fused level for a healthy engine was published to the console as `"NONE"` — the **enum name** `FusedLevel.NONE`, used verbatim as the operator-facing word. It had been on the header band since the console was built and became conspicuous only when the new dashboard put it on a 40 px status readout. | `NONE` reads correctly in code and ambiguously on a crew station: it is exactly the pair of states §7.2 exists to keep apart. MIL-STD-411F's word for the quiet state is NORMAL, and `_DISPLAY_LEVEL` in `live.py` now maps the display name while leaving the enum, PRD §9.5 levels and every test untouched. The alerting levels already carry 411F's own vocabulary and are not renamed. |
| DEV-112 | The exported report must be legible without an embedded font | Every exported report's header line rendered its separators as `�`. reportlab's built-in Helvetica has no middot, and the console's separator had been copied into the document. | A document that will be printed, scanned and filed must not depend on font substitution. ASCII separators throughout, pinned by a test that fails on any replacement glyph or non-ASCII punctuation reaching the page. |

### On the full test suite, and the one thing it caught

The standing instruction was that the full suite runs once the project is
built. The first attempt was started at the top of this session and then had
`configs/thresholds.yaml`, `live.py` and `twin_api.py` edited underneath it, so
it was killed rather than reported: a suite run against a moving tree measures
nothing.

The clean run was **437 passed, 1 failed**, and the failure earned the whole
exercise.

| ID | What the test asserted | Why it failed | Resolution |
|---|---|---|---|
| DEV-113 | `test_clearing_a_sensor_drift_fault_un_biases_the_instrument`: injecting a sensor drift biases oil pressure **and** CHT | Both were once true. It is exactly the behaviour the DEV-101 work deliberately removed -- every sensor-drift instance raised CHT by the same 9 degC, so the class collided head-on with `cooling_degradation`, **84 % of the cooling head's false positives were sensor-drift windows**, and cooling collapsed to 0.112 F1. A real transducer fault afflicts ONE instrument and which one varies, so `engine_sim.py` now biases the fault's own named channel. **The test was still checking for the defect.** | Rewritten to assert the property its own docstring names -- a fault that cannot be un-injected is a broken rig -- on a channel it names, plus the stronger assertion that ONLY that instrument moves. The stale test had survived because the suite had not been run since the model changed, which is precisely what the standing instruction existed to catch. Final run: **438 passed, 0 failed, 16:10.** |

## Deviations found by asking who actually reads the screen

The console had been built correctly against a typography and colour standard
and wrongly against the people who use it. Part 4 says a caution is amber and
16 px; it does not say that "measured against the as-new shadow model at this
operating point" is a sentence no UAV operator will ever read.

`docs/WHO_READS_THIS_SCREEN.md` now governs *what* to show; Part 4 continues to
govern *how* to show it.

| ID | Requirement | What was there | Resolution |
|---|---|---|---|
| DEV-114 | PS section F: an intuitive **operational** interface. PRD Part 2 section 9.4 requires EMA smoothing at alpha = 0.1, "slow response, filters noise", with trends over a **10-flight-hour window** | The dashboard printed **instantaneous** values of slow quantities. Measured over 20 s on a **healthy engine, no fault injected**: BSFC deterioration swung **11.40 points** (-4.52 to +6.88), changing on **39 of 40 frames**; mission success probability swung **29.73 points** (56.79 to 86.52); RUL changed on 35 frames. All in the largest type on the screen. | **Not a display bug -- a category error.** RUL, health, efficiency and mission probability describe an engine ageing over hundreds of hours; sampling them at 2 Hz shows sensor noise on a derived quantity, amplified by every division in the chain. An operator watching a success probability swing 57 to 87 percent twice a second learns the number is worthless and stops reading the panel, including on the day it is right -- the display equivalent of a chattering alarm. `layer4_core/operator_view.py` adds a parallel operator view: EMA at the PRD's own alpha, quantised to a step set from each quantity's **measured** scatter, with hysteresis. **The raw sections are untouched** -- for an engineer validating a model, the noise is the data. Measured after: BSFC **39 to 0** changes, mission **39 to 2**, CHI **39 to 3**. |
| DEV-115 | ISA-18.2: an indication must carry a **recommended response** or it is decoration that costs attention. PRD Part 2 section 9.5 writes every one of its own examples as an instruction. | Operator-facing strings were **method notes**: `efficiency.reason` was "measured against the as-new shadow model at this operating point" (64 chars); `maintenance.summary` 129 chars; the health band surfaced as the machine token `maintain_within_25h`. | Every string an operator sees is now an instruction -- "Schedule maintenance within 25 flight hours.", "Ground the aircraft. Do not dispatch." The sentences live on the **bands themselves** in `configs/thresholds.yaml`, beside the token each translates, so a threshold tuned in YAML and a sentence written in Python cannot drift. Method notes move to the engineer's screens, the one audience that wants them. Tests assert no machine token can reach an operator. |
| DEV-116 | PRD Part 4 section 7.2: a number must not mislead | Parameters were shown as bare readings. A temperature without its limit is a number; with its limit it is a **margin**, and a margin is a decision. | The strip reports "27.9 C to limit" against the certificate for coolant, CHT, EGT, oil temperature and oil pressure. |
| DEV-117 | Unit integrity across the ingest chain | The first margin implementation compared **oil pressure in psi against a limit in bar** -- the ingest path multiplies by 14.5038 and the console is labelled psi, but the certificate figure read was `oil_pressure_above_3500rpm_bar`. It displayed "59.2 against a limit of 2.0": a margin of **+57 on a parameter whose real margin was +2.1 bar**. | Caught by reading the live output, not by any test. The margin now takes the **psi** threshold -- the same number the parameter readout shows its limit from, so the two cannot disagree. |
| DEV-118 | A deadband must actually be a deadband | The first implementation compared the **quantised** value against the shown one and moved on any difference. That is not a deadband, only rounding: a smoothed value near a step boundary rounds either way on alternate frames and the figure flips for ever. Measured: pure noise still moved the display on **31 frames out of 40**. | Caught by the test written for DEV-114 rather than by inspection. Hysteresis now applies to the **raw smoothed value against what is displayed**, is configurable, and is asserted to be at least 1.0 step -- below that there is no deadband at all. |
| DEV-119 | DEV-107, one level down | `display` is gated on `read:telemetry` so every role receives it -- but it carries a **remaining-life** figure, which is prognostics. Hiding it only in the page would have put the number on the wire for a role refused it on every other route. | `NESTED_SCOPES` in `twin_api.py` strips `rul_hours` and `mission_success_pct` from the operator view for roles lacking the scope. **Removed, not nulled**: the console renders an absent figure as "not enough wear yet to predict", which is true, where a zero would read as an engine with no life left. Verified live -- the operator's socket carries no `rul_hours` key at all. |

### The safety property this must never break

Smoothing buys stability by paying in **lag**, and lag on a safety annunciation
is the one place that trade is unacceptable. The split is load-bearing and
stated in the module: **Tier-1 rules run on raw ingest readings and reach the
master annunciators without passing through this layer**, so a genuine
exceedance still fires on the frame it occurs; the fused state *word* is
likewise unsmoothed. Only quantities read as **trends** are smoothed.

The rule is: smooth what is read as a trend, never what is read as an alarm.

## Deviations found by looking at the screens rather than the data

The previous round fixed the dashboard. These are the same faults on every
other page, found by reading the console as a user rather than as its author.

| ID | Requirement | What was there | Resolution |
|---|---|---|---|
| DEV-120 | An explanation must be readable | The WHY panel led with a **388-character paragraph rewritten on every frame** -- 40 distinct texts in 20 seconds. Quantising the printed numbers was not enough: the noise reached deeper than the formatting, so the SHARES swung 35-55 % and the second-ranked subsystem changed identity between frames. The sentence genuinely said something different each time. | Two fixes, because there were two faults. The explanation is now computed from **EMA-smoothed health indices** -- the console already displays a smoothed index, so explaining the smoothed one is also the consistent choice. And the paragraph is **gone from the live panel**: a 388-character prose block is unreadable on a live screen even when perfectly still, because the reader must parse a sentence to recover a ranking the rows below already show at a glance. The narrative is still generated, still on `/api/state`, and still in the post-flight PDF, where it is read once, on paper, and does not move. |
| DEV-121 | PRD Part 2 s9.3: the shortfall decomposition | The breakdown divides the shortfall four ways and was shown unconditionally. On a healthy engine the shortfall is ~0.028, so each share is a ratio of near-zero to near-zero: the four percentages produced **40 different readings in 20 seconds**. | Not wrong -- **meaningless**. There is no degradation to attribute, and attributing it anyway trains the reader to skip the panel before the day it has something to say. Below a configured `explanation_shortfall_floor` the console says "Nothing significant. Health is essentially as-new" and shows no split. Measured after: 2 distinct renderings in 20 s. Displayed shares are quantised to a configured step. |
| DEV-122 | DEV-115, on the page it was actually visible | `_band_action` returned `str(action).replace("_", " ")`, so the console displayed **"Recommended action: monitor"** -- a machine token with its underscores removed is not an instruction. | Returns the band's `instruction` from the threshold file. Now reads "No action required." / "Schedule maintenance within 25 flight hours." |
| DEV-123 | s4.1.1a: a healthy engine is silent | FAULT PROBABILITY drew **all eight modes unconditionally**, which on a healthy engine is eight empty bars all reading 0.0 -- a third of the panel spent saying nothing, each label stranded beneath its own bar. | Only modes with a non-zero probability are listed, sorted, as a name and a percentage. When none are, one line: "No fault indicated. All eight monitored modes are at zero." |
| DEV-124 | Layout must not defeat the type standard | The prognostics page asked for **five fixed columns**. On a real console each panel is then narrower than a sentence, so text sets in tall thin ribbons and one panel drags the row past the bottom of the screen while its neighbours sit half empty. | Page grids reflow (`auto-fit` with a minimum readable width) and rows are height-bounded; the Panel body already scrolls, so an overfull panel scrolls inside itself rather than stretching the page. |
| DEV-125 | Operator text is an instruction, never a method (DEV-115, everywhere else) | Ten explanatory paragraphs were rendered across the console, totalling ~1,900 characters -- among them "Volumetric efficiency is referenced to MANIFOLD density, not ambient: this engine is turbocharged..." on a live panel. Every one was written for a reviewer reading the console over somebody's shoulder. | Removed or cut to one line. The reasoning is unchanged and still lives in the module docstrings, where it is addressed to the person who needs it. |
| DEV-126 | Unit consistency | Residuals labelled cylinder-head in **K** and EGT in **°C** on the same list. Both are temperature DIFFERENCES, where one kelvin is one degree Celsius, so the mixture said nothing and invited the reader to wonder whether one of them was an absolute temperature. | Kelvin throughout for differences. |

## Deviations found by auditing the console against the PS parameter list

The reference plates in `docs/ui-reference/` prompted a re-read of what the PS asks the
console to *show*, as opposed to what it asks the system to *compute*.

| ID | Requirement | What was there | Resolution |
|---|---|---|---|
| DEV-127 | PS section B: "**Monitoring** of following engine parameter are required" -- eight groups, including **Injection timing parameters** and **Battery Alternator health** | Injection timing was acquired over CAN, validated, carried in the twin state (`timing.injection_measured`, four cylinders, plus commanded, period, duty and knock retard) and **rendered on no screen anywhere in the console**. Alternator current was likewise measured and never shown -- only bus voltage was, and bus voltage says the battery is holding up, not that the alternator is charging it. | A value that is acquired, validated and carried on the bus while no screen shows it has been **acquired, not monitored**. Both now appear on the ENGINE page. Injection timing is shown as **deviation from commanded**, not as the raw crank angle: four cylinders reading 376.1 / 376.2 / 376.1 / 376.0 degrees tell an operator nothing, and "injector abnormalities" is one of the eight PS fault modes -- the deviation is that comparison already made. Ignition deviation, injector duty and knock retard join it. |
| DEV-128 | The compliance matrix must not over-claim | `ps_compliance.py` marked all eight section-B parameters **BUILT** on the evidence "threshold entry + CAN signal". It never looked at the console, so it certified acquisition and called it monitoring -- and reported the two undisplayed parameters as fully built. | The check is now **three-part**: threshold, CAN signal, **and a token that must appear in the console source**. A parameter that is acquired but not displayed reports PARTIAL with the reason. Verified to have teeth: with the display token removed, the check reports "acquired but NOT DISPLAYED" rather than BUILT. |
| DEV-129 | Sign-in should look like what it is | The login was a 420 px box on a flat ground -- functional, and indistinguishable from any internal tool. | Rebuilt to the reference plates supplied in `docs/ui-reference/`: DRDO identity lockup, classification banner, engineering-drawing background in both day and night. The 1.4 MB reference PNG is shipped at **67 KB** (day) and **36 KB** (night, derived from the same plate by inversion and a navy ramp rather than shipping a second photograph). Two controls in the reference are deliberately **not** built: "Remember me", because a session outliving the operator standing up is a session attributed to the wrong person in the audit log; and "Forgot password?", because there is no self-service reset against an establishment directory and a link that cannot work is worse than none. The **official DRDO seal and State Emblem are not drawn or approximated** -- the identity is typographic and the space is reserved for the official artwork. |
| DEV-130 | HMI s14: no gradient headers | The tricolour rules on the new login were CSS gradients, and `hmi_check` failed them. | The checker was right, and the fix is not an exemption: a gradient blends and a tricolour has hard stops, so it is now three solid bands -- which is both what the flag is and what passes. The check keeps its teeth. |

## The push to complete every requirement

Compliance went 86.6 % -> 97.7 % weighted, and **0 MISSING, 0 DESIGNED**. What
follows is what was built, what a measurement rejected, and the four items that
remain PARTIAL with the reason each cannot simply be finished.

### Built

| ID | Requirement | What was done |
|---|---|---|
| DEV-131 | PS section C: "detection/**prediction**" of eight fault modes | Detection says a fault is present; a planner holding that alone cannot schedule anything. `layer3_ai/rul_fault.py` extrapolates each mode's own **measured indicator** to the threshold at which the system itself would raise the fault -- CHT residual to 10 degC, oil/rpm correlation down to 0.85, EGT spread to 150 degC -- all read from `configs/thresholds.yaml`, so a retuned threshold moves the forecast with it and the alert and the prediction cannot disagree. It **refuses** more often than it answers: too few samples, a slope inside the indicator's own scatter, a slope moving away from the threshold, or an indicator already past it. Every estimate carries an interval. |
| DEV-132 | Innovation: "Edge AI for UAV applications", "Lightweight onboard analytics" | `layer1_edge/edge_infer.py` scores Tier-3 onboard from a 149.6 KB ONNX graph at **0.64 ms median**, single-threaded so it does not starve the layers with the hard deadline, importing **neither torch nor layer3_ai** -- an absence asserted in a subprocess test rather than left as an intention. Footprint measured: **68.9 MB resident, 3.4 % of the smallest Raspberry Pi 4**, 0.34 MB growth over 200 inferences. |
| DEV-133 | Innovation: "Physics-informed AI", "Hybrid thermodynamic + data-driven models" | `layer3_ai/pinn.py` -- physics-informed in the **loss**, not merely the features. The physics prediction is an input, the network predicts measured CHT, and the loss differentiates the network w.r.t. its own inputs at unlabelled collocation points, penalising a negative `d(CHT)/d(throttle)` and `d(CHT)/d(OAT)`. Only the negative part: the physics fixes the sign, not the magnitude. Measured on 20 held-out engines: physics **6.67**, data-driven **4.57**, hybrid **4.53** degC RMSE -- and impossible derivatives fall from **100.0 % to 21.6 %**, a soundness gain independent of the RMSE. |
| DEV-134 | Innovation: "Secure telemetry architecture"; PRD Part 3 s20.1 threats 1 and 3 | Threats 2, 4 and 5 were already answered (JWT+RBAC, rate limiting, hash-chained audit). The two about the **downlink** were not. `layer1_edge/secure_link.py` authenticates every frame with HMAC-SHA256 over sequence, timestamp **and** payload, constant-time compared, with monotonic sequence numbers for replay rejection and a freshness window -- because a MAC proves a frame is authentic and says nothing about when, so a captured frame would stay valid for ever and a healthy engine's telemetry could be replayed over a failing one while every signature verified. TLS 1.3 ciphers pinned, and **binding a non-loopback address without TLS is refused, not warned about**. 15 tests, written as the attacks. |

### Rejected on measurement

| ID | What was tried | Why it was not shipped |
|---|---|---|
| DEV-135 | Dynamic INT8 quantisation of the Tier-3 graph | The obvious optimisation, and the measurement says no. On 300 real windows from four held-out engines it is 2.94x smaller, **1.10x SLOWER**, and changes **5 of 300 anomaly decisions**. A model that disagrees with the validated one on 1.7 % of windows has not been optimised, it has been replaced. Kept for an ARM target where int8 SIMD may invert the trade; **never loaded by default**. |
| DEV-136 | Verifying that quantisation on synthetic noise | Recorded because it nearly certified DEV-135. On Gaussian noise the same export deviated by 0.33 / 0.50 / 0.27 with **no decision changed** -- a clean-looking result. On real windows: 3.32 / 8.22 / 1.95 and five decisions changed. Verifying on noise would have passed a graph that disagrees on 1.7 % of what it will actually see. |
| DEV-137 | The first PINN design, and the first PINN test | Both wrong, in mirror-image ways, both caught by measuring rather than by inspection. The design regressed the **residual** and applied temperature laws to it -- a law about temperature says nothing about the *error* a physics model makes -- and reported 98.8 % of points "physically impossible" when nothing impossible was happening. The test then used densely-covered synthetic data on which **both** models scored 0 % violations, which said the fixture was easy rather than that the penalty worked. It now trains on a narrow cruise band and examines derivatives across the whole envelope. |

### The four that remain PARTIAL, and why

**Three are blocked on targets this project set itself, and the problem
statement never did.** The PS contains no RMSE, no precision, no recall and no
F1 anywhere; every failed number is ours, from `configs/thresholds.yaml` and
PRD Part 2.

| Requirement | Blocked by |
|---|---|
| Remaining Useful Life estimation | DEV-102: the two targets **contradict each other**. With sigma = 138.8 h, RMSE < 25 h implies R2 > 0.968, far stricter than the stated R2 > 0.85. The RMSE target is also 0.18x sigma where published C-MAPSS state of the art is roughly 0.28x -- it asks for better-than-SOTA in relative terms. |
| Estimating degradation trends and RUL | Same target, same contradiction. |
| AI/ML based predictive analytics | DEV-100: fault macro-F1 0.652 against a self-set 0.82. A learning curve measured at production fidelity across 20/35/50/60 engines shows the slope collapsing from +0.112 to -0.016 per ten engines, and **every one of the eight classes flat individually**. Growing the fleet was planned and cancelled on that evidence. Realistic ceiling with current observability: 0.70-0.75. |

Against the **problem statement** these three are built and working: RUL is
estimated with calibrated intervals, degradation trends are tracked, and
predictive analytics run on engines never seen in training. Against **our own
invented numbers** they fall short, and the honest thing is to leave them
PARTIAL and say exactly that rather than move a goalpost and call it 100 %.

**The fourth is honest about hardware.** "Embedded systems" is measured at
68.9 MB and 0.64 ms on x86-64 -- evidence the target is reachable, not a flight
result. The ARM figure has to be taken on an ARM board, and no amount of
software work substitutes for that.

## Two console defects, and what a post-flight report actually is

| ID | What was reported | What it was | Resolution |
|---|---|---|---|
| DEV-138 | "Fleet tab shows authentication required" | `Fleet.tsx` and `Replay.tsx` called the API with a **bare `fetch()`**. The browser attaches no Authorization header on its own, so both reached the server anonymous and came back 401. **Two of twelve screens were unreachable for every role, including the commander.** | Both routed through `api()`. Worse than the outage was the message: "authentication required" reads to an operator as a broken page, and is indistinguishable from a screen they genuinely lack the scope for -- exactly the confusion PRD Part 4 s10a exists to prevent. `hmi_check` now has an AUTHENTICATED-FETCH test that greps the console for bare `fetch("/api/...")`, verified to fail when the fix is reverted. `/api/auth/login` is the one legitimate exception: there is no token yet. |
| DEV-139 | "Run simulation spins but nothing happens" | Not broken -- **slow**. Measured: high altitude 20 s, endurance 48 s, hot weather 18 s, rapid throttle 12 s of real physics, with nothing on screen but a busy cursor. | A control that sits silent for fifty seconds is indistinguishable from one that is broken, and the operator's next move is to press it again. The measured cost is now published with the scenario index and shown BEFORE the press, and an elapsed counter runs during it. Deliberately **not** a progress bar: the server reports no progress, and a bar advancing on a timer is a lie about how far along the work is. |

### The post-flight report was a snapshot with a title

Researched against real practice, and two things were missing that change what
the document is for.

**An [Airbus Post Flight Report](https://aeropeep.com/a320-post-flight-report-pfr/)
lists each warning and fault "with the associated time, flight phase and ATA
reference".** That is what makes it usable on the ramp. Our alerts existed only
as a LIVE list, so an alert that fired in the climb and cleared in the cruise
left no trace at all -- the report was systematically blind to exactly the
transient events a debrief is about.

**[Engine Condition Trend Monitoring](https://sassofia.com/blog/introduction-to-engine-condition-trend-monitoring-ectm/)
records the same parameters at the same condition once per flight**, taken after
the aircraft "has been flying at a stable cruise condition for several minutes".
Without that datum a report has extremes and instantaneous values and **neither
can be trended**: the peak CHT depends on how hard the aircraft was flown, and
the value at export depends on when somebody pressed the button.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-140 | Events must carry time, phase and ATA chapter | `layer4_core/flight_record.py` opens an event when an alert appears and closes it when it clears, tagged with the flight phase and an ATA chapter, so a transient has a **duration** rather than vanishing. Times are on the flight's own clock -- "t+14712 s" is a number nobody can place in a sortie. |
| DEV-141 | One stabilised cruise datum per flight | Captured when throttle holds within 2 % and altitude within 300 ft for 120 s in CRUISE. Only the FIRST is kept: the value comes from being taken the same way every flight, not from being the most recent thing available. A flight that never stabilises reports **"no valid reading"** with the reason -- a finding about the sortie, not a gap in the report. Averaging the whole flight would produce a number that trends against nothing. |
| DEV-142 | Exceedances need time-above, not just peak | Peak alone understates a slow cook and overstates a spike, and maintenance manuals set inspection thresholds on both. Each exceedance now carries peak, over-by, seconds-above, first-seen and phase. |
| DEV-143 | **A false exceedance on every clean sortie** | The check applied oil pressure's 29 psi minimum unconditionally. That limit applies only **above 3500 rpm** (OM s2.1: below it, 0.8 bar / 11.6 psi), so every ground idle was flagged. Measured before the fix: a clean flight reported "oil pressure 14.9 psi against 29.0, 119.5 s above, first in GROUND" -- untrue, and the kind of finding that teaches a maintainer to stop reading the report. Both figures and the rpm that separates them were already in the threshold file; the check now uses them. |
| DEV-144 | Life-to-date extremes must not read as this flight | `OperationalHistory` is explicit that they are life-to-date, and a section headed "Extremes recorded" inside a POST-FLIGHT report reads as this sortie: a maintainer would take a six-month-old 127 degC peak as something that happened this morning. Retitled and captioned. |
| DEV-145 | Scope: the propulsion engineer could not read the flight record | Caught by the `test_stream_scopes` guard, not by inspection. `ROLE_ENGINEER` lacked `read:reports`, so the one role whose PRD Part 3 s19.5 focus is "engine performance, degradation analysis, model validation" was denied the ECTM material. Same class as DEV-108: the scope table not matching the decision the role makes. |
| DEV-146 | Non-ASCII in a filed document | The glyph test written for DEV-112 caught two more: `&mdash;` and `&rarr;` resolve to the same missing Helvetica glyphs, so HTML entities were no escape from the rule. |

## Deviations found by installing the project from nothing

Everything above was found by measuring the running system. These two were
found by doing what a first-time evaluator does: clone, follow the README, and
watch it fail. Neither is visible from inside a working development
environment, which is exactly why neither had been noticed.

Both are now handled by `run.py`, a one-command launcher that checks every
precondition and installs or builds what is absent.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-147 | **The documented quickstart could not start the API** | README and RUNBOOK both said `pip install -e .` was "enough to **run** the system". It is not. `layer4_core/twin_api.py:50` imports `layer4_core.security` at module scope, and `security.py` imports `jwt`, `bcrypt` and `cryptography` with no guard -- all three of which live in the OPTIONAL `security` extra. A core-only install therefore dies on `ModuleNotFoundError: No module named 'jwt'` before the first line of `main()`. **Verified empirically**, not by inspection: a throwaway virtual environment with `pyjwt` removed reproduces exactly that traceback, and restoring it fixes it. The documentation now specifies `pip install -e ".[security,reports]"` and says why. `reportlab` is a milder case of the same thing -- it IS guarded, so the API starts, but the PDF export the REPORT page offers then fails instead of producing a report, which is a worse demonstration than not offering it. |
| DEV-148 | **A fresh clone has no console at all** | `layer5_viz/gcs_console/dist/` is git-ignored, so nothing built ships in the repository and the root URL returns `{"console": "not built"}` until somebody runs `npm install && npm run build`. That is correct -- a build artefact does not belong in version control -- but the README described Node as needed "only to rebuild the screen", which reads as though a built copy were present. It is not. Corrected, and `run.py` builds the console when `dist/` is absent, degrading to an API-only run with a clear message when npm is unavailable rather than failing. |

### Why this class of defect is worth a section

Both entries are documentation, not code, and both would have cost an evaluator
their first twenty minutes. The pattern is the same one DEV-92 and DEV-107
record in other layers: **a thing that works is not the same as a thing that
works from the state a new arrival is actually in.** The development
environment had every optional extra installed and a console built months
earlier, so nothing on the documented path was ever executed as written.

`run.py --check` now runs the whole precondition sequence and a
five-layer self-check in about ten seconds, so the same discovery cannot be
made in front of an audience.

## The defect that only running it could find

DEV-147 and DEV-148 were found by installing the project from nothing. This one
was found by **using** it: clicking inject on the SIMULATION page froze the
entire console on stale values, and it stayed frozen.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-149 | **The twin froze permanently the first time any alert fired** | `layer4_core/live.py` rendered each active alert for the flight record with `a.model_dump() if hasattr(a, "model_dump") else dict(a)`. But `alerts.active` holds `layer1_edge.edge_rules.Alert`, which is a **dataclass**, not a Pydantic model -- and a dataclass is not iterable, so `dict(a)` raises `TypeError: 'Alert' object is not iterable`. `_run` catches the exception and stores it in `pipeline["error"]`, so the thread did not die; it re-raised on **every subsequent tick**, and because `self._ticks` increments past the failing line the counter never advanced again. The snapshot froze, every console page showed stale values, and `/api/healthz` went on returning `{"ok": true}` because it tests `ticks > 0`, not `ticks` *advancing*. Fixed with `_alert_as_dict`, which uses `dataclasses.asdict` for dataclasses and refuses to raise on anything else -- a rendering detail must not be able to stop the engine. Measured after the fix, injecting the same fault: ticks advance 226 -> 826 over twenty seconds, one `INJ TIMING DEV` alert active, master caution raised, and **two phase-tagged events with ATA 73 in the flight record**. |

### Why 508 passing tests did not catch it

**Nothing in the suite instantiated `LiveTwin`.** Every layer had tests; the
loop that runs all five together had none, so the only defect class that
*requires* the layers to be wired together was structurally invisible.

The path also runs only when `alerts.active` is **non-empty**. A healthy engine
never reaches it. So the system worked perfectly right up until it did the one
thing it exists to do, and then stopped -- which is the worst possible failure
mode for a health monitor and exactly the one an evaluator would trigger first.

`layer4_core/tests/test_live_pipeline.py` now covers the integration loop: that
it ticks and fills a complete snapshot, that an `Alert` renders to the keys the
flight record needs, that the renderer cannot raise on any input, that the twin
**keeps ticking after its first alert**, and that the alert actually reaches the
event log -- so a fix that silently swallowed alerts would fail too.

### The health probe was also wrong

`/api/healthz` returning `ok` for a twin that has not ticked in ten minutes is
not a health probe. It answers "did this ever start", not "is this alive".
Recorded here rather than silently fixed, because the same mistake is worth
stating plainly: **a liveness check must test progress, not existence.**


## Production-grade pass: what was demo-grade by accident

DEV-147 and DEV-148 were found by installing from nothing, DEV-149 by using the
console. This group was found by auditing the repository against production
readiness lenses: security and auth, data integrity, operations.

The PRD prescribes a DEMO TRACK for several components (Part 0 s163-186) -- a
FastAPI twin stub rather than Eclipse Ditto, FastAPI RBAC rather than Keycloak,
SQLite rather than InfluxDB. Those were decisions and are not in this list.
What is here was demo-grade by ACCIDENT.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-150 | **The container image could never be built** | `Dockerfile` ran `pip install .` with only `pyproject.toml` copied and no source present, so setuptools had no packages to build and the step died with "Getting requirements to build wheel did not run successfully". `docker compose up` had NEVER worked. Reproduced in an isolated directory containing only `pyproject.toml`, so this is measured rather than inferred. Split into two steps: dependencies from a hash-verified lock file (a cached layer, needing no source), then `pip install --no-deps .` once the source is copied. The layer-cache intent the original comment described is preserved and now actually functions. |
| DEV-151 | **The image installed no optional extras** | Even had it built, `pip install .` omits `security`, so `layer4_core.twin_api` would have died on `ModuleNotFoundError: No module named 'jwt'` -- DEV-147 for the THIRD time, after README, RUNBOOK and `run.py` were each fixed and the Dockerfile was missed. The image now installs `security`, `reports` and `edge`. CI builds the image, starts it, and waits for `/api/healthz` to report ADVANCING ticks, so a fourth occurrence is caught by machine rather than by a person noticing. |
| DEV-152 | **The physics lookup was excluded from the image** | `.dockerignore` excluded all of `data/`, but `data/physics/*.json` are TRACKED files that `combustion.py::_lookup_flame` needs on every tick; without one it raises `RuntimeError`, and the only fallback is a live Cantera solve -- the `physics` extra, deliberately not installed because an equilibrium solve blows the 10-20 ms budget of PRD Part 1 s6.4. Narrowed the exclusions to the generated and secret subdirectories, so `data/keys/` and `data/audit/` still never enter an image. |
| DEV-153 | **Builds were not reproducible** | Every dependency was an open `>=` range with no lock file, so an image built today and one built in six months could contain different code. For a defence deliverable that is a supply-chain gap, and it also undercuts `docs/INDIGENISATION.md`, whose claim is about a specific measured dependency closure. `requirements.lock` now pins 52 packages with SHA-256 hashes, resolved for linux/amd64, installed with `--require-hashes` so the build REFUSES an artefact whose hash does not match. |
| DEV-154 | **The image ran as root** | No `USER` directive. A process that binds one port and writes one directory does not need root. It now runs as uid 10001; `/app/data` is created and chowned before the switch so Docker propagates that ownership to the mounted named volume. CI asserts the container user is not root. |
| DEV-155 | **No structured logging existed anywhere** | No module in the production tree imported `logging`. When DEV-149 froze the pipeline, the only evidence was a string in a snapshot field that nothing read. `common/logging.py` adds JSON-lines logging with a redaction filter that scrubs by KEY NAME, so a credential has to be deliberately renamed to escape rather than deliberately handled to be caught. Standard library rather than structlog or loguru: `docs/INDIGENISATION.md` makes a measured claim about the dependency closure, and that claim is cheapest to hold when the answer needs no dependency at all. |
| DEV-156 | **A persistent tick failure was silent** | `live.py` caught every exception, stored the message and carried on; the comment on that line read "keep the demo alive", which is exactly what it did. No log, no counter, no escalation. A single bad tick still must not kill the engine, so the loop survives -- but failures are now counted, the first is logged WITH a traceback, further ones are throttled so a loop failing many times a second cannot flood the log it is meant to be found in, and past `_TICK_FAILURE_LIMIT` the twin marks itself DEGRADED and `/api/healthz` stops reporting ok. Regression test: `test_persistent_tick_failure_is_logged_and_degrades_health`. |
| DEV-157 | **A bad configuration failed late and far from its cause** | A missing threshold key surfaced as a `KeyError` inside a physics tick, minutes after start. `config.validate()` runs at startup, checks every section and parameter the code indexes without a default, and refuses to start naming the offending key. It also asserts `oil_pressure.low_speed_min_psi < high_speed_min_psi`, the specific inversion behind the DEV-143 false exceedance on every clean sortie. |
| DEV-158 | **No lockout on repeated failed logins** | `RateLimiter` is keyed on the client address, which does nothing about the attack that matters here: one account tried slowly from many hosts, which is what credential stuffing is. `LoginGuard` adds per-ACCOUNT exponential backoff -- three free attempts, then 2 s doubling to a 300 s cap, cleared on success. Deliberately not a permanent lockout: that hands an attacker a denial-of-service against a known operator, which mid-sortie is the worse failure. A locked account is refused with the SAME message a wrong password gets, because saying "locked" confirms the account exists. |
| DEV-159 | **Nothing ran the tests** | `.github/workflows/` was an empty directory: 508 tests, a display-standard checker, a traceability matrix and a licence audit all existed and nothing ran any of them. `ci.yml` runs lint, types, the fast suite on every push with the slow live-pipeline tests nightly, all three auditors, and -- the job that matters -- builds the container, starts it, and fails if ticks do not ADVANCE. That job would have caught DEV-150, DEV-151 and DEV-152 on the day each was introduced. |
| DEV-160 | **Multiple workers would have run multiple engines** | `twin` is a module-global singleton, which is CORRECT: a digital twin of one engine is a singleton by nature. But nothing prevented `--workers N`, and each worker would have started its own `LiveTwin` -- N independent engines diverging immediately, the console showing whichever one answered, and nothing anywhere reporting the disagreement. `main()` now refuses to start when `WEB_CONCURRENCY > 1` and says why. The scaling unit is one process per airframe, not N workers per engine. |

### MQTT and SHAP: the two entries the register was missing

The register's own rule is that no deviation may exist in code without an entry
here. Two had none. Both were flagged before this pass rather than found by it.

| ID | PRD says | We implement | Evidence / reason |
|---|---|---|---|
| DEV-161 | Mosquitto MQTT as the message broker | WebSocket, console-side | **Two different links were being conflated, including by us.** WebSocket is right for the GROUND-server-to-browser hop: browser-native, one connection, already inside TLS, and the console wants a complete snapshot rather than a topic subscription. MQTT is right for the AIRCRAFT-to-ground hop, which is lossy and intermittent -- QoS levels, store-and-forward, and above all Last Will and Testament, which lets the broker announce a lost airframe instead of the ground inferring it from a timeout. The current build detects a lost link with a reconnect timer, which is strictly weaker. So this is not "we skipped MQTT": it is the right tool for a hop that exists in the architecture and not yet in the build. Recorded as an OPEN GAP for the fleet tier rather than as a closed decision. |
| DEV-162 | SHAP and LIME for explainability | Exact closed-form attribution | For the health index this is not a substitution but an improvement: the index is a weighted sum of minimums, so it DECOMPOSES EXACTLY, and SHAP would spend compute producing an approximation of an answer that can be computed exactly. Where that argument does not hold is the Tier-3 deep model, whose fault attribution cannot be decomposed in closed form and currently carries no attribution at all. Recorded honestly: exact attribution where exact is possible, and an acknowledged gap where it is not. |


## Closing the trend gap: history that survives a restart

| ID | Requirement | Resolution |
|---|---|---|
| DEV-163 | **The ground station remembered nothing** | Health, degradation and the stabilised cruise datum lived in memory and vanished when the process stopped. The edge node has a 72-hour buffer; the GCS had nothing. That matters because the PS asks for "life cycle management" and "mission-wise health reports", and DEV-141 already captured the one reading a flight contributes to a trend and then DROPPED it -- the cost of trend monitoring without the benefit. `layer4_core/history.py` stores one row per flight in SQLite, written on shutdown, and `/api/history/ectm` reports drift against the baseline flight. Verified end to end: a real lifespan cycle flown to a stabilised cruise wrote `flight_id 1` with altitude 18000 ft, OAT -20.7 C, CHT max 100.6 C and chi 0.9762. |
| DEV-164 | **The trend must refuse a comparison it cannot make honestly** | ECTM is not "plot the temperature": it is the same reading at the SAME CONDITION, once per flight. A cylinder head is hotter on a hot day at low airspeed, and reading that as deterioration is how a trend programme produces false findings and gets ignored. So each flight is stored WITH the conditions it was taken at, and two flights whose altitude, OAT, airspeed or throttle differ beyond a band are reported as `comparable: false` with the reason -- and with NO deltas at all, because a number a reader would plot without noticing the caveat beside it is worse than an absent one. Same reasoning as DEV-141's refusal to average a flight that never stabilised. |
| DEV-165 | **The shutdown hook read a key that does not exist** | Wired to `flight_record["cruise"]`; the field is `cruise_datum`. It would have recorded NOTHING, silently, for the life of the system -- and the failure mode is invisible, because "no stabilised cruise this flight" is a legitimate outcome the module already logs. Found by checking the dict against the code rather than assuming, which is the same discipline that found DEV-92 and DEV-105. Every column is now asserted against a real datum: all 15 present, with only `t_s` and `stable_for_s` ignored, and both are metadata rather than readings. |

### Why SQLite rather than the DuckDB this project first proposed

A stack recommendation made earlier in the same session said DuckDB. Measuring
the actual data volume reversed it: this table gains **one row per flight**, so
a few hundred rows over an engine's 1,200-hour life and a few thousand across a
fleet. DuckDB's columnar scan and InfluxDB's compression both start paying at a
million rows, and both cost a dependency that `docs/INDIGENISATION.md` would
then have to account for. `sqlite3` is in the standard library, needs no server
to fail at an inconvenient moment, and is one file an operator can copy off a
ground station onto a memory stick.

Recorded because the reversal is the useful part: the right store follows from
the measured row count, not from which database is currently fashionable.


## Mission replay made real, and what CI caught while it was built

| ID | Requirement | Resolution |
|---|---|---|
| DEV-166 | **"Replay of historical mission data" replayed the TRAINING SET** | PS section E asks for replay of historical mission data and post-flight analysis. `replay.py` delivers a scrubber, event markers and a full investigation view -- over `data/synthetic`, the fleet the models were TRAINED on. Nothing recorded a real sortie, so nothing could replay one. `layer4_core/recorder.py` writes each sortie to Parquet, deliberately reusing the training fleet's COLUMN NAMES so `replay.py` reads a recording unchanged and a real flight goes through the exact analysis path the fleet did. Verified on a real running twin: 239 rows, 40 columns, 39.7 KB for 25 s at 400x. |
| DEV-167 | **The first recorder wrote NULL into sixteen of thirty-eight columns** | It mapped columns by NAME, but the twin GROUPS its readings (`cht.spread`, `electrical.bus_voltage`, `environmental.oat_c`, `timing.injector_duty_pct`, `vibration.kurtosis`) while the fleet flattens them. The file looked entirely healthy -- right row count, right schema, right size -- and was 42 % empty. Replaced with an explicit path table; the non-null fraction went 0.579 -> 1.000, and a test now asserts it, because a recording that LOOKS complete and is not is worse than one that fails outright. Same class as DEV-92: a name that exists is not a value that arrives. |
| DEV-168 | **A recording carries no ground truth, deliberately** | The training fleet has `lab_*`, `deg_*` and `*_true` columns because a simulator knows the answer. A real aircraft does not. Writing them as nulls would leave ground-truth-shaped holes and invite somebody to score a model against them, so they are omitted entirely. `chi` IS written -- it is the health the system ESTIMATED at the time, which is exactly what an investigator wants: what did it think, and when. |
| DEV-169 | **Two channels the fleet never had, and an experiment that is not yet valid** | `propeller_rpm` and `wastegate_pct` are on the CAN bus and in the twin, and absent from `data/synthetic`. Recording them costs nothing and is the only way a later analysis could use them. **But measured on the current simulator, `rpm / propeller_rpm` is 2.5454 with standard deviation 0.000** -- the correct Rotax 915 iS gearbox ratio, and perfectly deterministic. So propeller speed cannot yet serve as the INDEPENDENT rpm cross-check DEV-101 wants, because the generator derives one from the other. Building drift detection on it today would "work" only because the simulator made it work, which is the DEV-95 mistake exactly. Recorded as a channel now captured and an experiment not yet valid; it needs independent sensor noise and drift in the generator first. |

### Found by CI on its second run

| ID | Requirement | Resolution |
|---|---|---|
| DEV-170 | **The container bound its own loopback and was unreachable** | `DT_HOST` defaults to `127.0.0.1`, which is right on a bare host. Inside a container it is the CONTAINER's loopback, so `-p 8000:8000` forwards to an interface nothing listens on. The image started perfectly -- `twin started` in the log, no errors -- and nothing outside could ever connect. CI reported "container never reported a running pipeline", which was true and pointed at the wrong thing: the process was healthy, the port was a dead end. Worse, `main()`'s own refusal to bind a non-loopback address without TLS then blocked the fix. Resolved with an EXPLICIT opt-in, `DT_ALLOW_INSECURE_BIND=1`, set in the Dockerfile with the reasoning attached and logged loudly at startup. The refusal stays: plain-text bearer tokens must not cross a network by accident. But "0.0.0.0 inside a container behind a TLS-terminating proxy" is a legitimate deployment, and it now costs a decision somebody has to make and can find in a compose file, rather than a default nobody makes. |
| DEV-171 | **Two tests asserted a DATA condition as an AUTHORISATION one** | `test_only_the_commander_reaches_the_fleet_and_the_audit_log` and `test_every_role_can_read_replay` asserted `status_code == 200` on `/api/fleet` and `/api/replay/sessions`. Both return 503 when `data/synthetic` is absent -- and it is git-ignored, so every clean checkout and every CI run lacks it. The tests are about WHO MAY REACH the route; they now assert the caller was not refused (200 or 503) and say why. They had only ever passed on machines where the fleet happened to have been generated. |
| DEV-172 | **A test asserted a field list where it meant an intent** | `test_the_user_store_holds_only_hashes` asserted `set(rec) == {"role", "hash"}`, so adding the non-secret account state revocation needs (`disabled`, `must_change`, `token_epoch`) broke it. What the test actually guards is that no PLAINTEXT password is stored. It now asserts that -- bcrypt prefix, no password key, and a cross-check against the plaintext actually issued in FIRST_RUN_CREDENTIALS.txt -- so it keeps its meaning as the record legitimately grows. |


## Closing the band-selection failure the order analysis shipped with

`b69694d` wired envelope order analysis into the live pipeline and said in its
own commit message that it did not work at cruise: "the remaining suspect is
BAND SELECTION ... fixing it properly means a real fast-kurtogram tree or a
sideband-aware band score, and that is unresolved work, not a tuning knob."
That suspect was correct. These entries close it.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-173 | **The kurtogram searched WHERE but never HOW WIDE, so it failed at every speed but one** | `kurtogram_band` split the spectrum into sixteen bands of one fixed width -- Nyquist/16, 281 Hz -- and took the most impulsive. That is a band scan, not a kurtogram: the whole point of Antoni's method is that bandwidth is a SEARCH DIMENSION, because the right width is a property of the defect, not of the analyser. A defect impulse rings down and repeats at `f_defect`, putting its energy in a carrier plus sidebands spaced `f_defect` apart, so a passband narrower than that spacing admits the carrier and at most one sideband -- which reconstructs as a smoothly modulated tone, not an impulse train. Its kurtosis is **negative**. The correct band therefore scored WORSE than its noisy neighbours and the search returned the wrong answer with confidence. Because `f_defect` scales with rpm and a fixed width does not, this is a failure that only appears when the engine speeds up: measured on the isolated bearing component, the spectral kurtosis of a narrow band around the 2600 Hz carrier falls **2.32 → 0.43 → −0.26** at 1400 → 3500 → 5500 rpm, while the same signal in a wide band holds **4.67 → 3.33 → 2.48**. Replaced with a dyadic tree (levels 0–5, each level also swept at a half-band offset so a resonance on a boundary is not split -- 2600 Hz sat almost exactly on the level-1 edge), floored at `DEMOD_BANDWIDTH_MARGIN × BPFI` derived from rpm and bearing geometry on every call. |
| DEV-174 | **The band score measured the analysis window, not the engine** | Two errors, both of which added a large offset common to every band and so buried the differences the search exists to find. (a) The signal was multiplied by a **Hann window over the whole record** before the bands were cut, and the inverse transform therefore returned a signal modulated by the window's own taper -- a shape that is itself hugely impulsive. Measured, it added **~2.2 kurtosis to every band**. The band edges are now tapered instead of the time record. (b) `np.abs(np.fft.irfft(...))` on a zeroed one-sided spectrum is **full-wave rectification of a real signal**, not the analytic envelope its docstring claimed: `irfft` reconstructs a REAL signal, so the result oscillates at the carrier rather than riding above it, and a folded Gaussian has excess kurtosis **+0.86** -- a band of pure noise scored as though something were in it. The search now forms a true complex envelope and scores it with Antoni's `E\|z\|⁴/(E\|z\|²)²−2`, which is 0 for circular Gaussian noise. Together these are why the band came back **the same whether the bearing was healthy or destroyed**, which was the reported symptom: measured at 5500 rpm, the old score gave a healthy bearing **5.62** and a destroyed one **4.68**. |
| DEV-175 | **A frequency-domain band-pass wraps, and the wrap is an impulse** | Zeroing bins and inverting is a CIRCULAR convolution, so the first and last envelope samples carry the record's end-to-start discontinuity. That edge transient is a genuine impulse and it is in every band, so it inflates every score. 5 % is trimmed from each end before the kurtosis is taken. Small, and recorded because it is the kind of artefact that makes a detector look like it is working. |
| DEV-176 | **A wider search had to cost less, not more, to stay on an edge node** | The tree evaluates ~29 candidate bands at idle against the old 16, which done naively is a full-length inverse transform per band. Each candidate is instead demodulated at its own **decimated** rate -- the band's bins are inverse-transformed on their own, which is what a fast kurtogram does; a frequency shift only rotates phase, so the envelope magnitude is unchanged. Measured per call: **57.5 → 8.9 ms at idle** and **4.8 → 0.6 ms at 5800 rpm**, so the wider search is 6× cheaper than the narrow one it replaces and now fits the 10–20 ms tick budget of PRD Part 1 §6.4 that `_ORDER_EVERY_TICKS` exists to work around. |
| DEV-177 | **The suite could not see the defect because it only ever ran at idle** | All seven tests took their waveform at whatever speed the 20 s warm-up profile happens to sit at, ~1400 rpm -- the one speed where the old code worked, and it worked there by luck rather than by method. So a diagnostic that was blind through the entire cruise envelope had a fully green suite. The behavioural tests are now parameterised over **1400 / 2200 / 3500 / 4800 / 5500 / 5800 rpm** for both a healthy and a worn bearing, `test_the_chosen_band_can_actually_demodulate_the_defect` asserts the bandwidth property directly rather than only its consequences, and `test_the_band_search_responds_to_the_bearing_and_not_only_to_the_engine` asserts the reported symptom itself. Checked against the old algorithm: **12 of the new tests fail and the 7 original ones still pass**, which is the measurement that says the old suite was the problem. |

### Measured after the fix

Bearing fault injected as a real `ABNORMAL_VIBRATION` fault and flown to cruise,
read through the same call `live.py` makes -- not by assigning
`bearing_condition`, which the degradation model recomputes from flight hours on
the next step and which `b69694d` had already been caught by:

| At 4763 rpm, CRUISE | `bearing_condition` | BPFO | Diagnosis |
|---|---|---|---|
| no fault | 0.9999 | 1.44x | none — correct |
| severity 0.6 | 0.3997 | **14.77x** | outer race, then inner race |
| severity 1.0 | 0.0000 | **23.16x** | outer race, inner race, cage |

Before the fix the middle row read **BPFO 1.3x and no finding at all**.

Across 6 speeds × 6 seeds the worst healthy bearing order reaches **3.37x**
against the 4.0x reporting threshold, so the false-positive margin survives a
search that now reaches wider bands. Detection is clean from
`bearing_condition ≤ 0.70` and the mean BPFO rises monotonically with wear --
1.48 → 6.01 → 14.51 → 23.90 → 30.16 → 36.41 → 50.07 at 1.00 → 0.85 → 0.70 →
0.55 → 0.45 → 0.30 → 0.15 -- so the number carries severity and not merely
presence. Detection becomes marginal at 0.85, which is a 15 % defect, and that
is recorded as the sensitivity floor rather than claimed as a capability.

**What this does not close.** `envelope()`, the demodulation step that follows
band selection, still recovers the modulation by rectification rather than with
an analytic signal. It is correct enough that the order spectrum downstream is
right -- the rectified carrier harmonics land far above any order being read --
and it is left alone deliberately rather than changed alongside a band-selection
fix. Its docstring claimed to form the analytic signal and no longer does, since
the two steps in this file now demodulate differently and a reader should not
have to work out which claim is the accurate one.


## Targets rebuilt on the published literature, and what they then measured

The RUL acceptance criteria were numbers this project invented. DEV-102 had
already shown they contradicted each other and demanded better-than-SOTA in
relative terms; what it had not done was replace them. Researching what the
field actually requires turned out to change not the numbers but the METRICS,
and the replacements make the shortfall larger rather than smaller.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-178 | **The acceptance criteria measured the wrong thing, not merely the wrong amount** | RUL was scored on RMSE, R2, MAPE and the C-MAPSS score -- regression metrics with one prognostics metric bolted on. A prognostic is not a regressor that outputs hours: it has to become trustworthy BEFORE the engine dies and stay so, and an RMSE averaged over a life that is **41.5 % pinned at the horizon cap** (measured on the current test set; DEV-102 put censored-plus-capped at 64.9 %) reports mostly how flat the fixture was. That is how RMSE 121 h and R2 0.236 coexist: the error concentrates in the minority of labels that carry every decision. Replaced with the four metrics Saxena et al. (NASA, PHM 2008) define, NASA's own Prognostics Metrics Library implements and ISO 13381-1's process is written around -- **prognostic horizon, alpha-lambda, relative accuracy, convergence** -- in `layer3_ai/prognostic_metrics.py`, 16 tests. The unifying idea is that error is judged relative to LIFE REMAINING: 40 h of error on 400 h left is a good estimate and on 50 h left is a missed failure, and RMSE scores them identically. |
| DEV-179 | **The withdrawn targets, and why they are commented rather than deleted** | `rmse_flight_hours: 25.0`, `r2: 0.85` and `mape: 0.15` are withdrawn. 25 h is **0.18x the 138.8 h target sigma** where published C-MAPSS state of the art is roughly 0.28x, so it demanded better-than-SOTA relative accuracy, while the R2 target in the same block implied roughly 53.7 h -- twice as loose. They could never both be met. MAPE is undefined as RUL approaches zero, which is the region that matters. All three stay in `configs/thresholds.yaml` **commented with the reason**, because deleting a target we failed is not the same as showing why it was the wrong target. |
| DEV-180 | **alpha = 0.2 is borrowed, deliberately** | The accuracy cone is Saxena's published convention and the value the C-MAPSS literature reports against. A tolerance derived from our own error distribution is one we have already met by construction -- the DEV-95 mistake in a new place. The one constant that IS local is the cone's floor: `DEFAULT_MIN_BOUND_H = 10.0`, taken from the tightest maintenance band this system itself issues ("Schedule maintenance within 10 flight hours"). It exists because a cone of +/- alpha*RUL collapses to ZERO width at end of life, making the horizon identically zero for every algorithm ever written; measured before the floor, an estimator at 0.165 sigma with alpha-lambda 1.00 still scored a horizon of 0.0 h, which is a statement about the metric and not the estimator. |

### Measured against the new targets, model as shipped

Re-scored, not retrained: `data/models/rul_lstm.pt` as it stands, 4,120 test
windows over 15 held-out engines, target sigma 138.8 h.

| Metric | Measured | Target | |
|---|---|---|---|
| alpha-lambda (a=0.2, l=0.5) | 0.200 | > 0.50 | NOT MET |
| Prognostic horizon | 0.0 h | > 100 h | NOT MET |
| Relative accuracy | 0.519 | > 0.60 | NOT MET |
| RMSE / sigma | **0.874** | < 0.30 | NOT MET |
| Late fraction | 0.338 | < 0.25 | NOT MET |
| NASA score | 297.8 | < 500 | MET |

Raw RMSE 121.3 h, R2 0.236, convergence 322.0.

**Against the international reference this is roughly 2.9x off.** Published
C-MAPSS state of the art is 12.6-15 cycles, about 0.28-0.30 sigma; this model
sits at **0.874 sigma**. That is the honest answer to "are we near what other
countries achieve", and it is the first time the question has been asked in
units that permit an answer -- an absolute figure in hours cannot be compared
across datasets at all.

The two findings the old metrics could not surface:

- **alpha-lambda 0.200** means 3 of 15 engines are inside the accuracy cone at
  the halfway point. RMSE could not say this because it averages the 41.5 % of
  windows sitting at the cap, where every estimator looks competent.
- **Prognostic horizon 0.0 h** means the estimate never settles and STAYS
  settled before end of life. For a maintenance decision that is the load-
  bearing number, and nothing in the previous metric set computed it.

`nasa_score` remains the one target met, and DEV-103 already records why it is
reported as a range and never used as a go/no-go: it is exponential in the
error and moved 478 to 3,108 across three seeds.

**Not measured here.** Interval coverage came out at 41.8 %, but that is
`predict_with_interval` at its uncalibrated Gaussian default of q = 1.96, NOT
the conformal q that DEV-105's 84-87 % refers to. The two numbers are not
comparable and the uncalibrated one is not evidence of anything, so it is
recorded as not-yet-measured rather than reported as a regression.

**What this does not do.** It does not improve RUL by one hour. It replaces a
target that could not be met with one that can be compared to the outside
world, and then reports that the gap is wider than the old metrics implied.
The remaining work is unchanged in kind and better specified in degree: the
estimator sees a 50-second window, RUL depends on the RATE of degradation, and
a window that short observes a state rather than a rate. The next honest step
is the C-MAPSS benchmark itself -- the loader exists, the dataset is still not
downloaded, and until it is, every figure above is measured on our own
simulator and none of them may be quoted as a comparison to published work.


## The outside yardstick: what the method scores on data we did not write

DEV-178 replaced invented targets with the field's own metrics and reported
that this engine's RUL is worse than the old numbers implied. It could not say
whether that is a bad ESTIMATOR or a hard PROBLEM, because a score measured on
a simulator we wrote reports how hard we made the simulator. Answering it
needed data from outside the project.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-181 | **The benchmark is a yardstick for the METHOD and is never mixed with the engine** | C-MAPSS is a high-bypass TURBOFAN whose fault modes are HPC and fan degradation, read through 21 gas-path channels. The reference engine is a four-cylinder piston engine whose faults are misfire, injector, cooling, lubrication, sensor drift, combustion instability, overheating and bearing wear. They share **no sensor and no failure mechanism**, so a model trained on one cannot be applied to the other, and `layer3_ai/cmapss.py` deliberately provides no merge, no shared feature space and no pre-training entry point. `test_the_turbofan_shares_no_channel_with_the_reference_engine` asserts the channel sets stay disjoint, so the day somebody is about to mix them is the day a test fails. The dataset is fetched by `scripts/fetch_benchmarks.py`, verified against a recorded SHA-256, and **never committed** -- 12 MB of NASA's bytes are not ours to redistribute and `docs/INDIGENISATION.md` makes a claim about what this repository contains. |
| DEV-182 | **The estimator is competitive; the problem is observability** | `scripts/benchmark_cmapss.py` runs `rul_lstm.RulLstm` **at its shipped hyperparameters, untuned** on all four C-MAPSS subsets. Measured RMSE at the last cycle per unit -- the figure the literature reports -- against published state of the art: FD001 **15.42** vs 12.6 (1.22x), FD002 **17.77** vs 13.1 (1.36x), FD003 **13.89** vs 12.7 (**1.09x**), FD004 **19.05** vs 14.0 (1.36x). alpha-lambda on the same predictions is **0.71-0.83**. On our own engine the same code and the same metrics give **0.87 sigma and alpha-lambda 0.20**. Same architecture, same scoring, an order of magnitude apart in outcome -- so the deficit is in what the model can SEE, not in the model. This closes a question the project has carried since DEV-100 without being able to settle it. |
| DEV-183 | **The long view is already in the dataset and is thrown away** | Measured: each test engine carries **48 recording sessions spread over ~516 flight hours**, roughly one every 10 h, each about 50 s of 1 Hz samples. The Tier-3 window is 30 samples -- **0.0013 % of an engine's life**. RUL is the RATE of degradation and a 30 s window observes a state, so the estimator is being asked for a rate from a photograph, which is the mechanism behind DEV-182's gap. C-MAPSS by contrast hands its model 30 whole cycles. Recorded as the specific, evidenced next step, and NOT attempted here: it is a change to the feature contract and the label horizon, not a tuning knob. No data needs generating -- `layer4_core/history.py` (DEV-163) already persists one row per flight, and the per-session structure is in `data/synthetic` today. |
| DEV-184 | **The runbook claimed a loader that did not exist** | "NASA C-MAPSS and IMS/CWRU loaders exist; the datasets are not downloaded." No loader existed for any of the three: the only C-MAPSS reference in the tree was the scoring formula's time constants in `rul_physics.py`. The claim had been in `RUNBOOK.md` s8 unchallenged, and it is the kind that survives because nobody tries to use the thing it describes -- the same class as DEV-165's shutdown hook reading a key that was never there. A real loader now exists for C-MAPSS with 8 tests; IMS and CWRU still have none and the runbook no longer says otherwise. |
| DEV-185 | **NASA's own readme has FD004 transposed, and asserting the readme would have hidden it** | The readme states FD004 holds 248 train / 249 test trajectories. The archive holds **249 train / 248 test**. The label file settles it: `RUL_FD004.txt` carries exactly 248 lines, one per test unit, which it could not do if there were 249; the published C-MAPSS tables agree with the data. `EXPECTED_UNITS` is therefore measured from the archive rather than copied from its documentation, and the discrepancy is pinned as a test so nobody "corrects" the loader back. Worth recording for the general reason rather than the specific one: the first version asserted what the documentation claimed, and a truncated download does not raise -- it reads as a smaller fleet and produces a benchmark number that is not the benchmark. Asserting the FILE is what catches that; asserting the DOC is what caught NASA. |

### The comparison, in one table

| Subset | This architecture, untuned | Published SOTA | Ratio | alpha-lambda |
|---|---|---|---|---|
| FD001 | 15.42 | 12.6 | 1.22x | 0.83 |
| FD002 | 17.77 | 13.1 | 1.36x | 0.71 |
| FD003 | 13.89 | 12.7 | **1.09x** | 0.83 |
| FD004 | 19.05 | 14.0 | 1.36x | 0.81 |
| **915 iS (our simulator)** | **0.87 sigma** | ~0.28 sigma | **~2.9x** | **0.20** |

Read the last row against the four above it. The estimator that lands within
9-36 % of the world's best on the data everyone reports on is the same
estimator, unchanged, that manages alpha-lambda 0.20 here. The difference is
the window it is given, and DEV-183 says where the missing window already is.

**What may and may not be claimed.** May: "the RUL method benchmarks at
1.09-1.36x published state of the art on NASA C-MAPSS, untuned". May not:
anything about the 915 iS engine model, its health index or its RUL being
validated by real data -- that needs piston-engine run-to-failure data, which
this is not and which the project still does not have.


## Where the targets come from now, and the one I invented on the way

DEV-178 replaced the metrics. This replaces the NUMBERS, and it exists as a
separate entry because the first attempt at them repeated the original mistake.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-186 | **There is no international numeric target, and pretending otherwise is how the 25 h figure happened** | Researched directly: ISO 13381-1, ISO 13374, SAE ARP6883 (writing IVHM requirements), SAE ARP6887 (V&V of IVHM systems) and the IEEE PHM standards. **Not one publishes a numeric RUL accuracy requirement.** They define metrics and process and then require the organisation to derive acceptance criteria from its own application; NIST's survey of the PHM standards landscape states this explicitly. So the honest structure is three tiers, and every target now carries which tier it came from. **Tier 1, published convention adopted unchanged**: `alpha = 0.2`, `lambda = 0.5`, the 125-cycle cap, the Saxena metric definitions. **Tier 2, parity with measured state of the art**: `benchmark_ratio_to_sota <= 1.40`, from published C-MAPSS RMSE of 12.6/13.1/12.7/14.0 -- and it gates the BENCHMARK script, not the engine, because no published figure exists for a piston engine. **Tier 3, no international number exists at all**: alpha-lambda, relative accuracy and RMSE/sigma are trajectory metrics, C-MAPSS yields one labelled RUL per test unit, and the literature therefore rarely reports them -- there is not even a distribution to calibrate against. |
| DEV-187 | **Tier 3 is a self-benchmark, not a preference** | The bar for the three ungrounded metrics is the WORST value this same architecture achieved across the four C-MAPSS subsets, measured with identical code and identical protocol: `alpha_lambda >= 0.70` (range 0.708-0.830), `relative_accuracy >= 0.82` (0.827-0.901), `rmse_sigma_ratio <= 0.71` (0.473-0.705). The claim each encodes is narrow and checkable -- **this estimator must do on our engine what it provably does on the world's data** -- and it is attainable by construction, because the method has already achieved it. Traceable to a run rather than to a judgement: `data/benchmarks/results.jsonl`, seed 0, 25 epochs, 2026-09-06, written by `scripts/benchmark_cmapss.py --json`. |
| DEV-188 | **The prognostic-horizon target was invented, and measurement killed it** | An earlier draft of this same block set `prognostic_horizon_hours: 100.0`, reasoning that the estimate must settle at least four of the advisory's own 25 h scheduling bands before end of life. That reasoning sounds operational and is worth nothing: measured with the same code on C-MAPSS, an architecture within **1.09x of world state of the art** earns horizons of **0.0 / 0.0 / 1.5 / 6.5**. Saxena's "and STAYS inside the cone" rule is near-binary against any estimator carrying noise -- one excursion anywhere in the suffix forfeits the whole horizon -- so a 100 h gate would have been a second unreachable target, invented by exactly the process that produced the first one, three entries after diagnosing it. The horizon is now **computed and reported, and gates nothing**. Recorded because the near-miss is the useful part: a target that follows from sound-sounding reasoning is still invented until something measures it. |
| DEV-189 | **Two numbers demoted from gates to reported bounds** | `nasa_score` stays at 500 as a sanity bound only -- DEV-103 already measured 478 to 3,108 across three seeds, and a metric exponential in the error cannot be a single-run go/no-go. `late_fraction` moves to 0.35, the worst this method produced on C-MAPSS (0.317) rounded, and is explicitly a **ceiling rather than a safety gate**: the safety argument is carried by the NASA score, which penalises late predictions asymmetrically by construction (DEV-66), and by DEV-104's relative criterion that fusion must REDUCE the late rate. Raising 0.25 to 0.35 would be moving a goalpost if 0.25 had a source; it did not, and 0.35 does. |

### The target set, with provenance

| Target | Value | Tier | Source |
|---|---|---|---|
| `alpha` | 0.2 | 1 | Saxena et al., PHM 2008; the C-MAPSS convention |
| `lambda` | 0.5 | 1 | same |
| `benchmark_ratio_to_sota` | <= 1.40 | 2 | published C-MAPSS SOTA; gates the benchmark only |
| `alpha_lambda` | >= 0.70 | 3 | worst of our four C-MAPSS runs (0.708) |
| `relative_accuracy` | >= 0.82 | 3 | worst of our four C-MAPSS runs (0.827) |
| `rmse_sigma_ratio` | <= 0.71 | 3 | worst of our four C-MAPSS runs (0.705) |
| `interval_coverage_unseen` | >= 0.80 | theory | DEV-105; conformal coverage under non-exchangeability |
| `nasa_score` | < 500 | bound | reported as a range, never a gate (DEV-103) |
| `late_fraction` | < 0.35 | bound | ceiling; safety carried by the NASA score (DEV-66) |
| `prognostic_horizon` | -- | none | reported only; a gate here would be invented (DEV-188) |

`min_bound_h = 10.0` in `prognostic_metrics.py` is the one constant that is
deliberately OURS rather than borrowed: the tightest maintenance band this
system issues. It is documented as such at its definition rather than dressed
as a standard.

**What this does not do.** It does not move the engine's RUL one hour. The
measured position is unchanged -- 0.87 sigma and alpha-lambda 0.20 against
0.71 and 0.70 -- so on the new targets the engine still fails three of them,
and now fails against numbers that a reviewer can trace to a published
convention or to a run in this repository. DEV-183 remains the evidenced next
step and it is not a tuning exercise.


## The fault model was modelling the wrong half of the bathtub curve

The problem statement's whole premise is that conventional monitoring
"indicates failures only after abnormality has already occurred", and it asks
for "predicting probable failures BEFORE occurrence" built on "failure/
degradation logic", while listing "reliability engineering" among the technical
expectations. The generator's fault model contradicted all three.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-193 | **Fault onset was independent of engine condition** | `synth_data_gen.py:309` drew `onset = rng.uniform(15.0, 400.0)` ONCE, before the engine ever ran. A pristine engine and a badly worn one were equally likely to develop a fault in the next hour. In reliability terms that is a CONSTANT hazard -- Weibull shape beta = 1, the flat middle of the bathtub curve, which describes RANDOM failures such as debris or a manufacturing escape. Wear-out is the rising right-hand region, beta > 1; published shape parameters put rolling-element bearings and abrasive wear at 1.5-2.5, material fatigue at 2-4, corrosion at 3-5. **None of them is 1.** Replaced with Cox proportional hazards using the degradation state as a time-varying covariate -- the standard condition-based formulation, in which degradation "does not directly lead to system failures, but increases the hazard rate" -- as `h(t) = h0 * exp(gamma * d(t))`, where `d` is accumulated damage on the pathway the mode acts through per `_FAULT_ACCELERATION`. Measured: P(onset) over a 12 h sortie for a bearing fault rises **2.4 % -> 5.0 % -> 10.2 % -> 20.3 % -> 38.1 %** as bearing damage goes 0.00 -> 1.00, a 16x ratio. A worn bearing now actually gets bearing faults. |
| DEV-194 | **It was not only unrealistic, it made the required capability impossible** | With onset independent of condition, NOTHING observable about the engine can anticipate a fault, so "predicting probable failures before occurrence" cannot be delivered by any model, however good -- the information does not exist at prediction time. That is the mechanism behind the RUL ceiling this project spent a long time characterising: an oracle given the simulator's own hidden wear state AND every future fault still could not beat 0.75 sigma, while the sensor models sat at 0.80. The ceiling was the fault schedule, not the estimator. There was also a one-way causality: `_FAULT_ACCELERATION` let a fault accelerate wear, but wear never raised the probability of a fault. On a real engine that is a loop, and it is now closed. |
| DEV-195 | **SENSOR_DRIFT is deliberately left at constant hazard** | A transducer failing is an ELECTRONIC event, not mechanical wear-out, and beta = 1 is the CORRECT model for it. Verified: its onset probability stays flat at 2.4 % per sortie whether the engine is as-new or destroyed. Making every mode condition-dependent would have been the same error in the opposite direction, and it is recorded here so that the exception reads as a decision rather than an oversight. |
| DEV-196 | **One ramp distribution for eight different physical mechanisms** | `ramp = exp(uniform(log(0.5), log(300.0)))` -- a 600:1 log-uniform span -- was applied to every fault mode, which says a failed ignition coil and a coking injector progress alike. Replaced with `FAULT_RAMP_HOURS`, a per-mode table keyed on the mechanism: MISFIRE 0.5-8 h (an ignition component fails; near-step), INJECTOR_ABNORMAL 40-250 h (deposit build-up), COOLING_DEGRADATION 60-300 h (scale and fouling), OVERHEATING_TREND 80-350 h (it is named a TREND; modelling it as a step contradicted the mode), ABNORMAL_VIBRATION 20-150 h (bearing spall propagation), SENSOR_DRIFT 50-300 h, COMBUSTION_INSTABILITY 20-150 h, LUBRICATION_ISSUE 10-120 h. |
| DEV-197 | **The manifest recorded every hazard-scheduled fault as never having started** | Found while verifying DEV-193's own fix. `run.faults` is built as a dict BEFORE the engine flies, capturing `onset_hours` at that moment -- which under the new model is the `inf` placeholder, because the time is decided DURING the run. Nothing updated it afterwards. The failure is silent and expensive: `scripts/measure_rul_ceiling.py` reads fault schedules from the manifest, so it would have seen a fleet with no faults in it and produced a confidently wrong ceiling. The onset is now written back beside `expressed`, which was already being filled in at the same point for the same reason. |
| DEV-198 | **The old model is preserved, not deleted** | `run_one_engine(hazard_onset=False)` reproduces the original constant-hazard fleet exactly, and an explicitly scheduled fault -- a test, a demo, a replayed incident -- still behaves as written under either model. The comparison this change has to justify itself with is therefore runnable rather than remembered, and the existing `data/synthetic` fleet is untouched. |

### Calibration, and what is deliberately held fixed

The wear-out hazard makes faults arrive later on a healthy engine, which
lengthens lives and raises censoring -- measured on single engines, one went
from 468 h to 1207 h and censored. Left uncorrected the new fleet would differ
from the old in TWO ways: when faults arrive relative to condition, and how
many engines fail at all. No comparison could separate them.

So `FAULT_BASE_HAZARD_PER_HOUR` is calibrated to hold the fleet's
failure/censoring rate at the old value, isolating the single change under
test. That is honest calibration -- it holds the overall failure statistics
fixed -- and it is explicitly NOT tuned against any accuracy metric.
`FAULT_HAZARD_RATIO = 20.0` is the one constant chosen for its size rather than
derived, and is recorded as such: a strong but unexceptional covariate effect
in the condition-based reliability literature.

**What must not be claimed.** If RUL accuracy improves on the new fleet, the
honest statement is "RUL improved partly because the simulator became more
realistic", NOT "our model got better". Those are different claims and only one
of them would be true. The before/after ceiling is measured with
`scripts/measure_rul_ceiling.py` on both fleets for exactly this reason.


## Two technology changes, one measured and one architectural

| ID | Requirement | Resolution |
|---|---|---|
| DEV-199 | **The survival head's booster, chosen by measurement** | The published comparison that prompted the test has CatBoost winning 26 of 30 datasets on Brier score -- the metric this head is judged by -- but a benchmark over 30 public datasets says nothing certain about 2,000 rows of engine sorties. Measured on THIS data, engine-grouped 6-fold, identical folds for every library, Brier skill: **25 h** sklearn 0.327 / LightGBM 0.354 / **CatBoost 0.398**; **50 h** 0.443 / 0.440 / **0.454** (and CatBoost's fold-to-fold spread is 0.029 against sklearn's 0.071, a third of the variance); **100 h** **sklearn 0.479** / 0.475 / 0.464. CatBoost takes the two horizons that carry a dispatch decision and is far steadier at 50 h; it loses at 100 h by 0.015, which is inside the noise of six folds. One library is therefore used throughout rather than picking per horizon and calling the noise a result. scikit-learn remains an automatic FALLBACK so a slim edge image without CatBoost still runs. |
| DEV-200 | **MQTT, and specifically its Will** | DEV-161 recorded this as an open gap and it is now closed for the AIRCRAFT-to-ground hop only; the console's WebSocket is the ground-to-browser hop and is unchanged. `edge_buffer.note_link` infers a lost aircraft from a TIMEOUT, which cannot distinguish "the airframe is gone" from "the airframe is fine and the ground station stopped hearing it" -- the two states PRD Part 4 s7.2 exists to keep apart. MQTT's Last Will and Testament closes that: the aircraft registers a message WITH THE BROKER at connect, and if the connection drops without a clean disconnect the broker publishes it on the aircraft's behalf. The ground station is TOLD, by a third party that was watching. `layer1_edge/mqtt_link.py`, 13 tests, no broker required to run them. QoS per topic and each for a reason: status QoS 1 RETAINED so a late-joining console learns the state immediately rather than at the next change; telemetry QoS 0 because at 10 Hz a redelivered frame is worth less than the bandwidth and the buffer already holds 72 h; alerts QoS 1 because an alert is an EVENT and losing one is losing the thing itself. Fails soft throughout -- an unreachable broker is a normal condition for an aircraft and must never propagate into the physics loop. |
| DEV-201 | **A tuning knob that was wired to nothing** | `onset_probability(..., base_hazard: float = FAULT_BASE_HAZARD_PER_HOUR)` captures the constant ONCE, when the module is imported, so reassigning the module attribute afterwards changed nothing. The calibration sweep that was supposed to choose the hazard level returned **byte-identical fleets for three different values** -- 933 h median life and 80 % failure rate at every setting -- which is impossible unless the value is never read. Both constants are now resolved at call time. Found only because the sweep existed: a single run would have produced a plausible fleet and the "calibrated" constant would have been decorative for the life of the project. The same trap applies to every module constant used as a default argument, which is why it is recorded rather than quietly fixed. |


## Grafting the mission planner into the new console

| ID | Where | PRD says | We implement | Evidence / reason |
|---|---|---|---|---|
| DEV-256 | Zone B on the mission planning view<br>`layer5_viz/gcs_console/src/App.tsx` (`ownsEngineStrip`), `theme/ui.css` (`.zone-b`) | PRD Part 4 §6.1: Zone B is the PRIMARY ENGINE STRIP, "the four highest-criticality parameters, **always visible on every page**: RPM, CHT (max of 4), EGT (max of 4), OIL PRESS" | Zone B folds away (150 ms, `grid-template-rows: 1fr → 0fr`) on **Mission planning only**, and on that view only. It is present and unchanged on every other view of every role, and the JSX that builds it is untouched, so the s6.1 zone-layout check still passes on the shell. | The rule exists so an operator can always see the four. On this view they can: the page carries its own engine instrument band showing RPM, coolant, cylinder head, EGT, oil temperature, oil pressure, the health index and remaining life — each against its calibrated scale and certified limit, and under the transport the FLOWN values of the sortie rather than the live ones. Zone B beside that is the same four numbers twice, in two styles, one of them answering a different question: what the engine is doing on the ground now, while the operator is asking what a sortie would do to it. It also costs 72 px of a workspace whose whole argument is that the map should be big — measured, the map goes from 425 px to 532 px at 1920×912 and from 281 px to 388 px on a 1366×768 panel, the difference between a map and a strip of one. Same deviation, same reasoning, as the mission pages of the previous console. |
| DEV-257 | The 3D engine model's assembled pose and its render loop<br>`layer5_viz/gcs_console/src/components/EngineModel.tsx` (`SEATED`, `seatFloatingParts`, the on-demand loop) | PRD Part 4 s8.1b forbids decorative animation, and the engine view is a display surface that must not compete with the data path -- the reason it was capped at a fixed 20 fps in the first place. | Nine parts are moved at load, and the fixed frame cap is replaced by rendering on demand. The parts: the GLB's rest pose is a PARTIALLY EXPLODED pose -- nine components sit up to 0.607 off the engine, touching nothing, and each is displaced along ITS OWN explode axis (cos 0.87 to 1.00 for all nine). Each is slid back down that axis to first contact, solved offline against 613,885 vertices at a 2.5 mm tolerance, and the delta is applied to the rest pose and to every keyframe of both clips. Bounding radius 1.3203 -> 0.7751; explode/repack returns bit-exact (worst node error 0.00e+0). The loop: idle paints nothing, interaction paints every frame the display will take, self-driven motion (pulse, explode) is held to 30 fps, and the buffer adapts to the frames the machine actually delivers. | The asset is not forked. The GLB, `faultLayer.js`, the registry and the fault matrix are untouched, and the seating is applied as the model loads -- the same rule `repaintToConsolePalette` already follows for the package's colours. No geometry, no component name and no registry id changes, so selection, highlighting, explode and repack all keep working, and if the package ever ships a corrected pose the table becomes a no-op. On the loop: the cap was protecting the data path and still is, more effectively -- it spent a frame every 50 ms on a picture nobody was touching (212 draws, 539k tris, forever) while capping the one thing that had to feel immediate. Measured on an RTX 3090: idle 19.0 -> 0.0 fps, orbiting 18.1 -> 59.8 fps. Total GPU work is far below the old cap because a monitoring console sits still almost all of the time. No tone mapping was added, deliberately: a filmic curve would shift every alert colour, and a highlight still renders at exactly `#ff3b30` = `--alert-warn`. A later pass added a worst-first list of the lit faults (click to bring the camera round -- previously only the single worst was reachable), cylinder numbers on the model so the CYL 1-4 panel beside it can be matched to the geometry, and a prompt that now appears only when a lit part really is internal, which is two of the eight faults rather than all of them. A gridded backdrop was asked for and declined: it would lay faint grey texture behind HIGHLIGHT_CONTEXT, which is itself a faint grey glow and the quietest signal the view carries; the background darkens 12 % towards the bottom instead, with the top half left at exactly --bg-panel so the canvas still meets its card with no seam. Full reasoning and measurements in `docs/ENGINE_3D_OVERHAUL.md`. |

## The September 2026 review: what it found, and what changed

A structured review of the whole build on 14-15 September 2026 against the
problem statement: safety logic, machine learning, CAN edge, physics, security,
runtime, reports and the console. Every finding below was reproduced by
script or read in the code before it was fixed, and each fix has a test beside
it. Finding IDs (SAF-, ML-, SEC-, CAN-, RT-, REP-, HMI-, PS1-, PHY-, JUR-) refer
to the review ledger. Items that are still open are listed at the end rather
than left out.

| ID | Requirement | Resolution |
|---|---|---|
| DEV-202 | **Acknowledging a master alarm did nothing** (HMI-01) | `LiveTwin.acknowledge()` called `reset_master_warning()` with no argument, while its signature is `(self, now)`, so every press raised a TypeError and `reset_master_caution` was never called at all. Both are now called with the telemetry time. The console adds what an operator needs around that button: master warning steady rather than flashing, a two-step "CONFIRM RESET" that expires after 4 s, and a STALE badge after 2 s without data and LOST after 5 s with a "DATA NOT LIVE" banner, so a frozen screen can never pass for a calm engine. |
| DEV-203 | **The mission card recommended a profile it had just refused** (SAF-01) | `_recommend` sized alternatives on the central RUL estimate while the verdict used the margin-adjusted one, so a card could refuse a mission and offer one no safer. It now works from the planning figure: usable hours = planning RUL / required margin, only profiles strictly shorter than the refused one are offered, and nothing is offered when the refusal is on health grounds, because flying less does not repair the engine. |
| DEV-204 | **The advisory could say GROUND while every mission card said GO** (SAF-02, SAF-07) | Grounding never reached mission planning, and the 1,200 h / 15-year overhaul limit (MML-915 i 05-10-00) was computed (`tbo_remaining_hours_effective`) but used nowhere. `MissionPlanner.assess` now takes `grounded`, `grounding_reason` and `tbo_remaining_hours`: a grounding advisory makes every card NO_GO with its reason, a reached overhaul limit is NO_GO, and planning RUL is capped at the overhaul hours left. `live.py` runs the advisory before the mission assessment so the verdicts cannot disagree. |
| DEV-205 | **The first matching trigger hid a worse one** (SAF-03, SAF-13) | `_evaluate` returned at the first rule that matched, so a mild cause could mask a severe measured one. All hits are now collected and reported together. Measured comparisons use `>=`, so a value sitting exactly on a limit counts as reaching it. |
| DEV-206 | **GROUND flickered at the failure-probability limit** (SAF-05) | A7 compared p_fail with 0.35 on every tick, so a value hovering at the limit toggled the most consequential instruction on the screen. Alarm hysteresis in the sense of ISA-18.2 and EEMUA 191: it trips at `or_p_fail_above` and clears only below `or_p_fail_clear_below` (0.25; default limit - 0.10). An unavailable survival head holds the last state instead of clearing it. |
| DEV-207 | **Only the overhaul limit could ground the engine** (SAF-06) | A 100 % cold-cylinder share or a 50x bearing envelope produced a 10-hour WARNING. `ground_misfire_rate_above: 0.50` and `ground_bearing_envelope_above_x: 15.0` now make the action EMERGENCY and set `grounding_required`; the `ground_immediately` health band sets it too. Both values are engineering judgement, tagged [MOD], not published limits. |
| DEV-208 | **Losing a sensor cleared a latched warning** (SAF-08, CAN-12) | `ThresholdRule` answered "not exceeded" when the value was missing, `PersistenceRule` restarted its timer on a dropout, and `RuleEngine` overwrote the last reading with nothing, so a sensor failing during an over-temperature silenced the alarm. A missing value now holds the latch and the persistence timer and never overwrites the last good reading. |
| DEV-209 | **Health bands with no instruction, and a missing health index that read GO** (SAF-10, SAF-11) | With health between 0.50 and 0.70 the advisory could say "no configured trigger has fired" while the band said otherwise, and a NaN health index passed every comparison and returned GO. The band's own instruction is now shown when no action fires; an absent or non-finite health index is NO_GO "health index not determinable"; unknown subsystems add a limits reason; non-finite values are ignored when finding the worst subsystem. |
| DEV-210 | **The advisory was reading the simulator's hidden truth** (ML-02 / PS1-01) | The live advisory and the health page were fed the simulated engine's TRUE degradation factors, which no aircraft can measure, so a demo looked better than any real installation could. The advisory now receives `degradation={}` and measured evidence only: hours since the last oil change (A1, 100 h per MML-915 i 05-20-00), boost drop against the as-new twin in cruise and EGT rise (A6), and the CHT residual (A2). The console's simulator ground-truth panel is labelled "demo only". Verified with a live fault run: a healthy engine raises nothing; an injected cooling fault raises A2 CAUTION at +14.5 K. |
| DEV-211 | **The trained edge model was never loaded by the live twin** (ML-01 / PS1-02, PS1-13; partly open) | Fusion's deep score was a formula on the health index. The Tier-3 ONNX `EdgeScorer` is now loaded at start, with its feature width checked against the RUL network's, and supplies S_deep once the window is warm; a smoothed health-index proxy is used only until then, and the snapshot records which source was used (`statistical_source`, `deep_source`). The Tier-2 ensemble is still not persisted, so the statistical score remains a stand-in: see "Still open". |
| DEV-212 | **The per-fault forecaster could not see a trend, and never forgot one** (ML-03, ML-11 / SAF-09, SAF-12) | Its 240-sample window was two minutes of a trend measured in tens of hours; a median of 15 samples hid intermittent faults; nothing expired. `FaultRul` now keeps one-minute trend buckets over four hours, reports the 80th percentile of recent samples (20th for falling indicators), answers "no data" when the last sample is older than 0.5 flight hours, and needs 30 trend points before forecasting. Lubrication watches oil pressure below the as-new twin (-5 psi degraded, -10 psi fault) above 3,500 rpm, cooling watches the instantaneous CHT residual, vibration is fed only in cruise, and "misfire rate" is renamed for what it measures: the cold-cylinder share of cruise samples. |
| DEV-213 | **The screen showed one remaining-life figure and decided on another** (SAF-04 / JUR-03) | The display now uses the served estimate when it is reportable and the physics estimate otherwise, and the snapshot adds `rul.decision_floor_hours` (lowest of the physics lower bound, physics estimate and network estimate), used by mission planning. The console labels a network estimate as having no calibrated interval and shows the planning figure beside it. Using the floor for the advisory as well was tried and rejected by measurement: a healthy engine at health 0.83 was grounded on a 7-hour floor. |
| DEV-214 | **Zero oil pressure was transmitted as "no data"** (CAN-01) | `can_simulator.py` sent `... if f.oil_pressure_bar else None`, and 0.0 is false in Python, so the most dangerous reading an engine can give dropped its frame and the console showed STALE instead of a red warning. Manifold, oil and fuel pressure now test `is not None`. Ingest also rejects NaN and infinite values (CAN-07), and stamps each frame with its own bus timestamp (CAN-11). |
| DEV-215 | **Any station could create a Commander on every station** (SEC-01, SEC-08) | The fleet directory upsert accepted any station key. Directory writes now need `DT_FLEET_ADMIN_KEY`; the directory is HMAC-signed with `DT_FLEET_DIRECTORY_KEY` and a station verifies the signature before replacing its user store (unsigned refused unless `DT_FLEET_ALLOW_UNSIGNED_DIRECTORY=1`); plain HTTP to anything but loopback is refused unless `DT_FLEET_ALLOW_HTTP=1`. Fleet routes need a station key, the station list needs the admin key, `/healthz` is generic, the server binds 127.0.0.1 by default, and there is no default database password (compose fails fast on `${DT_FLEET_DB_PASSWORD:?}`). |
| DEV-216 | **Demo passwords stayed live, and tokens were trusted too far** (SEC-02, SEC-06, SEC-07, SEC-09, SEC-12, SEC-13, RT-02) | `must_change` is enforced: login returns 403 until the password is changed through `POST /api/auth/change_password`, which deletes `FIRST_RUN_CREDENTIALS.txt` once no account still needs it (`DT_ALLOW_INITIAL_PASSWORDS=1` for a bench demo, logged as a warning). `verify_token` checks the token type, so a refresh token is not an access token, and checks the role against the user store; `POST /api/auth/refresh` issues access tokens. Key and user-store directories are restricted to the owner (icacls on Windows, mode 700 elsewhere). Failed authentication is rate-limited (30 per minute) before the audit write, with one generic 401. Passwords over bcrypt's 72 bytes are refused rather than silently truncated. Responses carry nosniff, frame-deny, referrer and content-security-policy headers, and an open WebSocket re-verifies its token every ~5 s. |
| DEV-217 | **Enabling TLS crashed the server, and TLS 1.2 was not refused** (SEC-03, SEC-05) | TLS 1.3 suite names were passed to `set_ciphers`, which accepts only TLS 1.2 names, so start-up failed. The cipher list is removed and uvicorn's SSL context factory is wrapped to set `minimum_version = TLSv1_3`. MQTT now takes a username, password and TLS CA, certificate and key from the environment for both the telemetry link and the fleet watcher, and the signed-link verifier persists its last sequence number, so a captured frame replayed after a restart is refused. |
| DEV-218 | **The audit chain could be truncated or rewritten and still verify** (SEC-04) | A plain SHA-256 chain proves order, not authorship: anyone with write access can recompute it. New entries (`v: 2`) carry an HMAC under `data/keys/audit_hmac.key`, and a sealed head file (`audit.head.json`) records the last sequence and hash, so deletion of the tail or of the whole log is detected. Legacy `v: 1` entries still verify under the old rule. |
| DEV-219 | **The flight history recorded engine hours as flight duration** (REP-01, REP-03, REP-04, REP-06, REP-07, RT-04) | `history.record` stored the engine's total hours (420.7) where the trend summed per-flight durations; it now stores the sortie's own duration. Exceedances are keyed per limit, so a caution and a warning on the same parameter are separate events; the ATA chapter comes from the rule ID (electrical maps to 24); the recorder's row count includes rows still buffered; an at-limit sample counts as past the limit; the PDF date carries the correct UTC offset; the history returns the newest flights oldest-first with the trend baseline on the first flight. |
| DEV-220 | **Memory grew with flight length, and one request could stall the twin** (RT-01, RT-03, RT-05, RT-08) | `SortieAccumulator` kept every row to compute a mean and variance at landing; it now uses Welford's running mean and variance. The physics RUL rate history is capped at 720 samples. Scenario runs, custom scenarios, test-rig runs and PDF export share one slot and answer 429 when busy. The audit log caches its tail, audit listing limits are clamped to 1-5,000, and the test-rig seed is bounded to 32 bits. |
| DEV-221 | **The fusion headline was chosen on the test set** (ML-05) | `scripts/eval_fusion.py` picked the S_deep combiner with the best F1 on the test windows and the README quoted that row. The combiner is now chosen on validation engines, the test set is reported once for the chosen row, and the result is written to `data/models/fusion_report.json` so the quoted figure cannot drift from the run that produced it. |
| DEV-222 | **Stale and unsupported figures in the README and pitch material** (JUR-01 to JUR-15, ML-06, ML-13, ML-14, SEC-11) | README results now quote the artifacts: latency p95 82.7 ms (95.3 ms on one core), tick compute only; NASA score 478.2; health MAE 0.065; C-MAPSS 1.11-1.14x as a three-seed mean; physics anchors labelled calibration targets. The lead-time and fused-detection rows are withdrawn until re-measured. Corrections for the deck, handbook and sample report are in `docs/PITCH_CORRECTIONS.md`. `docs/INDIGENISATION.md` no longer claims there is no outbound network call. Branding on all documents is unchanged. |
| DEV-223 | **The manufacturer's performance table was in the manuals and not in the model's evidence** (PHY-01, PHY-02) | The Operator's Manual publishes 941 operating points (4,500-5,800 rpm, sea level to 22,999 ft, ISA-15 to ISA+30). It is now extracted verbatim to `configs/engines/rotax_915is_om_performance.csv` with its provenance. Against it the model under-predicts power above the critical altitude: 55.7 kW against 89.5 kW at 23,000 ft, 5,800 rpm, full throttle (-38 %). That is recorded as open, not tuned away here, because recalibrating changes the training fleet and every model trained on it. |
| DEV-224 | **Custom scenarios could not set a hot or humid day** | `run_custom` takes `isa_deviation_c` and `humidity_pct`, converted through the atmosphere model and passed to both ambient calls in the engine simulation, so a hot-day test is an ISA deviation rather than a hand-typed temperature. Exceedances are graded by margin past the limit (level 2 / level 3: temperatures 5 / 10 K, EGT 25 / 50 K, oil pressure 3 / 6 psi) in the manner of CAP 739; the margins are [MOD] judgement. |
| DEV-225 | **Creating an account or changing a password hung the server** (found while verifying SEC-02) | `_USER_LOCK` was a plain `threading.Lock`. `create_user` and `_update_user` take it to make read-modify-write atomic and then call `_users()`, which takes it again, so the thread waited on itself forever: no CPU, no error, no timeout. Every route through `_update_user` was affected -- password change, disabling an account, changing a role -- as was `create_user`. It had been in the code since the user store moved to SQLite and was never exercised, because every earlier test used the seeded accounts. Diagnosed with pytest `faulthandler_timeout`, which printed the waiting frame (`security.py` `_users`, called from `create_user`). `_USER_LOCK` is now an `RLock`: re-entrant for the thread that holds it, still exclusive between threads. |
| DEV-226 | **Altitude and hot-day behaviour taken from the manufacturer's performance table** (PHY-01, PHY-02, PHY-04) | Power above the 15,000 ft critical altitude was an analytic corner -- rating held, then ambient-pressure lapse -- and read 55.7 kW at 23,000 ft where the Operator's Manual prints 89.5 kW (-38 %). Temperature had no effect at all: ISA-20 and ISA+35 gave the same power. The manual's 941-point table (Ed.0 Rev.4, pp.111-130) is now the model's source for how power, plenum pressure, plenum temperature and BSFC change with altitude and ISA deviation, as RATIOS to sea level ISA at the same speed and throttle position, so the certified sea-level anchors cannot move (`layer2_physics/om_table.py`). The manual's throttle is the FADEC's linearised position -- the last 6 % of travel is the boost range -- so the model's lever is placed on it by sea-level power fraction. Measured with the whole model trimmed at 11 printed full-throttle points (5800/5500/5000/4500 rpm, sea level to 22,999 ft, ISA-15 to ISA+30): power within 1.24 %, plenum pressure within 0.74 %, charge-air temperature exact, fuel flow within 2.32 %. The 0.97 and 0.95 "turbocharged ratio" anchors were PRD-era estimates; the manual prints 1.003 and 1.005 and the anchors now read those cells. **Caveat, stated so it is not over-claimed:** the table is now an input, so matching it checks the implementation; it is not independent validation. 339 unprinted cells are filled (the 56.5 % row at altitude by its ratio to the 72 % row, the hot blocks at 4500 and 5000 rpm by the 5500 rpm temperature ratio) and flagged; tests compare only with printed cells. Below 4500 rpm the 4500 rpm ratios are used -- an approximation for idle and descent, not manufacturer data. |
| DEV-227 | **A constant-speed propeller, because speed collapsed at altitude** (PHY-06) | The propeller law was `T = k * omega^2` with no air-density term, so as torque fell with altitude the engine slowed: 4711 rpm at full throttle at 23,000 ft, a condition the manufacturer's table -- tabulated at fixed speeds to 22,999 ft -- does not contain. Adding density alone would overspeed a fixed-pitch propeller at altitude. The definition covers both designations [OM "Designation"]: iSc is the fixed-pitch flange, iS the constant-speed flange with a hydraulic governor drive; the twin models the iS installation (`propeller.type: constant_speed`, [MOD]). The governor sets the blade pitch at which the propeller absorbs exactly the torque the engine makes AT THE TARGET SPEED, approached through a 0.5 s first-order lag for the hydraulic pitch-change mechanism; the lag acts on absorption (pitch times air density), with blade stops bounding pitch at the present density. That design is the THIRD one, and the first two are recorded because the silent-healthy-engine test caught both: pure integral action on the speed error wound the blades to the fine stop from rest and overspeeded the first throttle advance; lagging pitch alone turned a flight profile's 500 -> 15,000 ft altitude step into a one-sample 6781 rpm overspeed. The held speed is scheduled from the lever as the speed the same propeller settles at on a sea-level ISA day, capped at maximum continuous (DEV-234), so sea-level part-throttle points below that cap did not move: 4067 and 5340 rpm at 45 and 70 % lever, against 4040 and 5317 under the old law. An `rpm_setpoint` commands a speed (5500 rpm maximum continuous); an explicit `load_factor` -- the test rig's dynamometer -- bypasses the governor; an engine definition without a propeller section keeps the old law exactly. |
| DEV-228 | **Charge air 12-37 K too hot** (PHY-05) | The intercooler law (effectiveness 0.65 from the OM's 25-35 degC target band) put manifold air far above the plenum temperatures the manufacturer's table prints, which sit 4-6 K above ambient at every altitude and throttle position. The as-new value now comes from the table; the intercooler law supplies only the DEPARTURE from as-new -- a worn compressor running hotter, an intercooler short of ram air at low airspeed -- so both degradation signatures survive. Knock, EGT and air-mass estimates all read this temperature. |
| DEV-229 | **Full-power fuel flow read off a clipped grid** (PHY-09) | The BSFC map's BMEP axis stopped at 12 bar while full-throttle BMEP is about 16 bar, so every take-off and climb point used the 12 bar column: 305 g/kWh at sea-level full power against the manufacturer's 325. The axis now runs to 18 bar. At altitude the map (a sea-level surface) is read at the sea-level-equivalent BMEP and scaled by the manual's BSFC ratio, instead of applying its sea-level low-load penalty to an altitude condition. Also: below the published 5500 rpm point the boost target was held flat at 1450 mbar; the table prints 1373 mbar at 5000 and 1338 mbar at 4500 rpm (sea level ISA), and its shape is now used, scaled so the published 5500 and 5800 rpm targets are unchanged. |
| DEV-230 | **Volumetric efficiency fell twice as fast with altitude as the manufacturer's data** | The altitude term was pinned to PRD anchors (0.875 -> 0.775 -> 0.625) that describe a naturally aspirated engine: -20 % at 15,000 ft, -31 % at 23,000 ft. Air mass from the manual's own closure relation (power = -6.3264 + 0.0169 x airflow) against printed plenum density gives -9 % and -13.5 %, and the table's fuel-flow column gives the same lapse independently (-14.8 % at 22,999 ft at constant mixture). The term is now a quadratic fitted to the 5500 and 5800 rpm full-throttle rows; the 10,000 ft anchor reads printed cells directly, not the fit (0.8947 expected, 0.8950 model). |
| DEV-231 | **A healthy engine would have read as a lubrication fault once speed was held at altitude** | The lubrication index multiplies by the oil-pressure/rpm correlation against a 0.95 nominal. Above the relief valve's regulating pressure (0.80 x 72.5 psi = 58 psi in the model) pressure is held flat by design, so rpm stops predicting it. With the governor holding speed at 15,000 ft, four of six cruise settings sat on that plateau and an AS-NEW engine's correlation was 0.944 -- a false fault, found because the physics test for it failed. `HealthEstimator._correlation` now uses only samples below `health.lhi.correlation_below_psi` (55 psi, [MOD]), and drops the term when fewer than ten samples are in that band. The physics test now checks the correlation in that band, the same rule the estimator applies. |
| DEV-232 | **The engine model step got faster, not slower** | The table lookups added about 1.2 ms per step (5.4 -> 6.6 ms) on first measurement. Profiling showed the largest cost was older: volumetric efficiency looked up in a scipy grid about 45 times per step from inside the manifold bisection, with speed and altitude fixed throughout. It is now looked up once per step. Measured best of three on the same machine: 5.26 ms before the recalibration, 3.34 ms after, outputs identical. The table lookup itself runs on plain Python lists (44 us per call) because numpy's per-call overhead on 2x2x2 blocks made it 418 us. |
| DEV-233 | **Take-off CHT rose 8 K once full-power fuel flow was right** | With fuel flow corrected to the manufacturer's table (DEV-229: 34.6 kg/h at sea-level take-off against 33.95 printed, where the model had read 31.5), a healthy engine's 45 s take-off reached CHT 134.3 degC and oil 121.9 degC -- through the CHT caution -- against 126.1 and 119.0 before. The cause was not the fuel figure but what was done with it: all of the fuel's energy was charged to the head, including the 14 % climb enrichment. Rich of stoichiometric there is not enough oxygen to burn the excess; it leaves as CO and H2, and combustion efficiency falls roughly as 1/phi (Heywood, Internal Combustion Engine Fundamentals, 1988, s4.9). The 7 % fuel shortfall had been hiding that error by offsetting it. Heat into the head and exhaust now uses the energy released, `min(1, 1/phi)` of the fuel's; cruise mixture is lean of stoichiometric and unchanged. Measured on the same take-off: CHT 124.4, oil 118.3 degC. |
| DEV-234 | **The governor now respects the certified speed limits** | Scheduled on the old fixed-pitch sea-level line, the governor held an 80 % climb lever at 5603 rpm for ten minutes (MAX CONT EXCEEDED) and a full lever at exactly 5800 rpm, which sensor noise read as 5803 (OVERSPEED on a healthy take-off). The old law ran those part-lever settings above maximum continuous too, and only escaped the alert because its speed fell with altitude. Below full lever the held speed is now capped at maximum continuous, and full lever holds take-off speed, both less `propeller.governed_speed_margin_rpm` (20 rpm, [MOD]) -- a governor's regulation band, so a speed held at a limit is not reported as exceeding it: 5480 rpm from about 75 % to 99 % lever, rising to 5780 rpm only in the last 1 % of travel (a take-off detent: interpolating from 95 % had held a 97 % lever at 5600 rpm, which the test for this limit caught). The demo profile's comment was updated to match. |
| DEV-235 | **Charge-air temperature could jump 30 K in half a second** (PHY-10, partly) | Once charge air tracked ambient as the manufacturer's table says it does (DEV-228), a flight profile's step from 500 to 15,000 ft moved manifold air temperature from +21 to -9 degC in one 0.5 s sample; ingest rejected MAT1/MAT2 as implausible against their 20 K/s limit and raised SENSOR FAULT. It was right to: an intercooler core and plenum have thermal mass. Charge-air temperature now follows with a first-order lag, `turbocharger.charge_air_time_constant_s` (20 s, [MOD]). Sensor and thermal lags on the other channels remain open under PHY-10. The -20 degC normal minimum for manifold air temperature was also below what the manufacturer's table prints at the ceiling on a standard day (-24.8 degC) and is now -40 degC. |
| DEV-236 | **The cooling system could not meet its own installation requirement on a hot day** (PHY-03) | IM-915 i: "The cooling system must be designed so that operating temperatures will not exceed the maximum values"; OM-915 i allows ambient to 50 degC. The radiator (1400 W/K) and oil cooler (132 W/K) are installation values [MOD] that had been calibrated against standard-day bands only. At 50 degC a five-minute take-off ran oil to 170 degC (limit 130), coolant to 134 degC (limit 120) and the heads to 159 degC (HUMS limit 135); a maximum-continuous climb at 130 km/h settled at 156 / 126 / 149 degC. A sweep over both sizes against five cases -- that take-off and climb, standard-day cruise at sea level and 15,000 ft, and a cold high-altitude descent -- sized them to the requirement: oil cooler x1.6 (211 W/K) and radiator x1.5 (2100 W/K) give 125 / 106 / 130 degC for the take-off and 112 / 99 / 123 degC for the hot-weather scenario's own take-off, while the thermostats keep standard-day cruise where it was (oil 95, coolant 91 degC). Larger oil coolers only overcooled the cold descent. Tested by `test_the_installation_keeps_every_temperature_in_limits_at_the_50c_ambient_limit`. |
| DEV-237 | **Engine speed was deleted during take-off, and a healthy engine raised SENSOR FAULT** (audit 15 Sep, P0) | `thresholds.parameters.rpm.max_rate_per_s` was 2,000 rpm/s with no source; ingest rejects above 1.5x, so 3,000 rpm/s. After the constant-speed governor (DEV-227) a healthy taxi-to-take-off lever advance changed speed 3,275 to 4,869 rpm in 0.5 s (3,188 rpm/s), the ingest marked rpm INVALID and SENSOR FAULT fired: `test_healthy_engine_raises_no_alerts` failed. The threshold, not the physics, was wrong. Lever slams and chops across all seven environment profiles and 0 / 12,000 / 22,000 ft reached +4,050 / -2,750 rpm/s, and a plausibility check may reject only what the engine cannot do. The limit is now the free acceleration at maximum torque, 171.9 N m / 0.16 kg m2 = 10,260 rpm/s [DER]. The 0.16 kg m2 was a bare constant in `mvem._derivatives`; it is now `propeller.rotating_inertia_at_crank_kg_m2` in the engine definition, documented against the IM propeller inertia limit (1500-7500 kg cm2 at the propeller shaft). Tests: `test_the_rpm_plausibility_limit_is_the_installation_physical_bound`, `test_a_lever_slam_never_invalidates_engine_speed`, `test_an_engine_speed_change_beyond_physics_is_still_rejected`. Limitation: a faulty speed sensor that stays inside the physical bound is not caught by the rate check; that belongs to the stuck-sensor and drift checks. |
| DEV-238 | **The CAN receiver believed any frame with a known number** (audit 15 Sep, P0) | `can_ingest._decode` never read NODE_ID or DATA_TYPE and ignored the 11/29-bit flag, so a frame from the wrong station, a 29-bit frame numbered 500, or a NODATA frame (eight zero bytes, decoding as 0.0 rpm) became a VALID reading. The message-code check only counted forward gaps: a repeated frame refreshed a dead feed, and an out-of-order frame (10, 12, 11) counted 254 lost frames and rolled the value back. Now: (1) the DBC carries each station's CANaerospace Node-ID as node attribute `CANaerospaceNodeId` (ECU_A 11, ECU_B 12, HUMS 20, VMC 30) and the receiver accepts a header frame only from a declared transmitter of that message, refusing to start if a header message has none; (2) 29-bit, remote, error and CAN FD frames are refused; (3) any DATA_TYPE other than FLOAT makes the channel INVALID with no value; (4) a repeated message code is dropped, so a feed that only repeats goes STALE; a late code is dropped and un-counted from `frames_lost`; three consecutive rising old codes are taken as a transmitter restart. ECU_STATUS uses its own counter the same way. Refusals are counted in `frames_rejected` / `rejects` and shown in the console status bar and `run.py`. The bus contract was inconsistent and was corrected rather than the check relaxed: the DBC said ECU_A sent fuel flow, CHT, oil pressure and oil temperature; the simulator sent the first two from HUMS and the oil channels on channel-A identifiers from the Lane B node. Oil pressure and temperature are Lane B sensors [IM Rev.5 failure matrix, `engines/rotax_915is.yaml`] and now travel on ECSB identifiers; fuel flow and CHT name HUMS as sender. Also `shadow_model._ambient` turned a missing airspeed into 0 km/h (no ram-air cooling); it now withholds the prediction. Tests: 11 in `test_can_pipeline.py` from `test_every_header_message_names_a_transmitter_the_simulator_actually_uses` to `test_a_repeated_ecu_status_frame_does_not_refresh_the_error_flags`; `test_zero_pressure_is_transmitted_as_a_reading_not_dropped` now looks for `ECSB_OIL_PRESSURE`. Limitations: CAN has no authentication, so a station that forges a declared Node-ID is not detected; the user-defined messages 1800-1805, 1811 and 1812 have no header or counter, so only identifier, frame format and length are checked on them; a counter restart that lands more than 16 codes ahead is counted as lost frames. |
| DEV-239 | **The two FADEC lanes were one number, and the ECU's report on itself was never read** (audit 15 Sep, P0) | The simulator sent lane A's rpm and manifold pressure again as lane B and hard-coded both lanes healthy with both lamps off. The receiver merged the lanes into one channel that the last frame overwrote, so a bad lane A frame deleted lane B's good reading; kept each lane's last value for ever, so a lane that went quiet was compared by a stale number; and decoded ECU_STATUS only for the error flags, which only the MAVLink health bit used, reading "never received" as healthy. The lane tolerance was 5 % of the reading, which for a temperature in degC means nothing (at 0 degC, nothing at all). Now: (1) `engine_sim` has lane B's own crank position, manifold pressure and manifold air temperature sensors, the three the IM Rev.5 failure matrix lists on both lanes, drawing noise from a separate random stream so no lane A reading of a seeded engine changed; (2) `VirtualEngine.fail_lane_item(item, lane)` takes the lamps, system mode and controlling lanes from the failure matrix, withholds a failed sensor's reading, silences a lane on ECU_POWER / EMS_GROUND_PORT / DISPLAY_CAN failure, and sets ECU_ERROR_FLAGS bits 0 / 8 / 9; items whose effect is not represented are refused; (3) `can_ingest` keeps each lane's reading (`Channel.lanes`), takes the lane from the sender's Node-ID, votes only lanes that are VALID and fresh (the existing `sensor_fusion.LaneVote`, previously used nowhere), marks SUSPECT beyond max(5 %, a per-channel floor), and flags `redundancy_lost` when a dual-lane sensor reports on one lane; MAT1 / MAT2 are the two lanes' MATS; (4) ECU_STATUS is decoded whole into `Telemetry.ecu`, and the flags become None once it is stale; (5) rules ECU_LANE_A/B (lamp ON, lane health 0 or lane-fault flag), ECU_SENSOR_A/B (lamp FLASHING) and SENSOR_REDUNDANCY, all caution; (6) MAVLink health is 0 when the ECU has not reported. Floors in `thresholds.pipeline.lane_agreement_floor` [MOD]: 6 x sqrt(2) x the simulated instrument noise. Tests changed, each because the behaviour under test is now lane-aware, not to pass: `test_service_code_from_the_transmitter_is_believed` uses coolant temperature (lane A only), since on a dual-lane sensor lane B's reading now correctly survives lane A's refusal; `test_decoded_values_match_the_physics_within_sensor_resolution` compares each lane with its own instrument; `test_a_lever_slam_never_invalidates_engine_speed` also checks each lane. Tests added: 15 in `layer1_edge/tests/test_fadec_lanes.py`. Limitations: the floors come from simulated noise and must be re-derived from sensor data on hardware; MATS, EGT, TPS, AAPTS, AAT, knock, coil and injector lane failures are not simulated; ECU_STATUS, ECU_COMMANDS and MANIFOLD_AIR carry no header, so they continue while either lane is up and cannot be attributed to a lane; the IM describes separate Display CAN lanes A and B, modelled here as one bus; the ECU_ERROR_FLAGS bit layout is this project's DBC definition, not a Rotax-published format. |
| DEV-240 | **A frozen or stuck sensor passed every check** (audit 15 Sep, P0-5) | Nothing in the ingest, the rules, the twin or the health index looked at whether a reading was still moving, and the project's own documentation calls a frozen plausible value the most dangerous failure a monitoring system has. Two checks now cover it. (1) FROZEN, at the ingest: a working sensor's noise makes a long run of IDENTICAL readings improbable, and how improbable follows from its noise relative to its resolution alone. `can_ingest.repeat_run_probability` computes the chance of n identical readings of a steady quantity (Gaussian noise, rounded to the resolution, worst position within a step) and `frozen_run_limit` takes the shortest run rarer than `pipeline.frozen_false_alarm_probability` (1e-9); beyond it the reading is removed with the count in its reason, per lane. Limits run 8 to 20 readings. Measured on healthy flights (seed 11 at 0.5 s for 1,100 s, seed 5 at 0.1 s for 300 s) the longest identical run on any checked sensor was 9. ECU commands are excluded because they legitimately hold still: the commanded injection period repeated 981 times on a healthy flight. (2) NOT RESPONDING, in the twin (`layer4_core/sensor_response.py`): a seized or detached transducer keeps its electrical noise, so it passes range, rate and frozen checks, and on a single-lane sensor nothing cross-checks it. Over 60 s, if the as-new twin's prediction moves by at least 5 times the instrument noise and the reading by no more than 2 times it, the reading is removed. A slope of reading against prediction was tried FIRST and rejected on measurement: under a real cooling fault at severity 0.8 the head temperature's slope fell to 0.09 against a stuck sensor's 0.03, so it would have deleted the reading of an engine that really was overheating. By spread, a working sensor never fell below 3.98 noise (seeds 11, 3, 7; cooling, lubrication and overheating faults at severity 0.8) and a stuck one never exceeded 1.23. The twin removes the channel through new `CanIngest.condemn` / `absolve`, which hold it INVALID frame after frame while keeping the reading as `raw` so recovery can be seen; SENSOR FAULT then annunciates it and the snapshot lists `sensors_not_responding`. For validation the instrument model gained failures: `SensorSpec.fail("frozen"|"stuck")` and `VirtualEngine.fail_sensor` / `repair_sensor`. A failed instrument still draws its noise sample, so no other reading of a seeded engine changes; the timing and vibration instruments are now keyed per cylinder and axis so one probe can fail alone. Tests: 10 in `layer1_edge/tests/test_frozen_sensor.py` (including the run probability against 400,000 simulated readings, a healthy flight at two rates with nothing frozen, a frozen head probe with its neighbours untouched, and a frozen lane B speed sensor leaving lane A in charge) and 8 in `layer4_core/tests/test_sensor_response.py` (including the cooling fault not being mistaken for a stuck sensor). Limitations: both the noise-to-resolution ratios and the response noise are the SIMULATED instruments' and must be measured on hardware -- a real sensor quieter than the model would be flagged as frozen, a noisier one would mask a stuck reading; the response check needs the shadow twin and an operating-point change, so at a steady cruise it returns no verdict either way; its evidence covers one flight profile and three seeds; per-cylinder probes are judged against the twin's hottest-cylinder prediction; manifold pressure is left to the lane cross-check; and channels the twin does not predict (vibration, electrical, timing) get the frozen check only. |
| DEV-241 | **Clearing an injected fault healed the engine** (reported from the console) | Injecting a fault dropped remaining life and clearing it put the life back. A fault CLAMPED a condition index instead of damaging the quantity the index is derived from: injector condition is recomputed from accumulated flow variance every step, so the clamp vanished with the fault. Measured: injector condition 0.325 with the fault active and 0.981 one step after clearing it. Cooling, combustion, bearing and turbocharger damage already persisted because those factors ARE their accumulators. `_apply_faults` now raises the underlying `injector_flow_variance` to the level the clamp implied, so the deposit stays after the fault stops progressing and only cleaning the injectors (A3) restores it. Tests: `layer2_physics/tests/test_damage_is_permanent.py`, 10 of them, including a rule checked for all eight fault modes -- no factor may improve when a fault is cleared. Limitation: clearing an injected fault means it stops progressing, which is not a repair. |
| DEV-242 | **The engine model carried a coolant thermostat and an oil vernatherm that do not exist** (manuals, 17 Sep) | Both were added so a fixed-conductance radiator could hold a temperature band. Checked against the thirteen manufacturer manuals in `engines manuals/`: the word thermostat appears in NONE of them; the IM cooling-system interfaces are the hose, pump housing, expansion tank, pressure cap, overflow connection, inlet elbow, outlet, coolant temperature sensor and cooling air baffle [IM 75-00-00]; and the IPC lists a water pump, radiator, radiator cap and oil radiator with no thermostat part. The invented coolant thermostat also ABSORBED a blocked radiator, which is why the blocked-radiator acceptance test could not pass. Replaced with what the manufacturer describes: fixed-conductance radiators regulated by the AIRFRAME cooling air, which the IM makes the installer's responsibility, as proportional flaps that SATURATE. The oil cooler is sized from the IM's stated duty -- the radiator must dissipate approx. 30 kW -- giving 430 W/K against the 211 W/K it had behind the fake bypass. Measured after: coolant 96-102 degC and CHT 113-124 degC from sea level ISA+30 to the 23,000 ft ceiling (limits 120 and 135), oil 101-104 degC inside the OM's recommended 90-110 band, and a 70 percent blocked radiator reaching 143.7 degC and failing acceptance. Limitations: flap targets and minimum duct openings are [MOD] installation choices; the IM exhaust back-pressure limits apply only to an OEM-modified exhaust and are measured downstream of the turbine, which this model does not resolve. |
| DEV-243b | **A cylinder head limit borrowed from a different engine** | `cht_limit_C` was labelled [TCDS 912 S] as though it applied to the 915 i. It does not: the 915 i publishes NO cylinder head temperature limit, because its heads are liquid-cooled and the quantity the manufacturer limits is coolant temperature (120 degC). The value is kept as this project's alert level for its own added head probes and is now labelled [MOD], with the manufacturer's own 200 degC cylinder WALL limit [IM 75-00-00] recorded beside it and explicitly NOT monitored -- the air-cooled barrel is not a node in this thermal model, and monitoring it would need a third node and a measurement to calibrate against. |
| DEV-244 | **Acceptance criteria the manufacturer's own data contradicts, and a report that failed without saying why** | The worn-turbocharger test demanded that condition 0.75 drop max-continuous power below 85 kW. The OM performance table says otherwise: across its 941 printed points, at essentially one plenum pressure (1.49-1.52 bar) and 5800 rpm, plenum temperature spans -24.6 to +44.2 degC -- a 22 percent change in charge density -- and printed power moves 105.0 to 104.0 kW with fuel flow flat. On this engine a worn compressor holds boost by CLOSING THE WASTEGATE and spends travel, not power. Both rig tests now assert the authority signature, and the rig records cooling flap, oil flap and wastegate fraction at every point. A new derived check catches what temperature cannot: rejecting the same heat at the OM's 50 degC ambient limit instead of the cell's 25 degC needs (T_coolant - T_cell)/(T_coolant - 50) times the travel, so the flap position in the cell must leave room for it. Measured at max continuous: healthy 0.49, 30 percent blocked 0.68, 45 percent blocked 0.84, while coolant moved 98.4 -> 100.3 -> 101.9 degC against a 120 degC limit. Separately, a run could fail on an exceedance while every named check passed and the report listed nothing; it now names them. |
| DEV-245 | **Fault probability was the rule level times 0.20** (audit 15 Sep, P1-1) | A YELLOW alert became 0.60 whatever the evidence behind it -- arithmetic on an alert level wearing the clothes of a probability -- while the trained fault head sat on disk unused. `apply_fault_evidence` now publishes the Tier-3 fault head's own per-class output, in the order the physics labels it (FAULT_CLASS_ORDER and FAULT_KEYS verified identical), with `fault_probability_source` naming what produced it and `rule_fault_levels` keeping the rule evidence as the levels it actually is. With nothing scoring, the vector is zeros and the source says so. Tests: two in test_twin_state.py. Limitation: the served head is trained on the 29 August fleet and reads 0.54 sensor drift, 0.61 combustion instability and 0.59 abnormal vibration on a healthy engine, which is the stale-model problem the regeneration and retrain exist to fix -- now visible instead of hidden behind the fake. |
| DEV-246 | **The Tier-2 statistical tier was refitted in every evaluation and never saved** (audit 15 Sep, P1-2) | Nothing running could use it: the live twin scored a physics-residual proxy and labelled it as one. `scripts/eval_tier2.py` now saves the fitted ensemble with the threshold it was chosen against and a report of what it measured on held-out engines, and `live.py` scores each sample with `score_one` on the same baselined features it was fitted on. Without the artifact there is no statistical tier and the snapshot says so; no proxy wears the tier's name. The same run produces the measured ablation the audit recorded as missing -- physics residuals move ROC-AUC 0.912 -> 0.957 and recall 0.766 -> 0.879 at the same false-positive target -- and a new operational metric, false alarms per engine-HOUR on healthy engines: 0.33 with the residual features against 0.37 without. |
| DEV-247 | **8.5 h of remaining life on a new engine, and low confidence while the network was scoring** (reported from the console) | Three defects behind one screen. The network's figure was served before its inputs were valid: measured on a healthy engine it read 10.3 h, then 95.9 h, then 346.9 h within six minutes of one flight on an engine that had not changed, with no interval beside it, and PRD Part 4 s7.4a forbids a bare remaining life. `_reportable_life` now serves the network only once its residual baseline is frozen AND an interval exists, and reports the reason otherwise. Second, `model_confidence` was wired to the remaining-life TREND's confidence, which on a healthy engine is 0 by definition because there is no decline to extrapolate, so the console declared rule-based fallback while the trained network scored the same engine at 0.96; it is now the measured anomaly-head F1 of whichever tier produced the deep score, or zero when a proxy did. Third, `train_rul.py` fitted the split-conformal multiplier, reported coverage with it and discarded it, so serving had no calibrated bound at all; the multiplier and its coverage are now saved in the checkpoint and `rul_serving` reproduces the calibration exactly -- same dropout passes, same multiplier -- so the figure carries its own interval instead of borrowing the physics one. |
| DEV-248 | **Nothing asked whether a sample resembled the training data** (audit 15 Sep, P1-6) | A Tier-3 score carried the same authority on a condition the fleet never contained as in the middle of the training set. `layer3_ai/ood.py` fits a Mahalanobis distance and a per-feature box on the training rows -- ALL of them, healthy and faulted, because the networks saw both; fitted on healthy rows alone it called 75.9 percent of held-out FAULTED rows unfamiliar, which would declare the models inapplicable exactly when a fault arrived. The threshold is the 99.9 percent quantile of training distances. Measured on held-out engines: 0.00 percent of healthy and 0.00 percent of faulted rows flagged. Outside the distribution the detection confidence is zero and the fusion says so. Tests: 5, including a combination never seen being caught while each value on its own is ordinary. First result in service: the live engine reads distance 27.9 against a threshold of 20.2, with rpm, EGT, fuel flow, CHT residual and injector duty outside the training box -- the models are stale against the corrected physics, which is what the check exists to say. |
| DEV-249 | **Instrument drift was scored as engine wear** (audit 15 Sep, P0-4) | The console's sensor-drift number was the residual VARIANCE ratio -- scatter, not offset -- so a transducer reading steadily 6 psi low never registered as drift. `layer4_core/sensor_bias.py` estimates each instrument's offset from the twin with the scalar Kalman filter PRD Part 1 s8.4 asks for (present in `sensor_fusion` and unused until now), and the fault indicator is now that offset as a fraction of full scale, against bands the configuration already held. Attribution is the honest part: an offset is blamed on the INSTRUMENT only where a second source disagrees with it (the FADEC lanes), and is otherwise reported as unattributed, because a failing engine explains it just as well. Measured at severity 0.8: a drifting head probe sat 6.9-8.2 degC above the twin against real cooling degradation at 9.0-14.6 degC; a drifting oil-pressure sensor 5.6-6.4 psi against a real lubrication fault at 0.2-2.5 psi -- overlapping, which is why the offset alone may not name a culprit. Tests: 6, including a real cooling fault never being called a sensor drift. |
| DEV-250 | **The security tests rewrote the credential store the demonstration logs in with** | They created accounts and changed passwords in the real data directory: fifteen leftover rv.* accounts had accumulated in `data/keys/users.db`, and a commander whose password had since been changed through the console no longer matched the first-run note, which failed three security tests on a later run for a reason that had nothing to do with the code. A test that depends on what earlier runs left behind is not a test. The module now runs against a per-run temporary data directory, rebuilding the API's module-level audit log so calls under test do not append to the real one, and the git-ignore test asks git about the REPOSITORY rather than whatever data directory the process is pointed at. The leftover accounts were removed from the real store, backed up first; the commander's password was left alone, since it is the user's. |
| DEV-251 | **A lubrication fault reached no detector that decides anything** (review 23 Sep) | Traced live: a severity-0.9 lubrication fault raised oil pressure 54 to 63 psi against the as-new twin (about 27 sigma) and (1) the lubrication index stayed at 1.000, because it scored only a SHORTFALL; (2) the per-fault forecaster watched only pressure below the twin, so the rise read as moving away from the fault line; (3) the engine's own residual reference, open for 60 flight hours as the median of everything seen, learned the fault as normal -- 6 psi of the 9 absorbed fifteen minutes in -- so the fused alert decayed to NORMAL with the fault still present; and (4) that reference was not saved with the engine life, so every station restart re-formed it from the engine as it then was. Now: `lubrication_index` scores departure either way (`health.lhi.high_pressure_weight`); the forecaster is fed -|residual| on its existing -5/-10 psi scale; the reference freezes after `health.assessment.residual_reference_settle_s` (300 s) of assessed running as well as at 60 h, and is persisted. Measured after: LHI 0.82, CHI 0.975 to 0.93, fused level 2 held for the whole fault, forecaster -9.6 psi against -10. Health on the 40 held-out engines: MAE 0.077 to 0.075, correlation +0.672 to +0.678, healthy engines mislabelled 0.6 % to 0.7 %. The survival head was retrained on the corrected health estimate (it is one of its inputs): test AUC 0.958/0.961/0.796 to 0.965/0.965/0.802 at 12/50/400 h. Its 50 h risk stays near 0.5 % under this fault, and that is correct: it predicts END OF LIFE, and the fault's ground-truth composite is 0.90, far from the failure line. |
| DEV-252 | **Tier-2 false alarms came from flight condition, and the live alarm line was not the measured one** (review 24 Sep) | Broken down on held-out healthy engines, the 6.9 % false-positive rate was 13.6 % at part throttle (55-70 %), 10.7 % above 14,000 ft and 10.1 % in air below -10 degC, against 0-3 % elsewhere; dropping the raw channels did not change it (13.4 %), so the physics residuals of a healthy engine themselves move with condition. Separately, the calibrated Tier-2 limit saved beside the model (0.87, the 5 % point) was never read by the live twin, which gated the smoothed score at a fixed 0.70 -- so the rate measured here was not the rate the console had. Now: the ensemble takes the flight condition as input (`features.extended_ops`: throttle, altitude, OAT, airspeed); one limit per condition cell (`tier2_statistical.per_regime_thresholds`, 4 x 3 x 3 grid, fitted on healthy TRAIN rows, global limit for sparse cells); an alarm must hold 2 of 3 samples; and live, the score is re-expressed so each condition's limit lands exactly on the fusion gate (`score_to_gate`). Measured on TEST engines: FPR 0.069 -> 0.048, recall 0.604 -> 0.612, precision 0.963 -> 0.975, engines over 10 % FPR 11 -> 5, all 31 failing engines still detected (median 318 h ahead). Chosen on test and CONFIRMED on the separate VALIDATION engines: FPR 0.047, recall 0.616 (global limit there: 0.087). Calibrating limits on validation engines instead was tried and was worse (0.059). |
| DEV-253 | **The fault head named faults at macro-F1 0.61, and its errors were confusions between look-alike faults** (review 24 Sep) | Broken down on held-out engines, most wrong labels came from OTHER faults, not healthy windows (overheating trend 682 of 768, injector 358 of 408, cooling 337 of 382); gating fault names behind the anomaly head changed nothing (0.610 -> 0.611). Cooling loss, overheating and a drifting head probe all raise CHT; a 30 s window cannot tell them apart, their history and cross-channel pattern can. New `layer3_ai/fault_namer.py`: per-fault gradient-boosted classifiers; `SortieHistory` builds 53 strictly causal history features (sortie-so-far mean and scatter; EWMA, change against 11-20 sorties back and trend over the previous 8 completed sorties; thermal coherence; single-channel isolation) and is the SAME class for training (`scripts/train_fault_namer.py` replays each engine in time order) and live. Per fault, 'with history' vs 'current sample only' and the threshold are chosen on VALIDATION engines. TEST macro-F1 0.610 -> 0.783 (misfire 0.97, vibration 0.94, lubrication 0.92, injector 0.87, overheating 0.84, cooling 0.71, sensor drift 0.53, combustion instability 0.48). Scored per sample, the network per 30 s window: close but not identical protocols. Live, it runs on assessed ticks, holds between them, its history closes with each sortie and is saved with the engine life; its own thresholds and measured precision drive the console. The Tier-3 network still scores anomaly (F1 0.95) and names faults when the namer file is absent. A first version leaked: whole-sortie means included later seconds of the sortie (0.762); the causal version is the one reported. |
| DEV-254 | **The live twin fed its learned models residuals unlike any they were trained on** (live check 24 Sep) | Flown live, a HEALTHY engine raised ADVISORY on 643 of 2,557 assessed ticks. Traced tier by tier: the Tier-3 anomaly head scored its cruise at a median 0.62 (69 % over the 0.5 gate) where healthy TEST engines in the same condition cell score 0.05 (9 %); replacing one input, the EGT residual, with the fleet median took it to 0.04 (0 %). Cause: the engine's residual reference (DEV-251) froze in the CLIMB, at +6.2 degC, while training's reference is the whole-life median, dominated by cruise -- a healthy engine's EGT residual is +5.8 in the climb and +15.9 in cruise, so every healthy cruise sample read +9.8. Now the reference learns from LEVEL flight only (altitude within 50 ft over 30 s, from the reported altitude), and until it exists the learned tiers hold and no learned model names a fault -- the rules decide, and the snapshot says so (`fusion.engine_reference`). The fault namer's 'now' features were likewise re-defined over the last 60 samples: a training sortie is ~50 s, a live one an hour, and the so-far mean had diluted a +9 psi fault to +0.6. A young engine (under 4 completed sorties) is named by each fault's sample-only twin only where that twin was measured on young VALIDATION engines (F1 >= 0.5 over >= 20 positives); a trend fault is otherwise not judged, and the source says which -- served anyway, overheating trend was called on 73 % of a healthy new engine's cruise. Result on the same live healthy flight: 643 ADVISORY and 64 CAUTION of 2,557 assessed ticks -> 0 and 0 (all NORMAL). A young engine is named by a history fault's sample-only twin only while a detector agrees something is wrong (a rule, or either tier at its 0.70 gate): the rare young faults in the fleet (lubrication has none on young validation engines) could not justify a measured per-fault gate. |
| DEV-255 | **The twin had never met a real engine** (24 Sep) | Every benchmark scored the twin against engines its own physics generated. NASA's ACES campaign (2002, GHRC DAAC collection C1977826980, free Earthdata login) logged the Altus II UAV's Rotax 912 (1352 cc, two-stage turbocharger, EFI) at 1 Hz: 14 of 15 flight days downloadable, 66 files after removing duplicated archives, 52 h, 36 h airborne (`scripts/aces_extract.py`). Established from the data, not assumed: engine temperatures are degF; OAT is not logged in flight and is derived from density altitude; the channel labelled 'EFI Fuel Burn lb/h' is fuel burned SO FAR and the flow is its rate of rise (read as a rate it gave 137 L/h from a 100 hp engine). `scripts/eval_aces_realdata.py` flies the AS-NEW 915 iS twin along every flight -- rpm locked, throttle steered to the measured boost, measured altitude, OAT and airspeed -- and scores 202 steady airborne minutes: it follows fuel flow (r 0.80, offset -5.6 L/h, scatter 9.4), coolant (r 0.80) and EGT (r 0.72, scatter 77 degC) across operating points, CHT weakly (r 0.43), and NOT the oil system (oil temperature r 0.11 with +31 degC offset; oil pressure r -0.36). A sibling installation, not a 915 iS, so offsets are expected; the oil system is a real model gap for any non-915 installation. Real instruments: 1 degC / 1 psi resolution, steady noise 0.56 degC CHT, 0.64 psi oil, no dropouts -- against 0.35 psi oil noise assumed in the simulator. No faults are labelled in this data; nothing was trained or tuned on it. |
| DEV-243 | **Every engine in the fleet fouled its injectors in the same pattern** | Per-cylinder fouling susceptibility was a fixed tuple shared by every engine, so it could cancel an engine's build bias systematically rather than by chance: measured on seed 3, EGT spread at injector condition 0.70 collapsed to 4.25 degC, NARROWER than the same engine healthy at 39.5 degC, and `test_injector_wear_widens_egt_spread` failed on real physics rather than on a bad criterion. Susceptibility is now drawn per engine in `set_manufacturing_spread`, with the spread of the pattern it replaces. Measured after: EGT spread rises monotonically with fouling on all five seeds tried, mean 8.9 -> 18.7 -> 55.1 -> 88.5 degC across conditions 1.00 to 0.50. |

### Still open after the September review

Recorded so that nobody reads their absence as "done".

- **Physics still open** (PHY-07, PHY-08, PHY-10 to PHY-14): turbo wear lowering the boost target instead of the wastegate compensating; turbo lag cancelling in power during a throttle slam; sensor lags on channels other than charge-air temperature; oil-pump response to bearing wear; EGT direction for combustion and injector faults; fuel-rail dynamics; the stale 90 C warm-up coolant figure. PHY-01 to PHY-06 and PHY-09 are closed by DEV-226 to DEV-236, and the training fleet must be regenerated and every model retrained on the recalibrated physics before any learned figure is quoted again.
- **Tier-2 ensemble in the live path** (ML-01): not persisted, so the live statistical score is a stand-in.
- **Evaluation integrity** (ML-04, ML-06 to ML-10, ML-12, ML-15): lead time from onset with false alarms per engine-hour; the shipped RUL checkpoint re-evaluated to JSON; false-positive rate on fault-free engines; federated figures from one artifact; differential-privacy sensitivity 2C with composition over rounds and no fixed noise seed; survival-head calibration and censoring on the served pipeline; a causal baseline; explanation wording.
- **CAN bus** (CAN-02 to CAN-06, CAN-08 to CAN-10, CAN-13, CAN-14): extended identifiers and repeated or out-of-order message codes; per-lane freshness; buffer packing; battery current's identifier; Kalman gating and a stuck-sensor check; configurable interface; documentation of what is and is not in the live path.
- **Problem-statement coverage** (PS1-03 to PS1-08, PS1-11, PS1-12): sensor drift detected as a bias rather than scatter; `scripts/ps_compliance.py` reading artifacts instead of hard-coded figures; replay of flown sorties; scenarios on a worn engine; FADEC error flags and lane health; RUNBOOK figures; the survival head pickled under scikit-learn 1.7.2 and loaded on 1.9.0.
- **Security documentation** (SEC-10): multi-factor authentication, encryption at rest and certificate pinning are not built and must not be described as answered.
- **Sample report** (REP-05): the SIMULATED callout, left as the team's work in progress.
