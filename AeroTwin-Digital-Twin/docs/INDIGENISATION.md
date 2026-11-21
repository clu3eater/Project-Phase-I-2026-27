# Indigenisation

Closes gap **G5**.

The problem statement asks for an *"indigenous Digital Twin framework"*. That
word carries a specific obligation in a defence procurement, and it is worth
being precise about what is being claimed and what is not, because a claim that
overreaches is worse than a narrower one that holds.

Everything below is **measured**, not asserted. The measurement is executable:

```bash
python scripts/licence_audit.py            # exits non-zero on a finding
python scripts/licence_audit.py --verbose  # every package, version, licence
```

It walks the *installed dependency closure* rather than the declared top-level
list, so it cannot be satisfied by editing a manifest.

---

## 1. What is claimed

**The framework is Indian-authored, runs entirely on infrastructure the
operator controls, and carries no licence cost, no export-controlled
component, and no foreign vendor in its critical path.**

That is a claim about the *framework*. It is not a claim about the engine, the
regulator's documents, or the origin of the open-source numerical libraries the
world runs on. Section 5 says what is not indigenous.

---

## 2. Dependency and licence audit — measured

| | Python | Console (npm) | Total |
|---|---|---|---|
| Third-party components in the closure | 70 | 115 | **185** |
| Permissive (MIT / BSD / Apache-2.0 / ISC / PSF / CC-BY) | 69 | 115 | **184** |
| Weak copyleft (LGPL) | 1 | 0 | **1** |
| Strong copyleft (GPL / AGPL / SSPL) | 0 | 0 | **0** |
| Proprietary or source-unavailable | 0 | 0 | **0** |
| Licence cost | ₹0 | ₹0 | **₹0** |

Direct console dependencies are React and React-DOM only; the rest of the 115
is the Vite and TypeScript build chain, which does not ship in the artefact.

### The one non-permissive licence, stated rather than buried

**`python-can` is LGPL-3.0-only.** It is a core dependency — decision **D1**
puts the CAN bus at the centre of Layer 1, and the PS explicitly asks for
"CAN bus / SocketCAN based engine data acquisition".

The LGPL is *weak* copyleft: it constrains the library, not the application
that imports it, provided the recipient can replace the library with their own
version. A Python package imported at runtime satisfies that condition
inherently — there is no static linking, and `pip install python-can==X` is the
replacement mechanism.

**What this means for a delivered system:** `python-can` must ship as a
separable, replaceable component with its licence text intact, and its source
must be available to the recipient. Both are automatic for a pip dependency.
It does **not** place any obligation on the DRDO-owned code in this repository.

This is recorded here because a distribution constraint discovered at handover
is a problem, and one written down in advance is a decision. `licence_audit.py`
fails the build on any *strong* copyleft dependency, so this cannot silently
become a worse problem later.

---

## 3. Data sovereignty — measured, not asserted

**No component of this system makes a call outside the establishment's own
network.** Verified by searching the source tree for outbound HTTP, socket and
cloud-SDK calls. The console talks only to its own ground station
(`http://127.0.0.1:8000`). The one other outbound path is OPTIONAL fleet sync
(`layer4_core/fleet_sync.py`): it is off unless `DT_FLEET_URL` is set, and then
reaches only the operator's own on-premise fleet server. An earlier version of
this page said the loopback address was the only URL anywhere, which overlooked
fleet sync (SEC-11).

**The console loads nothing from the internet.** No CDN script, no external
font, no analytics. Verified by search: there is no external URL in
`layer5_viz/gcs_console/src` or its `index.html`. A defence console that pulls
a webfont from a foreign CDN is not air-gappable, and this one does not.

**Telemetry does not leave the aircraft even in the fleet-learning case.** The
federated learning path (`layer3_ai/fed/federated.py`) exchanges model weights,
never rows. Measured over 25 rounds with 3 clients: **51.92 MB of telemetry
stayed on the aircraft; 12.60 kB of weights crossed the link** — a 4121×
reduction, and the fleet model matched the centralised one at 0.869 ROC-AUC.
This is the difference between a fleet-monitoring architecture that requires a
foreign cloud and one that does not.

**Every model runs locally.** There is no inference API call, no hosted model,
no API key anywhere in the system. Detection, health, RUL and explanation are
all computed on the operator's own hardware.

---

## 4. Deployment on Indian infrastructure

Nothing in the stack requires foreign hardware or a foreign service:

| Layer | Requirement | Indian deployment path |
|---|---|---|
| Edge (on-aircraft) | ARM64 or x86-64 SBC, SocketCAN, ~1 GB RAM | Any COTS SBC with a CAN transceiver; the edge image needs only `onnxruntime`, not torch |
| Twin core / GCS | x86-64, 4 cores, 8 GB RAM | Standard workstation; runs offline |
| Training | One GPU, or CPU-only with longer runs | C-DAC PARAM or any institutional cluster; no cloud dependency |
| Fleet | The federated server is a single Python process | On-premises at the operating base |

The whole system ships as a `Dockerfile` + `docker-compose.yml` and runs with
no registry access beyond the initial image build, so it installs inside an
air-gapped network from a local mirror.

Adding a new engine is a YAML file with **zero code change** — the mechanism by
which this framework would be pointed at an indigenous engine (see §5).

---

## 5. What is **not** indigenous — stated plainly

Claiming otherwise would be dishonest, and each of these is a real
consideration rather than a disclaimer:

1. **The reference engine is Austrian.** The Rotax 915 iS is a BRP-Rotax
   product, and its type certificate is EASA's. It was chosen because it is the
   only current-production turbocharged aero piston engine in this class whose
   **full certified limit set and FADEC/CAN architecture are public** — which is
   what makes every threshold in this system traceable to a regulator's document
   rather than invented. An indigenous engine (e.g. a VRDE/HAL programme) would
   be supported by adding one YAML file; the framework itself is engine-agnostic
   and already carries two engine profiles.

2. **The numerical and ML libraries are foreign-origin open source.** NumPy,
   SciPy, PyTorch, scikit-learn and React are US-origin projects. They are
   permissively licensed, source-available, forkable and locally mirrorable, so
   they create **no vendor dependency, no licence cost and no export-control
   exposure** — but they are not Indian-authored, and this document does not
   pretend they are. The *system* is indigenous; the general-purpose
   numerical substrate is global open source, as it is for every comparable
   system in the world.

3. **CPython itself is foreign-origin open source**, on the same terms.

4. **The exact Rotax Display CAN message assignment is not public.** The DBC in
   this repository uses open **CANaerospace Rev 1.6** standard identifiers. It
   must never be presented as the Rotax database. An integration against real
   hardware requires the assignment from an authorised Rotax distributor.

5. **SAE ARP4102/7 display symbology is paywalled and was not obtained.** The
   console's engine-display conventions trace to FAA AC 25-11A via the FAA HFDS
   compilation instead.

---

## 6. What indigenisation actually buys here

Not a slogan — three concrete properties that a foreign-dependent alternative
would not have:

1. **It runs air-gapped.** No component needs the internet at runtime, so the
   system can be deployed on an operational network without an exception.
2. **It cannot be withdrawn.** There is no vendor who can revoke a licence,
   discontinue a product, or be subject to an export restriction that would
   ground the capability. Every one of the 185 components is source-available
   and locally mirrorable.
3. **The data never leaves.** Engine telemetry from an operational MALE UAV is
   sensitive — it discloses sortie length, altitude profile and endurance.
   The federated path was chosen specifically so that fleet-level learning does
   not require centralising it.

---

## 7. Keeping the claim true

`scripts/licence_audit.py` is wired to fail on:

* any **strong copyleft** dependency entering the runtime closure;
* any module the source **imports but does not declare** — which would mean a
  clean checkout cannot run, and is how an undeclared foreign component sneaks
  in.

It also reports dependencies that are **declared but never imported**, each of
which must carry a stated reason. Running it during this audit found and
removed exactly that: `flwr`, `stumpy`, `shap`, `matplotlib`, `paho-mqtt`,
`structlog` and `pydantic-settings` were declared and imported nowhere — a
seventh of the manifest was aspirational — and `python-pptx` was imported by a
tracked script and declared nowhere at all.

The audit belongs in CI for the same reason the compliance matrix is
executable: a claim that is not checked is a claim that quietly stops being
true.
