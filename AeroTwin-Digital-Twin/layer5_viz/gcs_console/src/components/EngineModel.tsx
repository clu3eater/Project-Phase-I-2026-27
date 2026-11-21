/* The Rotax 915 iS, with the fault the twin has detected lit on the part.
 *
 * WHY THIS EXISTS AT ALL
 * ----------------------
 * Every other panel on this console reports a fault by NAME. "Misfire, 30%"
 * is a sentence a propulsion engineer reads; it is not where the part is, and
 * it is not what a commander decides on in ten seconds. This shows the fault
 * the detector named, on the component it belongs to, on the cylinder it
 * belongs to.
 *
 * WHAT IS OURS AND WHAT IS NOT
 * ----------------------------
 * The model, the 73-component registry, the fault-to-component matrix and the
 * three.js layer that applies them come from the ROTAX_915IS_FAULT_INTEGRATION
 * package and are used through its published contract
 * (digital_twin_visualization_api.md). Nothing here reasons about geometry.
 * This file does one job: turn what the twin has DETECTED into setFault and
 * clearFault calls, and turn a click back into a component id.
 *
 * WHAT IS SHOWN IS WHAT WAS DETECTED
 * ----------------------------------
 * The faults lit here come from `snap.twin.predicted.fault_probability` --
 * the network's output -- at the same threshold the rest of the console uses
 * to call a fault present. An injected fault the detector has NOT yet found is
 * not lit. The model shows the twin's belief, not the simulator's ground
 * truth, because the belief is the only version of it that means anything.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Snapshot } from "../lib/api";
import { Status, type Level } from "../ui/status";

/* Fault ids in the package's registry, keyed by the twin's own fault names.
 * Both lists are the problem statement's eight, so this is a spelling map and
 * not a translation -- if it ever needs a real translation, one of the two has
 * drifted from the PS and that is the bug to fix. */
const FAULT_ID: Record<string, string> = {
  misfire: "MISFIRE",
  injector_abnormal: "INJECTOR_ABNORMAL",
  cooling_degradation: "COOLING_DEGRADATION",
  lubrication_issue: "LUBRICATION_ISSUE",
  sensor_drift: "SENSOR_DRIFT",
  combustion_instability: "COMBUSTION_INSTABILITY",
  overheating_trend: "OVERHEATING_TREND",
  abnormal_vibration: "ABNORMAL_VIBRATION",
};

/* The score at which a fault is shown when the network's own calibrated
 * threshold for that class is not available. With it, each class is lit at
 * ITS threshold (tier3_report.json, published as fusion.fault_calibration):
 * the classes are called anywhere from 0.04 to 0.98, and a flat 0.30 lit
 * parts on a healthy engine whose scores merely hovered near it. The list on
 * the prognostics page uses the same thresholds, so the two cannot disagree. */
const SHOW_AT = 0.30;

/* AND THE POINT AT WHICH IT STOPS BEING SHOWN, WHICH IS LOWER.
 *
 * With one threshold, a probability sitting near it sets the fault, clears it,
 * and sets it again on consecutive ticks. Every clear starts a three-second
 * HIGHLIGHT_RECOVERING glow, so a part hovering at the boundary pulses between
 * "faulted" and "recovering" while nothing about the engine has changed. That
 * is alarm chatter, and MIL-STD-1472H 5.4.3.1 wants an annunciator to mean
 * something when it changes.
 *
 * A fault lights at its threshold and is only released below two thirds of
 * it. The band is the same idea as the persistence a Tier-1 rule already uses
 * before it fires. */
const CLEAR_FRACTION = 2 / 3;

/* THE MODEL MUST SPEAK THE CONSOLE'S SIX COLOURS, NOT ITS OWN SEVEN.
 *
 * The package ships a palette chosen to read well on the Rotax castings. Three
 * of its choices collide with what colour MEANS on this console
 * (theme/tokens.css, RTCA DO-257A "at least six coding colours" -- a rule that
 * only holds if there is one place to count them):
 *
 *   RECOVERING  #34C759 is green, and green here means NORMAL, IN TOLERANCE.
 *               A part glowing green because a fault just cleared reads as a
 *               part that is fine. Mapped to cyan, which is ADVISORY: recovery
 *               is information, not a condition.
 *   SUSPECT     #B57CFF is a seventh hue that carries meaning nowhere else on
 *               the console. The Readout already shows a suspect value in
 *               amber and distinguishes it with a TEXT TAG; the model
 *               distinguishes it from WARNING by pulse rate, which the package
 *               already specifies (0.5 Hz against 0.8 Hz).
 *   CONTEXT     a pale blue-grey. Greys are explicitly NOT coding colours
 *               here, which is right -- "related to the fault" is not a
 *               condition of the engine -- so it takes the physics-overlay
 *               grey that already means exactly that.
 *
 * WARNING and CRITICAL need no change: #FFB000 and #FF3B30 are already the
 * console's caution amber and warning red to within a shade.
 *
 * Applied to the registry as loaded rather than by forking the layer. The
 * colours live in fault_registry.json (componentRenderStates[].emissive) and
 * the layer reads them from there, so this is configuration -- the package
 * stays the package, with its contract and its 33/33 test intact.
 */
function tokenColour(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
  return v || fallback;
}

function repaintToConsolePalette(registry: any): any {
  const map: Record<string, [string, string]> = {
    HIGHLIGHT_CONTEXT: ["--phys", "#8a9bb0"],
    HIGHLIGHT_RECOVERING: ["--alert-advis", "#35c6e8"],
    HIGHLIGHT_INVALID: ["--ink-mute", "#63748a"],
    HIGHLIGHT_SUSPECT: ["--alert-caut", "#ffb302"],
    HIGHLIGHT_WARNING: ["--alert-caut", "#ffb302"],
    HIGHLIGHT_CRITICAL: ["--alert-warn", "#ff3b30"],
  };
  for (const s of registry.componentRenderStates ?? []) {
    const m = map[s.state];
    if (m) s.emissive = tokenColour(m[0], m[1]);
  }
  return registry;
}


/* WHERE THE PARTS ACTUALLY BELONG.
 *
 * The shipped model's "assembled" pose is not assembled. Nine parts sit off
 * the engine with clear air all around them: the air baffles a full 0.61 from
 * the nearest casting, the overboost valve 0.58, and the oil tank, fusebox,
 * ECU, intercooler, boost solenoid, ambient sensor and gearbox behind them.
 * At the default camera they read as debris floating beside the engine, which
 * is what anyone looking at this page noticed first.
 *
 * THEY ARE NOT SCATTERED AT RANDOM. Every one is displaced along ITS OWN
 * EXPLODE AXIS -- the direction that closes the gap and the direction the
 * EXPLODE clip throws that part are the same line, cos 0.87 to 1.00 across
 * all nine. The pose that ships is a PARTIALLY EXPLODED pose: the export kept
 * a residual offset on exactly the parts that travel furthest.
 *
 * So the correction is the one the model itself defines -- slide each part
 * back down its own explode axis until its geometry touches the engine. These
 * distances were solved offline against the GLB's 613,885 vertices, by binary
 * search on first contact at a 2.5 mm tolerance. They are applied to the rest
 * pose AND to every keyframe of both clips, because the clips carry absolute
 * positions: patch only the rest pose and the first frame of EXPLODE would
 * snap each part straight back out to where it floated.
 *
 * DONE AT LOAD, NOT IN THE ASSET, ON PURPOSE. The GLB, the registry and the
 * matrix come from the ROTAX_915IS_FAULT_INTEGRATION package under a published
 * contract with its own test suite. repaintToConsolePalette above already
 * adjusts that package as it is loaded rather than forking it; this follows
 * the same rule. No geometry, no name and no registry id changes -- only where
 * nine nodes sit, so selection, highlighting, explode and repack are untouched.
 */
const SEATED: Record<string, [number, number, number]> = {
  ROTAX_915IS_AIR_BAFFLES:                  [-0.63179,  0.07213, -0.09580],
  ROTAX_915IS_OVERBOOST_VALVE:              [ 0.12929,  0.07122, -0.59728],
  ROTAX_915IS_OIL_TANK:                     [ 0.36663,  0.07536, -0.14946],
  ROTAX_915IS_FUSEBOX:                      [ 0.35849,  0.05079, -0.08298],
  ROTAX_915IS_AMBIENT_AIR_SENSOR:           [ 0.13925,  0.09134, -0.25459],
  ROTAX_915IS_ECU:                          [ 0.11503,  0.07079, -0.23366],
  ROTAX_915IS_INTERCOOLER:                  [ 0.21376,  0.08076, -0.19031],
  ROTAX_915IS_BOOST_CONTROL_SOLENOID_VALVE: [ 0.21376,  0.08076, -0.19031],
  ROTAX_915IS_GEARBOX:                      [-0.11443,  0.00000,  0.00000],
};

/** Seat the floating parts, in the rest pose and in both clips. */
function seatFloatingParts(gltf: any): number {
  let moved = 0;
  gltf.scene.traverse((o: any) => {
    const d = SEATED[o.name];
    if (!d) return;
    o.position.set(o.position.x + d[0], o.position.y + d[1], o.position.z + d[2]);
    moved++;
  });
  for (const clip of gltf.animations ?? []) {
    for (const track of clip.tracks ?? []) {
      const dot = String(track.name).lastIndexOf(".");
      if (dot < 0 || track.name.slice(dot + 1) !== "position") continue;
      const d = SEATED[track.name.slice(0, dot)];
      if (!d) continue;
      for (let i = 0; i + 2 < track.values.length; i += 3) {
        track.values[i] += d[0];
        track.values[i + 1] += d[1];
        track.values[i + 2] += d[2];
      }
    }
  }
  return moved;
}

const MODEL_URL = "/engine3d/rotax915is.glb";

/** Why the model would not load, said in terms someone can act on.
 *
 * ONE FAILURE IS WORTH CATCHING BY NAME. The repository keeps the 19 MB model
 * in Git LFS, so a clone made without LFS -- or a zip export of one -- leaves
 * a 133-byte TEXT pointer where the binary should be:
 *
 *     version https://git-lfs.github.com/spec/v1
 *     oid sha256:66f41e76...
 *     size 19297256
 *
 * GLTFLoader sees no glTF magic, falls back to parsing it as .gltf JSON, and
 * reports `Unexpected token 'v', "version ht"... is not valid JSON` -- which
 * is true, and tells an operator nothing about what to do. The file is asked
 * for its length first (a HEAD, so a healthy 19 MB model is never downloaded
 * twice) and only a suspiciously short one is read.
 */
async function whyNotLoaded(url: string, err: unknown): Promise<string> {
  try {
    const head = await fetch(url, { method: "HEAD" });
    const len = Number(head.headers.get("content-length") ?? 0);
    if (len > 0 && len < 1000) {
      const text = (await (await fetch(url)).text()).slice(0, 64);
      if (text.startsWith("version https://git-lfs")) {
        return "the model file is a Git LFS pointer, not the model — fetch it "
             + "with \"git lfs pull\", or copy rotax915is.glb into public/engine3d/";
      }
    }
  } catch { /* the network answer is a bonus; fall back to what threw */ }
  return String((err as any)?.message ?? err);
}

export function EngineModel({ snap, onSelect, focusPart }: {
  snap: Snapshot;
  onSelect?: (componentId: string) => void;
  /** A component another view has asked to see. `n` is a nonce, so asking for
   *  the same part twice still arrives as a fresh request. */
  focusPart?: { componentId: string; n: number } | null;
}) {
  const mount = useRef<HTMLDivElement>(null);
  const layer = useRef<any>(null);
  /* ASK FOR A FRAME.
   *
   * The loop below paints only when something has changed, so anything that
   * changes the picture from OUTSIDE the loop has to say so. Highlighting is
   * exactly that: setFault and clearFocus rewrite materials and return, and
   * with nothing else moving the new colours would sit in GPU memory unpainted
   * until the operator happened to nudge the camera. Wired to invalidate once
   * the renderer exists; a no-op before that, when there is nothing to paint. */
  const paint = useRef<() => void>(() => {});
  /* PUT THE WHOLE ENGINE BACK IN FRAME.
   *
   * Clicking a part flies the camera down onto it, which is the right hint --
   * but CLEAR FOCUS only used to drop the ghosting, so it left the operator
   * still nose-down on a fuel rail with no way back except orbiting out by
   * hand. Clearing a focus now clears the camera too. It pulls back along
   * whatever direction the operator is currently looking from, so the gesture
   * restores the framing without also confiscating the angle they chose. */
  const home = useRef<() => void>(() => {});
  const mixer = useRef<any>(null);
  // True while EXPLODE or REPACK is playing, so the camera re-fits only then.
  const moving = useRef(false);
  const clips = useRef<Record<string, any>>({});
  const registry = useRef<any[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [detail, setDetail] = useState("");
  const [exploded, setExploded] = useState(false);
  const [part, setPart] = useState<any>(null);
  /* WHAT IS LIT, NOT JUST HOW MANY.
   *
   * The camera flies to the worst fault on its own, and until now that was
   * the only way to reach one: a second fault was lit somewhere on the engine
   * with nothing to say so and no way to get to it. These drive the list
   * under the buttons -- worst first, click to fly there -- which doubles as
   * the legend for the colours, since nothing else on the panel explains that
   * a dim grey part is RELATED to the fault rather than also broken. */
  const [litFaults, setLitFaults] = useState<
    { id: string; name: string; p: number; level: Level }[]>([]);
  const [focused, setFocused] = useState<string | null>(null);
  /* Whether any part that is LIT is one the registry marks as internal. The
   * explode prompt used to appear whenever anything was lit, which is not the
   * same claim: cooling degradation lights four cylinder heads and a water
   * pump, and the heads are in plain sight. Nine of the 73 components are
   * flagged internal, and only those justify telling an operator they cannot
   * see what the console has just lit. */
  const [hidden, setHidden] = useState(0);
  /* displayName per faultId, straight from the package registry. */
  const faultNames = useRef<Record<string, string>>({});

  // --- build the scene once -------------------------------------------------
  useEffect(() => {
    let disposed = false;
    let frame = 0;
    let cleanup: (() => void) | null = null;

    (async () => {
      try {
        const THREE = await import("three");
        const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
        const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
        const { RoomEnvironment } = await import("three/examples/jsm/environments/RoomEnvironment.js");
        const { DigitalTwinFaultLayer } = await import("../lib/faultLayer.js");

        const [rawRegistry, componentRegistry, matrix] = await Promise.all(
          ["fault_registry", "component_registry", "fault_component_matrix"].map((f) =>
            fetch(`/engine3d/${f}.json`).then((r) => r.json())));
        const faultRegistry = repaintToConsolePalette(rawRegistry);
        faultNames.current = Object.fromEntries(
          (faultRegistry.faults ?? []).map((f: any) => [f.faultId, f.displayName ?? f.faultId]));

        // NO DRACO, DELIBERATELY.
        //
        // The Draco build is 5.7 MB against 19.3 MB, which is worth having --
        // but its decoder starts a worker from a blob: URL, and this console's
        // Content-Security-Policy refuses that, correctly. The choices were to
        // add `worker-src blob:` to the CSP of a defence ground station so a
        // display feature could start a worker from a URL the policy cannot
        // vet, or to run the decoder on the main thread, which three 0.160
        // does not actually support (setWorkerLimit(0) fails inside the
        // loader: "Cannot read properties of undefined (reading '_taskCosts')").
        //
        // So the uncompressed model ships instead. 13 MB more over a local
        // link, once, against a permanent hole in the policy: an easy trade.
        const loader = new GLTFLoader();
        const gltf = await loader.loadAsync(MODEL_URL).catch(async (e) => {
          throw new Error(await whyNotLoaded(MODEL_URL, e));
        });
        if (disposed || !mount.current) return;

        const el = mount.current;
        const scene = new THREE.Scene();
        seatFloatingParts(gltf);

        // Set by anything that changes the picture. The loop at the bottom of
        // this effect paints only when it is true -- see the note there.
        let needsRender = true;
        const invalidate = () => { needsRender = true; };
        paint.current = invalidate;
        // Set the moment the operator touches the camera. Until then the view
        // is ours to re-frame; afterwards it is theirs and we leave it alone.
        let userMoved = false;

        // ANTIALIASING ONLY WHERE IT IS NOT ALREADY PAID FOR. At a device
        // pixel ratio of 1.5 or more the buffer already supersamples the
        // panel, and MSAA on top of that spends bandwidth on an edge the
        // display cannot resolve.
        const renderer = new THREE.WebGLRenderer({
          antialias: devicePixelRatio < 1.5,
          powerPreference: "high-performance",
        });
        const DPR_MAX = Math.min(devicePixelRatio, 2);
        let dpr = DPR_MAX;
        renderer.setPixelRatio(dpr);
        renderer.setSize(el.clientWidth, el.clientHeight);
        el.appendChild(renderer.domElement);

        // THE PANEL FOLLOWS THE CONSOLE AMBIENT, AND KEEPS FOLLOWING IT.
        // Read once at mount, the backdrop stayed at whichever ambient was set
        // when the Engine page first opened: switch to day and a night
        // backdrop sat inside a light console for the rest of the session.
        // A GROUND CUE, NOT A DECORATION.
        //
        // On a flat fill the engine reads as cut out and floating in a void.
        // The obvious fixes are worse than the problem: a gridded floor puts
        // faint grey texture directly behind HIGHLIGHT_CONTEXT, which IS a
        // faint grey glow and is the quietest thing the view has to say; and a
        // painted contact shadow is a lie that breaks the moment the operator
        // orbits underneath, which OrbitControls allows.
        //
        // So the panel darkens slightly towards the bottom and nowhere else.
        // The top half stays exactly --bg-panel, so the canvas still meets the
        // card it sits in with no visible seam, and the only thing added is a
        // sense of down. It is correct from every angle because there is no
        // geometry in it to be wrong.
        const paintBackground = () => {
          const base = new THREE.Color(
            getComputedStyle(document.documentElement)
              .getPropertyValue("--bg-panel").trim() || "#0b1018");
          const c = document.createElement("canvas");
          c.width = 2; c.height = 128;
          const g2 = c.getContext("2d");
          if (!g2) { scene.background = base; invalidate(); return; }
          const grad = g2.createLinearGradient(0, 0, 0, 128);
          grad.addColorStop(0, "#" + base.getHexString());
          grad.addColorStop(0.5, "#" + base.getHexString());
          grad.addColorStop(1, "#" + base.clone().multiplyScalar(0.88).getHexString());
          g2.fillStyle = grad;
          g2.fillRect(0, 0, 2, 128);
          const tex = new THREE.CanvasTexture(c);
          tex.colorSpace = THREE.SRGBColorSpace;
          (scene.background as any)?.dispose?.();
          scene.background = tex;
          invalidate();
        };
        paintBackground();
        const ambientWatch = new MutationObserver(paintBackground);
        ambientWatch.observe(document.documentElement,
          { attributes: true, attributeFilter: ["data-ambient", "class"] });

        // EVEN LIGHT, BUT NOT FLAT PAINT.
        //
        // The rule here has always been that a console is not a showroom:
        // dramatic shading hides which part is lit, and the lit part is the
        // entire reason the model exists. That still holds. What the old rig
        // got wrong was not the evenness, it was the LEVEL -- a hemisphere at
        // 2.2 and a key at 1.1, on r160 lighting that is already physically
        // scaled, drove the pale castings past white while leaving the dark
        // ones at black. On the day ambient the engine read as a silhouette
        // with blown edges, which is the washed-out look that was reported.
        //
        // A small procedural room supplies the ambient instead. It is built
        // once, costs one cube lookup per fragment, and gives the aluminium
        // and the plastic something to reflect -- which is what makes a
        // casting read as a casting instead of a grey blob.
        //
        // NO TONE MAPPING, DELIBERATELY. ACES or Reinhard would roll the
        // highlights off nicely and would shift every fault colour on the way:
        // #FF3B30 warning red does not survive a filmic curve. The six coding
        // colours in theme/tokens.css have to come out of the renderer as they
        // went in, so exposure is controlled by the lights and the pipeline
        // stays linear -> sRGB with nothing in between.
        const pmrem = new THREE.PMREMGenerator(renderer);
        const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
        scene.environment = envRT.texture;
        pmrem.dispose();

        scene.add(new THREE.HemisphereLight(0xffffff, 0x2b3038, 0.5));
        const key = new THREE.DirectionalLight(0xffffff, 1.25);
        key.position.set(2.4, 3.2, 2.0);
        scene.add(key);
        // Enough from behind that the far side is readable, not lit.
        const fill = new THREE.DirectionalLight(0xffffff, 0.3);
        fill.position.set(-2.0, 0.7, -1.7);
        scene.add(fill);

        // The room lights the casting; it must not wash it out. Set before the
        // fault layer is built so its material variants inherit the value.
        gltf.scene.traverse((o: any) => {
          const mats = Array.isArray(o.material) ? o.material
                     : o.material ? [o.material] : [];
          for (const m of mats) if ("envMapIntensity" in m) m.envMapIntensity = 0.5;
        });
        scene.add(gltf.scene);

        const camera = new THREE.PerspectiveCamera(
          38, el.clientWidth / Math.max(el.clientHeight, 1), 0.05, 100);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;

        // FIT THE WHOLE ENGINE, MEASURED AGAINST BOTH FIELDS OF VIEW.
        //
        // The sphere radius is the distance to the FURTHEST corner, so for a
        // wide flat assembly it wildly overstates what has to fit and the
        // engine comes back as a thumbnail in an empty panel. Fitting the box
        // height and width separately against the vertical and horizontal
        // fields of view is the honest measure of what is on screen, and it is
        // the same measure used while a clip is playing.
        /* A THIN SAMPLE OF THE REAL SURFACE, FOR FRAMING.
         *
         * Even a per-mesh bounding box overshoots -- a pipe running diagonally
         * puts its box corners out in empty air, and framing against those
         * leaves the engine smaller than the panel it is in. The only honest
         * silhouette is the geometry itself, so the fit projects actual
         * vertices. Every mesh contributes at most ~48 of them, evenly spaced
         * through its buffer: about 3,000 points for the whole engine, which
         * is a fraction of a millisecond and only runs when the view is being
         * framed, never per frame while orbiting. */
        const silhouette: any[] = [];
        gltf.scene.traverse((o: any) => {
          const pos = o.isMesh && o.geometry?.attributes?.position;
          if (pos && pos.count) {
            silhouette.push({ mesh: o, geometry: o.geometry,
                              step: Math.max(1, Math.floor(pos.count / 48)) });
          }
        });

        const FIT_DIR = new THREE.Vector3(1, 0.85, 0.9).normalize();
        const _right = new THREE.Vector3(), _up = new THREE.Vector3();
        const _fwd = new THREE.Vector3(), _corner = new THREE.Vector3();
        const WORLD_UP = new THREE.Vector3(0, 1, 0);
        const fitBox = (margin: number, lerp: number) => {
          const b = new THREE.Box3().setFromObject(gltf.scene);
          const c = b.getCenter(new THREE.Vector3());
          const dir = lerp >= 1 ? FIT_DIR.clone()
                    : camera.position.clone().sub(controls.target).normalize();

          // MEASURE THE SILHOUETTE, NOT THE BOX SIDES. What has to fit the
          // panel is the assembly as the CAMERA sees it, and from an oblique
          // angle that is not the width of any one face -- an engine 1.09
          // wide and 0.90 deep presents 1.41 across a 45-degree view. Fitting
          // max(x, z) instead left the engine filling a third of the panel
          // height with empty space above and below it. The eight corners are
          // projected onto the camera's own right and up axes and fitted
          // against the two fields of view separately.
          _fwd.copy(dir).negate();
          _right.crossVectors(WORLD_UP, _fwd).normalize();
          _up.crossVectors(_fwd, _right).normalize();
          let hx = 0, hy = 0;
          for (let i = 0; i < 8; i++) {
            _corner.set(i & 1 ? b.max.x : b.min.x,
                        i & 2 ? b.max.y : b.min.y,
                        i & 4 ? b.max.z : b.min.z).sub(c);
            hx = Math.max(hx, Math.abs(_corner.dot(_right)));
            hy = Math.max(hy, Math.abs(_corner.dot(_up)));
          }
          const half = Math.tan((camera.fov * Math.PI) / 360);
          const need = Math.max(hy / half,
                                hx / (half * Math.max(camera.aspect, 0.2)),
                                0.35) * margin;

          const want = c.clone().add(dir.clone().multiplyScalar(need));
          if (lerp < 1) {
            controls.target.lerp(c, lerp);
            camera.position.lerp(want, lerp);
            return;
          }
          controls.target.copy(c);
          camera.position.copy(want);

          // NOW TIGHTEN IT AGAINST THE GEOMETRY, BECAUSE THE BOX LIES.
          //
          // Everything above fits the scene's single bounding box, and for an
          // irregular assembly seen from an oblique angle that box is a bad
          // stand-in for the silhouette. Its corners stick out into empty air
          // -- and the near ones are closer to the camera than the engine is,
          // so perspective throws them wider still. Measured: the fit put the
          // box's extreme corner at 1.087 of the frame, apparently a snug
          // crop, while the engine itself covered 60 % of the width and 41 %
          // of the height and sat marooned in the middle of the panel.
          //
          // So the box only gets the camera roughly right. The distance is
          // then corrected against where the geometry ACTUALLY lands: every
          // mesh's own bounding box, projected through the real camera, which
          // hugs the shape far more closely than one box around all of it.
          // Extent scales as about 1/distance near the target, so scaling the
          // distance by the measured overshoot converges in two or three
          // passes; it stops early once it is within a percent.
          gltf.scene.updateMatrixWorld(true);
          let dist = need;
          for (let pass = 0; pass < 4; pass++) {
            camera.updateMatrixWorld(true);
            camera.updateProjectionMatrix();
            let nx = 0, ny = 0;
            for (const m of silhouette) {
              const pos = m.geometry.attributes.position;
              for (let i = 0; i < pos.count; i += m.step) {
                _corner.fromBufferAttribute(pos, i)
                  .applyMatrix4(m.mesh.matrixWorld).project(camera);
                nx = Math.max(nx, Math.abs(_corner.x));
                ny = Math.max(ny, Math.abs(_corner.y));
              }
            }
            const over = Math.max(nx, ny) * margin;
            if (!isFinite(over) || over <= 0 || Math.abs(over - 1) < 0.01) break;
            dist = Math.max(dist * over, 0.35);
            camera.position.copy(c).add(dir.clone().multiplyScalar(dist));
          }
        };
        fitBox(1.06, 1);
        controls.update();

        layer.current = new DigitalTwinFaultLayer({
          root: gltf.scene, camera, controls,
          faultRegistry, componentRegistry, matrix,
        });
        registry.current = componentRegistry.components ?? componentRegistry ?? [];

        /* WHICH BARREL IS CYLINDER 3?
         *
         * The Cylinders panel sits immediately beside this view listing CYL 1
         * to 4, and the detector names faults per cylinder -- "misfire,
         * cylinder 3", and above magnitude 0.5 its coil partner as well. The
         * model lit a barrel and there was no way to tell WHICH barrel, so the
         * two halves of the same fact sat side by side unable to refer to each
         * other. The registry already maps ROTAX_915IS_CYLINDER_01..04 onto
         * cylinders 1..4, so this is a label, not a modelling job.
         *
         * Drawn as DOM rather than sprites or 3D text: the 16 px type floor
         * covers glyphs too, and real CSS type in --font-num stays crisp at any
         * zoom, takes its colours from the tokens like everything else, and
         * costs one transform write per label on frames that already moved.
         */
        const marks: { node: any; centre: any; el: HTMLElement }[] = [];
        const markLayer = document.createElement("div");
        markLayer.style.cssText =
          "position:absolute;inset:0;pointer-events:none;overflow:hidden";
        el.appendChild(markLayer);
        gltf.scene.traverse((o: any) => {
          const m = /^ROTAX_915IS_CYLINDER_0([1-4])$/.exec(o.name || "");
          if (!m) return;
          const centre = new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3());
          const span = document.createElement("span");
          span.textContent = m[1];
          span.setAttribute("aria-hidden", "true");
          span.style.cssText =
            "position:absolute;transform:translate(-50%,-50%);" +
            "font-family:var(--font-num);font-size:16px;line-height:1;" +
            "color:var(--ink-dim);background:var(--bg-panel);" +
            "border:1px solid var(--line);border-radius:var(--radius);" +
            "padding:1px 7px;opacity:0";
          markLayer.appendChild(span);
          marks.push({ node: o, centre: o.worldToLocal(centre), el: span });
        });

        const _mp = new THREE.Vector3(), _mc = new THREE.Vector3();
        const _ma = new THREE.Vector3(), _mb = new THREE.Vector3();
        const placeMarks = () => {
          if (!marks.length) return;
          const w = el.clientWidth, h = el.clientHeight;
          new THREE.Box3().setFromObject(gltf.scene).getCenter(_mc);
          for (const mk of marks) {
            _mp.copy(mk.centre).applyMatrix4(mk.node.matrixWorld);
            // Hide the bank turned away from the camera: its number would
            // float over the parts in front of it and point at nothing.
            _ma.copy(_mp).sub(_mc).normalize();
            _mb.copy(camera.position).sub(_mp).normalize();
            const facing = _ma.dot(_mb);
            _mp.project(camera);
            const shown = facing > -0.15 && _mp.z < 1;
            mk.el.style.opacity = shown ? "1" : "0";
            if (!shown) continue;
            mk.el.style.left = ((_mp.x * 0.5 + 0.5) * w).toFixed(1) + "px";
            mk.el.style.top = ((-_mp.y * 0.5 + 0.5) * h).toFixed(1) + "px";
          }
        };

        // EXPLODE AND REPACK, WHICH THE MODEL HAS SHIPPED ALL ALONG.
        //
        // Most of the parts that fail are INSIDE the engine. Lighting a
        // conrod red inside an assembled crankcase is a red glow nobody can
        // see, which is worse than not lighting it: the operator is told
        // something is wrong and shown nothing. The GLB carries EXPLODE and
        // REPACK clips -- 12 s, 72 tracks -- that draw the assembly apart so
        // an internal part is actually visible, and fault states are material
        // states, so a highlight survives both clips.
        mixer.current = new THREE.AnimationMixer(gltf.scene);
        for (const clip of gltf.animations ?? []) {
          const action = mixer.current.clipAction(clip);
          action.setLoop(THREE.LoopOnce, 1);
          action.clampWhenFinished = true;     // stay apart, do not spring back
          clips.current[clip.name.toUpperCase()] = action;
        }

        // THE DEFAULT VIEW IS THE WHOLE ENGINE, WHICH IT COULD NOT BE BEFORE.
        //
        // This used to call focusComponent("ROTAX_915IS_CRANKCASE", 2.6) --
        // the package's own framing -- because a whole-model fit was useless
        // while nine parts floated up to 0.6 away: the fit had to take them in
        // and the engine ended up a thumbnail ringed by empty panel. The
        // crankcase framing traded that for the opposite fault, parking the
        // camera close enough that the panel showed a barrel and half a
        // generator cover with no way to tell what you were looking at.
        //
        // With those nine seated the bounding radius falls from 1.32 to 0.78
        // and the honest fit is also the good one: fitBox above frames the
        // engine, entire, with a 15 % margin. focusComponent still does what
        // it is good at -- flying to ONE part when the operator clicks it, or
        // when a fault lights.

        // RE-FRAME UNTIL THE OPERATOR TAKES THE CAMERA.
        //
        // The first fit runs while the effect is still setting up, and React
        // has not necessarily laid the panel out yet: clientWidth can still be
        // 0, camera.aspect falls back to the 0.2 floor, and the fit solves for
        // a viewport four times narrower than the real one -- which parks the
        // camera far too far back and leaves the engine a small object in a
        // large panel. The ResizeObserver then corrected the aspect without
        // ever re-fitting, so the bad distance stuck for the session.
        //
        // Any resize re-frames, until the operator first touches the camera.
        // That also keeps the engine framed when the window is resized or the
        // alert rail appears, which it did not do before.
        const onResize = () => {
          if (!el.clientWidth) return;
          camera.aspect = el.clientWidth / Math.max(el.clientHeight, 1);
          camera.updateProjectionMatrix();
          renderer.setSize(el.clientWidth, el.clientHeight);
          if (!userMoved && !moving.current) fitBox(1.06, 1);
          invalidate();
        };
        const ro = new ResizeObserver(onResize);
        ro.observe(el);

        const onClick = (ev: MouseEvent) => {
          const r = renderer.domElement.getBoundingClientRect();
          const id = layer.current?.selectAt(
            ((ev.clientX - r.left) / r.width) * 2 - 1,
            -((ev.clientY - r.top) / r.height) * 2 + 1);
          invalidate();
          if (!id) { setPart(null); return; }
          // The registry entry, not just the name. An operator who clicks a
          // part is asking what it IS -- which subsystem, which cylinder, what
          // it can fail as -- and all of that is already in the package's
          // component registry.
          setPart(registry.current.find((c: any) =>
            (c.componentId ?? c.id ?? c.registry_id) === id) ?? { componentId: id });
          layer.current?.focusComponent(id, { ghost: true });
          if (onSelect) onSelect(id);
        };
        renderer.domElement.addEventListener("click", onClick);

        // PAINT WHEN SOMETHING CHANGES, NOT TWENTY TIMES A SECOND.
        //
        // The old loop painted a fixed 20 fps for as long as the page was
        // open. The instinct behind it was right and still is: a 3D view has
        // no business competing with the data path, and it was measured here
        // on a host with no GPU where the software rasteriser drove the twin's
        // own tick p95 to 12 SECONDS. But a fixed cap is the wrong instrument
        // for it, and it is wrong in both directions at once.
        //
        // It spends a whole frame every 50 ms redrawing a picture nobody is
        // touching -- 212 draw calls and 539k triangles, forever, on a
        // monitoring console that sits still almost all of the time. And it
        // CAPS the one moment that has to feel immediate: dragging the model.
        // Measured on an RTX 3090 the panel orbited at 18.1 fps, and it would
        // have orbited at 18.1 fps on any machine ever built, which is exactly
        // the "slow on every device" that was reported.
        //
        // So the loop is driven by change instead:
        //
        //   idle             nothing is painted at all. No draw calls.
        //   orbit/zoom/pan   every frame the display will take. This is the
        //                    one interaction that must not feel cheap.
        //   pulse / explode  30 fps, ample for a 0.8 Hz annunciator and a
        //                    12 s assembly move.
        //   tab hidden       nothing, as before.
        //
        // Total GPU work goes DOWN against the old cap, because the idle case
        // is the common one -- so the data path still wins, which was the
        // whole point of the cap.
        let dragging = false;
        controls.addEventListener("change", invalidate);
        controls.addEventListener("start", () => { dragging = true; userMoved = true; });
        controls.addEventListener("end", () => { dragging = false; invalidate(); });
        // The wheel zooms without a start/end pair, so it asks for itself.
        const onWheel = () => { userMoved = true; invalidate(); };
        renderer.domElement.addEventListener("wheel", onWheel, { passive: true });

        /** Is anything still moving of its own accord? */
        const animating = () => {
          const l = layer.current;
          return moving.current
            || !!(l && ((l.pulsing?.size ?? 0) > 0 || l.focusTween
                        || (l.recovering?.size ?? 0) > 0));
        };

        // ADAPTIVE RESOLUTION, FROM WHAT THE MACHINE ACTUALLY DELIVERS.
        //
        // devicePixelRatio alone is a poor predictor -- a 2x panel in front of
        // an integrated GPU and a 2x panel in front of a discrete one want
        // different buffers. The renderer starts at the display's ratio and
        // steps the buffer down only when the frames it is ALREADY delivering,
        // drawing continuously, fall behind budget; it steps back up when they
        // do not. A thin laptop settles low, a workstation stays sharp, and
        // neither had to be recognised by name.
        const DPR_MIN = 0.75;
        const SLOW_MS = 20;            // a run of frames below ~50 fps
        const FAST_MS = 12;
        let run = 0, runSum = 0;
        const setDpr = (v: number) => {
          v = Math.max(DPR_MIN, Math.min(DPR_MAX, v));
          if (Math.abs(v - dpr) < 0.05) return;
          dpr = v;
          renderer.setPixelRatio(dpr);
          renderer.setSize(el.clientWidth, el.clientHeight);
          invalidate();
        };

        // Set to a deadline by CLEAR FOCUS; the loop eases the camera out to
        // the full engine until it passes.
        let homingUntil = 0;
        home.current = () => { homingUntil = performance.now() + 650; invalidate(); };

        const ANIM_GAP_MS = 1000 / 30;
        let last = performance.now();
        let paintedLast = false;
        const tick = () => {
          frame = requestAnimationFrame(tick);
          const now = performance.now();
          const gap = now - last;
          if (document.hidden) { last = now; paintedLast = false; return; }

          const anim = animating() || homingUntil > 0;
          // Throttle self-driven motion, never the hand on the model.
          if (anim && !dragging && gap < ANIM_GAP_MS) return;
          last = now;

          if (anim) {
            const dt = Math.min(gap / 1000, 0.1);
            layer.current?.update(dt);
            mixer.current?.update(dt);
            needsRender = true;
          }
          if (homingUntil) {
            fitBox(1.06, 0.18);
            needsRender = true;
            if (now > homingUntil) homingUntil = 0;
          }
          if (controls.update()) needsRender = true;

          // FRAME THE LIVE BOUNDS WHILE THE ASSEMBLY IS MOVING.
          //
          // The package says it plainly: "components move during
          // EXPLODE/REPACK", so a camera placed before the clip is wrong by
          // the end of it. Measured on a capture: the exploded engine ran off
          // all four edges of the panel, because the view had been framed
          // twelve seconds earlier.
          //
          // Re-fitted every frame while a clip runs, and never after -- once
          // the animation settles the operator owns the camera, and a view
          // that keeps correcting itself under the hand is worse than one that
          // is slightly wrong.
          if (moving.current) { fitBox(1.12, 0.12); needsRender = true; }

          if (!needsRender) { paintedLast = false; run = 0; runSum = 0; return; }
          needsRender = false;
          renderer.render(scene, camera);
          placeMarks();

          // Only consecutive painted frames say anything about the frame rate;
          // the gap after an idle stretch is not a slow frame.
          if (paintedLast) {
            run++; runSum += gap;
            if (run >= 20) {
              const mean = runSum / run;
              run = 0; runSum = 0;
              if (mean > SLOW_MS) setDpr(dpr - 0.25);
              else if (mean < FAST_MS) setDpr(dpr + 0.25);
            }
          } else { run = 0; runSum = 0; }
          paintedLast = true;
        };
        tick();
        setStatus("ready");

        cleanup = () => {
          cancelAnimationFrame(frame);
          ro.disconnect();
          ambientWatch.disconnect();
          markLayer.remove();
          renderer.domElement.removeEventListener("click", onClick);
          renderer.domElement.removeEventListener("wheel", onWheel);
          controls.dispose();
          layer.current?.dispose();
          envRT.dispose();
          renderer.dispose();
          if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement);
        };
      } catch (err: any) {
        // Said out loud, not swallowed. A blank rectangle where the engine
        // should be is the kind of thing that gets discovered on stage.
        if (!disposed) { setStatus("failed"); setDetail(String(err?.message ?? err)); }
      }
    })();

    return () => { disposed = true; cleanup?.(); };
  }, []);

  // --- drive it from what the twin has detected -----------------------------
  const lit = useRef<Set<string>>(new Set());
  const lastSig = useRef("");
  useEffect(() => {
    const l = layer.current;
    if (!l || status !== "ready") return;
    const probs: Record<string, number> = snap.twin?.predicted?.fault_probability ?? {};
    const cal: Record<string, { threshold: number }> =
      (snap.fusion as any)?.fault_calibration ?? {};
    const want = new Map<string, number>();
    for (const [name, p] of Object.entries(probs)) {
      const id = FAULT_ID[name];
      if (!id) continue;
      const at = cal[name]?.threshold ?? SHOW_AT;
      // Already lit stays lit until it falls through the release band.
      if (p >= at || (lit.current.has(id) && p >= at * CLEAR_FRACTION)) want.set(id, p);
    }
    // NOTHING TO DO WHEN NOTHING HAS CHANGED.
    //
    // This effect runs on every snapshot, four a second. It used to re-apply
    // every active fault on each one -- rewriting materials the layer had
    // already set, rebuilding its variants, and (once the renderer stopped
    // painting on a timer) asking for a fresh frame every tick. A completely
    // static engine was costing 4 fps of GPU and a layer flush per tick for a
    // picture that had not changed. The wanted state is hashed instead, to the
    // nearest 1 % of magnitude, and a tick that matches the last one returns
    // before touching anything.
    const sig = [...want.entries()]
      .map(([id, p]) => id + ":" + p.toFixed(2)).sort().join("|");
    if (sig === lastSig.current) return;
    lastSig.current = sig;

    for (const [id, p] of want) {
      // RED above 0.7, amber below -- the two steps the alert engine uses, so
      // the model never shows a level the alert list disagrees with.
      try {
        l.setFault({ faultId: id, magnitude: p, alertLevel: p >= 0.7 ? "RED" : "ORANGE" });
      } catch { /* an id the registry does not carry is not lit, and not fatal */ }
    }
    for (const id of lit.current) {
      if (!want.has(id)) { try { l.clearFault(id); } catch { /* already gone */ } }
    }

    // A NEWLY LIT FAULT DRAWS THE ENGINE APART AND BRINGS THE CAMERA TO IT.
    //
    // Only on the transition, not on every tick: an assembly that re-explodes
    // twice a second is unreadable, and a camera that keeps flying home is
    // worse than one that never moves.
    const fresh = [...want.keys()].filter((id) => !lit.current.has(id));
    if (fresh.length) {
      const worst = fresh.reduce((a, b) =>
        (want.get(a) ?? 0) >= (want.get(b) ?? 0) ? a : b);
      try {
        /* THE ENGINE NO LONGER TAKES ITSELF APART.
         *
         * A newly lit fault used to call explode(true), so the assembly flew
         * apart on its own whenever the detector crossed its threshold -- and
         * flew back together when it fell below it again. Around the threshold
         * that is an engine repeatedly dismantling and reassembling itself
         * while nobody has touched anything, which is both unreadable and
         * alarming for a reason that has nothing to do with the engine.
         *
         * It also violates s8.1b, which forbids decorative animation, and
         * s6.2b: "Panels SHALL NOT resize, reorder or animate in response to
         * data."
         *
         * The camera still moves to the part that is lit -- that is a HINT,
         * cheap and reversible -- and EXPLODE VIEW is one click away with a
         * prompt beside it when the lit part is one the operator cannot see
         * from outside. Taking the engine apart stays the operator's decision.
         */
        // NO GHOSTING HERE, and that was tried the other way first.
        //
        // focusFault(..., {ghost: true}) drops everything not involved to 12 %
        // opacity. On a fault involving a handful of parts that is almost the
        // whole engine, and the capture showed exactly that: a washed-out
        // translucent shape in which the lit part was no easier to find than
        // before. The explode view is what makes an internal part visible; the
        // ghosting was solving a problem the explode had already solved, and
        // costing the operator every landmark on the engine to do it.
        //
        // Ghosting stays for the deliberate act -- clicking one part to study
        // it -- where hiding everything else is the point.
        l.focusFault(worst, { ghost: false });
        setFocused(worst);
      } catch { /* the camera hint is optional; the highlight is not */ }
    }
    lit.current = new Set(want.keys());
    setLitFaults([...want.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id, mag]) => ({
        id, p: mag,
        name: faultNames.current[id]
          ?? id.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()),
        // The same two steps the alert engine uses, so the list can never show
        // a level the alert rail disagrees with.
        level: (mag >= 0.7 ? "warning" : "caution") as Level,
      })));
    if (!want.size) setFocused(null);

    // Count the lit parts the operator genuinely cannot see from outside.
    const litParts = new Set<string>();
    for (const pl of l.activeFaults?.values?.() ?? []) {
      for (const cid of pl.directComponents ?? []) litParts.add(cid);
    }
    setHidden([...litParts].filter((cid) => registry.current.some((c: any) =>
      (c.componentId ?? c.id ?? c.registry_id) === cid && c.internal)).length);
    paint.current();
  }, [snap, status]);

  /** Fly to one of the lit faults. The camera goes on its own to the worst
   *  when it first lights; this is how the operator reaches the others. */
  const showFault = useCallback((id: string) => {
    try { layer.current?.focusFault(id, { ghost: false }); } catch { /* not in the registry */ }
    setFocused(id);
    paint.current();
  }, []);

  /* A PART NAMED SOMEWHERE ELSE, SHOWN HERE.
   *
   * The Health page can point at a cylinder from its balance figure, but the
   * model is on this view, so the request arrives through the shell. Keyed on
   * the nonce rather than the id: asking for the same cylinder twice is two
   * requests, and keying on the id alone would silently ignore the second.
   *
   * Deliberately the SAME three steps a click on the model itself performs --
   * select, fly to it, ghost the rest -- so a part reached from the Health
   * page and a part reached by clicking it end in the same state. */
  useEffect(() => {
    const id = focusPart?.componentId;
    const l = layer.current;
    if (!id || !l || status !== "ready") return;
    try {
      setPart(registry.current.find((c: any) =>
        (c.componentId ?? c.id ?? c.registry_id) === id) ?? { componentId: id });
      l.focusComponent(id, { ghost: true });
      onSelect?.(id);
      paint.current();
    } catch { /* an id this registry does not carry is not fatal */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPart?.n, status]);

  /** Draw the assembly apart, or put it back. */
  const explode = useCallback((out: boolean) => {
    const a = clips.current[out ? "EXPLODE" : "REPACK"];
    const other = clips.current[out ? "REPACK" : "EXPLODE"];
    if (!a) return;
    other?.stop();
    a.reset();
    a.play();
    setExploded(out);
    paint.current();
    // The clips are 12 s; a little longer so the last frame is framed too.
    moving.current = true;
    window.setTimeout(() => { moving.current = false; }, 12600);
  }, []);

  const btn = {
    padding: "5px 12px", fontSize: 16, fontFamily: "var(--font-ui)",
    cursor: "pointer", background: "var(--bg-raised)", color: "var(--ink)",
    border: "1px solid var(--line)", borderRadius: "var(--radius)",
  } as const;

  return (
    <div /* No 320 px floor. The ENGINE page ran 106 px past the bottom of a
         1080-line display because of it, and a floor that guarantees a scroll
         bar on a monitoring page is worse than a slightly shorter view of the
         engine -- the renderer already resizes to whatever it is given. */
      style={{ position: "relative", width: "100%", height: "100%",
               minHeight: 0 }}>
      <div ref={mount} style={{ width: "100%", height: "100%", position: "relative" }} />

      {/* The operator can take the engine apart and put it back without
          waiting for a fault to do it for them. */}
      {status === "ready" && (
        <div className="engine-model-toolbar" style={{ position: "absolute", left: 8, top: 8, display: "flex",
                      flexWrap: "wrap", maxWidth: "calc(100% - 16px)",
                      gap: "var(--space-2)" }}>
          <button style={btn} onClick={() => explode(!exploded)}>
            {exploded ? "REASSEMBLE" : "EXPLODE VIEW"}
          </button>
          <button style={btn} onClick={() => {
            layer.current?.clearFocus(); setPart(null); home.current();
          }}>CLEAR FOCUS</button>
          {/* The prompt that replaced the automatic explode. Most of the parts
              that fail are INSIDE the engine, so a highlight on one of them is
              invisible from the outside -- which is what the automatic explode
              was solving, at the cost of the assembly moving on its own. Saying
              so and leaving the control to the operator solves it too. */}
        </div>
      )}

      {/* WHAT IS LIT, AND HOW TO GET TO IT.
          The camera flies to the worst fault by itself the moment it lights.
          Every other lit fault used to be unreachable -- somewhere on the
          engine, with nothing naming it and no way to bring the view round.
          Worst first, click to fly. It is also the only thing on the panel
          that explains the colours: a dim grey part is RELATED to the fault,
          not a second broken one, and there was no way to know that. */}
      {status === "ready" && litFaults.length > 0 && (
        <div style={{ position: "absolute", left: 8, top: 48, minWidth: 232,
                      maxWidth: 300, background: "var(--bg-panel)",
                      border: "1px solid var(--line)",
                      borderRadius: "var(--radius)", padding: "var(--space-2)" }}>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                        letterSpacing: "0.07em", padding: "0 var(--space-2)",
                        marginBottom: "var(--space-1)" }}>
            DETECTED — CLICK TO VIEW
          </div>
          {litFaults.map((f) => (
            <button
              key={f.id}
              onClick={() => showFault(f.id)}
              aria-current={focused === f.id || undefined}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: "var(--space-3)", width: "100%", textAlign: "left",
                padding: "var(--space-1) var(--space-2)", cursor: "pointer",
                border: "1px solid transparent", borderRadius: "var(--radius)",
                background: focused === f.id ? "var(--bg-raised)" : "transparent",
                fontFamily: "var(--font-ui)",
                transition: "background 120ms linear",
              }}>
              <Status level={f.level} text={f.name} />
              <span style={{ fontFamily: "var(--font-num)", fontSize: 16,
                             color: "var(--ink-dim)" }}>
                {f.p.toFixed(2)}
              </span>
            </button>
          ))}
          {/* The prompt that replaced the automatic explode. Most of the parts
              that fail are INSIDE the engine, so a highlight on one of them is
              invisible from outside -- which is what the automatic explode was
              solving, at the cost of the assembly moving on its own. Saying so
              and leaving the control to the operator solves it too. */}
          {hidden > 0 && !exploded && (
            <div style={{ fontSize: 16, color: "var(--ink-mute)", lineHeight: 1.4,
                          padding: "var(--space-1) var(--space-2) 0" }}>
              {hidden === 1
                ? "one lit part is inside the engine — EXPLODE VIEW shows it"
                : `${hidden} lit parts are inside the engine — EXPLODE VIEW shows them`}
            </div>
          )}
        </div>
      )}

      {/* WHAT THE PART IS, WHEN ONE IS CLICKED.
          Straight from the package's component registry, with its OWN field
          names rather than the ones I first guessed at: displayName,
          componentType, subsystem, cylinderAssociation, faultRoles. An
          operator who clicks a glowing part is asking what it is, and the
          answer already exists in the data the highlight came from. */}
      {part && (
        <div className="engine-selected-part" style={{ position: "absolute", right: 8, top: "var(--engine-part-top, 8px)", maxWidth: "min(330px, calc(100% - 16px))",
                      boxSizing: "border-box", maxHeight: "var(--engine-part-height, calc(100% - 16px))", overflowY: "auto",
                      background: "var(--bg-panel)", border: "1px solid var(--line)",
                      borderRadius: "var(--radius)", padding: "var(--space-3)",
                      fontSize: 16, lineHeight: 1.45 }}>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                        letterSpacing: "0.07em", marginBottom: "var(--space-2)",
                        display: "flex", justifyContent: "space-between" }}>
            <span>SELECTED PART</span>
            <button type="button" aria-label="Close selected part details" onClick={() => setPart(null)} style={{ ...btn, padding: "2px 8px" }}>CLOSE</button>
          </div>

          <div style={{ fontWeight: 700, fontSize: 18 }}>
            {part.displayName ?? String(part.componentId ?? "")
              .replace(/^ROTAX_915IS_/, "").replace(/_/g, " ")}
          </div>

          {part.componentType && (
            <div style={{ color: "var(--ink-dim)" }}>
              {String(part.componentType).replace(/_/g, " ").toLowerCase()}
            </div>
          )}
          {part.subsystem && (
            <div style={{ color: "var(--ink-dim)" }}>
              {String(part.subsystem).replace(/^[0-9]+_/, "").replace(/_/g, " ").toLowerCase()}
            </div>
          )}
          {part.cylinderAssociation?.cylinders?.length > 0 && (
            <div style={{ color: "var(--ink-dim)" }}>
              cylinder {part.cylinderAssociation.cylinders.join(", ")}
            </div>
          )}

          {/* WHY IT COULD NOT BE SEEN BEFORE. The registry knows which parts
              live inside the assembly; those are the ones a highlight was
              invisible on until the explode view existed. */}
          {part.internal && (
            <div style={{ marginTop: "var(--space-2)", color: "var(--alert-advis)" }}>
              inside the engine — use the explode view to see it
            </div>
          )}

          {part.faultRoles && Object.keys(part.faultRoles).length > 0 && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <div style={{ color: "var(--ink-dim)" }}>can present as</div>
              {Object.entries(part.faultRoles).map(([fault, roles]: any) => (
                <div key={fault}>
                  {fault.replace(/_/g, " ").toLowerCase()}
                  <span style={{ color: "var(--ink-mute)" }}>
                    {" "}({Array.isArray(roles) ? roles.join(", ") : String(roles)})
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* PROVENANCE. Some internals were modelled to fill parts the source
              CAD did not contain -- the crankcase and barrels are solid in it.
              A part that is a modelling choice rather than a scanned component
              says so, on the same principle every engine value in this system
              carries its source. */}
          {part.identificationBasis && (
            <div style={{ marginTop: "var(--space-3)", fontSize: 16,
                          color: "var(--ink-mute)", lineHeight: 1.4 }}>
              {String(part.identificationBasis)}
            </div>
          )}
        </div>
      )}

      {status !== "ready" && (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
                      color: status === "failed" ? "var(--alert-caut)" : "var(--ink-mute)",
                      fontSize: "var(--size-label)", letterSpacing: "0.07em",
                      textAlign: "center", padding: "var(--space-4)" }}>
          {status === "loading"
            ? "LOADING ENGINE MODEL…"
            : `ENGINE MODEL UNAVAILABLE — ${detail.slice(0, 200)}`}
        </div>
      )}
    </div>
  );
}
