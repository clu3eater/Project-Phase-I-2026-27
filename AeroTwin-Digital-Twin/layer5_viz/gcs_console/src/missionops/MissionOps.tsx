/* MISSION OPS — plan it, check it, fly it, read it.
 *
 * WHAT THIS IS
 * ------------
 * The whole mission workflow on one surface, composed as an operations
 * console rather than a form beside a picture:
 *
 *   ┌ COMMAND BAR   what this mission is · its state · COST IT · SIMULATE ─┐
 *   ├──────────────────────────────────────────────┬──────────────────────┤
 *   │ MAP — the workspace, and the tools that act  │ COMMAND DOCK         │
 *   │ on it                            1272 × 648  │ PLAN CHECKS SIM RSLT │
 *   ├──────────────────────────────────────────────┴──────────────────────┤
 *   │ SIMULATION STRIP   only when there is a sortie          transport    │
 *   │ ENGINE INSTRUMENTS live twin, or the flown sample under the cursor   │
 *   └─────────────────────────────────────────────────────────────────────┘
 *
 *   PLAN       identity, four figures, four states, and the eight things the
 *              sortie is made of -- one line each, one open at a time
 *   CHECKS     every finding with the thing that answered it, and NOT
 *              EVALUATED where nothing has
 *   SIMULATE   the commit point, the elapsed count, then the monitor
 *   RESULTS    the verdict, what the fault did, the legs, the trace
 *
 * THE STRIP EARNS ITS HEIGHT. While the mission is being planned there is no
 * time to show, so it is not drawn and the map is 54 px taller. Both of the
 * collapses are real as well: closing the dock or the band changes a grid
 * track and the map takes the space through its own ResizeObserver, rather
 * than being revealed underneath something.
 *
 * ONE SELECTION, THREE VIEWS. A waypoint, a leg or an event is selected once
 * -- on the map, in the segment table, or from the event list -- and the map
 * highlights it while the dock turns into its inspector. There is no second
 * editor anywhere on the page.
 *
 * FAULT IS NOT A STAGE. It is a property of one simulation, so it has a sheet
 * rather than a tab: staged from SCENARIO in PLAN, or injected from the
 * transport at the second the aircraft has reached.
 *
 * THE ONE THING THAT MOVED IN THE BACKEND
 * ---------------------------------------
 * `/api/mission/flight` takes a `scenario`: a fault applied to a degradation
 * engine THE SIMULATION OWNS (layer4_core/flight_sim.py). Before it, the only
 * way to ask what a fault would do to a sortie was to inject it into the live
 * twin -- which degrades the real engine's health, its remaining life and
 * every alert on every page, permanently, to answer a hypothetical. The twin
 * lab still does exactly that, on purpose, on the INJECT FAULT page. This page
 * never touches the running engine.
 *
 * Everything else is the same four endpoints with the same bodies. Where the
 * console would like something the server does not have -- a per-leg speed, a
 * cruise throttle, a flown divert, wind, a health curve over the sortie -- it
 * says so rather than computing a substitute.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./motion.css";
import "../mission/mission.css";

import { type Airbase, type BaseRole } from "../data/airbases";
import { assessRoute, can, fetchEnvelope, simulateFlight, useEngineInfo,
         type Envelope, type FlightSim, type MissionScenario,
         type RouteCost } from "../lib/api";
import { Playback } from "../mission/clock";
import { TYPE_BY_KEY, emptyPlan, expand, newId, withBase,
         type MissionPlan, type PlanPoint } from "../mission/plan";
import { Workspace, type Tab as WsTab } from "../ui/kit";
import { Actions, MissionLine } from "./Actions";
import { MapPane } from "./MapPane";
import { Dock, type Tab } from "./SidePanel";
import { TelemetryBar } from "./TelemetryBar";
import { Timeline, type Mode } from "./Timeline";
import { NEW_SCENARIO, type ScenarioDraft } from "./FaultSheet";
import type { Sel } from "./Selection";
import type { Tool } from "./Palette";
import {
  DEFAULT_CONSTRAINTS, buildChecks, loadIdentity, saveIdentity, segments,
  worstOf, type Constraints, type MissionIdentity,
} from "./mission";

/* The dock is 380 working, 560 wide and 46 shut; the command bar 44; and the
 * band 104 with the instruments alone or 160 with the transport above them --
 * the instrument row carries a calibrated scale under each bar and needs the
 * height to stay readable. At 1920 x 912 that is a map of 1272 x 648 while
 * planning, 61 % of the work area, and 77 % of it with the dock away. */
const SIDE_W = 380;
const WIDE_W = 560;
const RAIL_W = 46;
const STRIP_H = 56;
const INSTR_H = 104;
const BAND_SHUT = 42;
/* Under this width the dock stops being a column: there is not enough left
 * for the map, so it floats over it instead and the map keeps its 60 %. */
const FLOAT_BELOW = 1500;

/* The one control the band owns: show the instruments, or give the height to
 * the map. Rendered in the transport row when there is one and in the corner
 * when there is not, so it never costs the instruments a row. */
function BandToggle(props: { open: boolean; onToggle: () => void }) {
  return (
    <button onClick={props.onToggle} className="mo-tab"
            aria-label={props.open ? "hide the telemetry" : "show the telemetry"}
            title={props.open ? "hide the telemetry and give the map the space"
                              : "show the telemetry"}
            style={{ width: 30, height: 30, flex: "0 0 auto", padding: 0,
                     display: "flex", alignItems: "center",
                     justifyContent: "center", background: "var(--bg-panel)",
                     border: "1px solid var(--line)",
                     borderRadius: "var(--radius)", color: "var(--ink-dim)",
                     cursor: "pointer" }}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2" strokeLinecap="round"
           strokeLinejoin="round" aria-hidden="true"
           style={{ transform: props.open ? "none" : "rotate(180deg)" }}>
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
  );
}

const handleBtn: React.CSSProperties = {
  width: 11, height: 40, padding: 0, cursor: "pointer", display: "flex",
  alignItems: "center", justifyContent: "center", borderRadius: 3,
  border: "1px solid var(--line)", background: "var(--bg-panel)",
  color: "var(--ink-mute)",
};

const remember = (w: number) => {
  try { window.sessionStorage.setItem("astra.missionops.sidew", String(w)); }
  catch { /* no storage: the width lasts as long as the page does */ }
};

export function MissionOpsPage(props: {
  snap: any;
  /* The other views in this workspace. A `home` view draws its own frame, so
   * it has to draw their tabs too or it becomes a dead end. */
  tabs?: WsTab[];
  tab?: string;
  onTab?: (id: string) => void;
}) {
  const snap = props.snap;
  const engine = useEngineInfo();

  /* NOTHING IS CHOSEN ON ARRIVAL. The type, the two fields and every point
   * of the route are the operator's to pick (mission/plan.ts, emptyPlan). */
  const [plan, setPlan] = useState<MissionPlan>(() => emptyPlan());

  /* ONE SELECTION FOR THE WHOLE PAGE: a point, a leg or an event. The map
   * highlights it and the dock inspects it; there is no second copy of this
   * state anywhere. */
  const [sel, setSel] = useState<Sel | null>(null);
  const selectedId = sel?.kind === "point" ? sel.id : null;
  const selectedLeg = sel?.kind === "leg" ? sel.i : null;

  /* WHAT A CLICK ON THE GROUND MEANS. WAYPOINT is the default because it is
   * what this map has always done. */
  const [tool, setTool] = useState<Tool>("WAYPOINT");

  const [sim, setSim] = useState<FlightSim | null>(null);
  const [cost, setCost] = useState<RouteCost | null>(null);
  const [env, setEnv] = useState<Envelope | null>(null);
  const [flying, setFlying] = useState(false);
  const [costing, setCosting] = useState(false);
  const [err, setErr] = useState("");

  const [tab, setTab] = useState<Tab>("PLAN");

  /* WHO THE SORTIE IS FOR, AND WHEN. Generated on arrival and held for the
   * session, because the API carries no mission identity -- there is nowhere
   * to file it, and making an operator type one before they can draw a line
   * is paperwork rather than planning. */
  const [identity, setIdentity] = useState<MissionIdentity>(loadIdentity);
  useEffect(() => { saveIdentity(identity); }, [identity]);

  /* WHAT THIS CREW WILL ACCEPT. CHECKS judges the plan against these; the
   * flight model flies its own reserve regardless, and the panel says so. */
  const [constraints, setConstraints] = useState<Constraints>(DEFAULT_CONSTRAINTS);

  /* THE FAULT THIS SIMULATION WILL BE FLOWN AGAINST -- and only this one. */
  const [draft, setDraft] = useState<ScenarioDraft>(NEW_SCENARIO);
  const [faultOpen, setFaultOpen] = useState(false);

  const [sideShut, setSideShut] = useState(false);
  /* THE DOCK IS SIZEABLE, because how much of it is wanted depends on what is
   * in it: a route list needs less than a segment table. Remembered for the
   * session, clamped so the map can never be squeezed out of its own page. */
  const [sideW, setSideW] = useState(() => {
    try {
      const v = Number(window.sessionStorage.getItem("astra.missionops.sidew"));
      return v >= 320 && v <= 560 ? v : SIDE_W;
    } catch { return SIDE_W; }
  });
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [bandOpen, setBandOpen] = useState(true);

  /* THE MISSION IS FROZEN FROM THE MOMENT IT IS COMMITTED, and for as long as
   * the answer on screen belongs to it. Editing again is a deliberate act. */
  const [locked, setLocked] = useState(false);
  /* THE SORTIE BEGINS WHERE A REAL ONE DOES, unless the operator only wants
   * the airborne part. The API has always taken this; the console fixed it. */
  const [coldStart, setColdStart] = useState(true);
  /* Where to put the transport back after a re-fly with an injected fault. */
  const resumeAt = useRef<number | null>(null);
  /* THE CLEAN RUN, KEPT SO A FAULT CAN BE PRICED AGAINST IT. */
  const [baseline, setBaseline] = useState<{ key: string; sim: FlightSim } | null>(null);

  /* The clock is an object, not state. Views subscribe to it; `version` is
   * bumped only when something a React view must re-render for has changed. */
  const pbRef = useRef<Playback | null>(null);
  if (!pbRef.current) pbRef.current = new Playback();
  const pb = pbRef.current;
  const [version, setVersion] = useState(0);
  useEffect(() => {
    pb.onDiscrete = () => setVersion((v) => v + 1);
    return () => { pb.onDiscrete = null; pb.stop(); };
  }, [pb]);

  const expansion = useMemo(() => expand(plan), [plan]);

  /* A sortie belongs to the route it was flown for. */
  const planKey = useMemo(() =>
    expansion.waypoints.map((q) => q.name + q.lat_deg + q.lon_deg + q.altitude_ft).join("|")
    + "@" + plan.isa_deviation_c + "/" + plan.humidity_pct + "/" + plan.airspeed_kmh
    + "/" + plan.usable_fuel_l + "/" + plan.live_engine,
  [expansion, plan]);
  const flownKey = useRef<string>("");
  const stale = !!sim && flownKey.current !== planKey;

  /* ---- actions ---------------------------------------------------------- */
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!flying && !costing) { setElapsed(0); return; }
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [flying, costing]);

  /* ONE PATH FOR EVERY SORTIE, CLEAN OR FAULTED.
   *
   * `scenario` is sent with the request and applied to a degradation engine
   * the SIMULATION owns (layer4_core/flight_sim.py). The live twin is not
   * touched, which is the whole difference between this and the twin lab. */
  const fly = async (scenario?: MissionScenario | null) => {
    setFlying(true); setLocked(true); setErr(""); setSim(null); pb.clear();
    setSel(null); setFaultOpen(false); setTab("SIMULATE");
    try {
      /* HOW LONG IT HAS BEEN WORKING, COUNTED UP AND SHOWN. This call steps the
       * engine model through an entire sortie and takes from half a minute to a
       * couple of minutes. A disabled button that says nothing for two minutes
       * is indistinguishable from a console that has hung. */
      const s = await simulateFlight(expansion.waypoints, {
        true_airspeed_kmh: plan.airspeed_kmh,
        isa_deviation_c: plan.isa_deviation_c,
        humidity_pct: plan.humidity_pct,
        usable_fuel_l: plan.usable_fuel_l,
        use_live_engine: plan.live_engine,
        start_engine: coldStart,
        scenario: scenario ?? null,
      });
      setSim(s);
      flownKey.current = planKey;
      /* THE CLEAN RUN OF THIS ROUTE, KEPT SO A FAULT CAN BE PRICED AGAINST IT.
       * Only a sortie flown with no mission fault AND on an engine with
       * nothing injected into it is a baseline; anything else is a second
       * faulted run wearing the name. */
      const clean = !scenario
        && Array.isArray(snap?.faults_injected)
        && snap.faults_injected.length === 0;
      if (clean) setBaseline({ key: planKey, sim: s });
      /* PAUSED AT THE BEGINNING, WITH THE ENGINE STOPPED. The verdict is
       * already in the dock for an operator who only wanted the answer; the
       * one who wants to watch presses play and sees it begin where a sortie
       * begins. */
      pb.load(s.samples, s.duration_s);
      if (resumeAt.current != null) {
        // Injected from the transport: come back to the same second, with the
        // faulted sortie under it.
        pb.seek(Math.min(resumeAt.current, s.duration_s));
        resumeAt.current = null;
      }
      /* The answer is what was asked for, so the dock moves to it. */
      setTab("RESULTS");
    } catch (e: any) {
      setErr(String(e?.message ?? e));
      // Nothing was flown, so nothing is being protected: give the plan back.
      setLocked(false);
      setTab("PLAN");
    } finally {
      setFlying(false);
    }
  };

  const price = async () => {
    setCosting(true); setErr(""); setCost(null); setEnv(null);
    try {
      // The route first, because it is what was asked for; the reach envelope
      // after, so the circles appear against an answer already on screen.
      setCost(await assessRoute(expansion.waypoints, {
        true_airspeed_kmh: plan.airspeed_kmh,
        isa_deviation_c: plan.isa_deviation_c,
        // THE SAME DAY THE SORTIE WOULD BE FLOWN ON. The costing endpoint
        // ignored humidity until it was given a field for it, so this panel
        // could set a humidity that moved the flown sortie and not the figure
        // printed beside it.
        humidity_pct: plan.humidity_pct,
        usable_fuel_l: plan.usable_fuel_l,
      }));
      /* THE RINGS ARE DRAWN FOR THE ALTITUDE THIS SORTIE IS PLANNED AT.
       * The endpoint has always taken one and the console never sent it, so
       * every reach ring was a 15,000 ft answer -- including around a sortie
       * planned at 24,000. */
      setEnv(await fetchEnvelope({
        altitude_ft: Math.max(...expansion.waypoints.map((w) => w.altitude_ft),
                              1000),
        isa_deviation_c: plan.isa_deviation_c,
        usable_fuel_l: plan.usable_fuel_l }));
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setCosting(false);
    }
  };

  /* ---- map callbacks ---------------------------------------------------- */
  const addPoint = useCallback((lat: number, lon: number) => {
    setPlan((p) => {
      const patrol = tool === "PATROL";
      const t = TYPE_BY_KEY[p.type] ?? TYPE_BY_KEY.CUSTOM;
      const made: PlanPoint = patrol ? {
        id: newId(), kind: "PATROL",
        name: "AREA " + String.fromCharCode(
          65 + p.points.filter((q) => q.kind === "PATROL").length),
        lat_deg: lat, lon_deg: lon, altitude_ft: t.patrol_ft,
        loiter_min: 60, pattern: "ORBIT", radius_km: 15,
      } : {
        id: newId(), kind: "TRANSIT",
        name: "WP" + (p.points.filter((q) => q.kind === "TRANSIT").length + 1),
        lat_deg: lat, lon_deg: lon,
        /* Corrected by the terrain check once the route is assessed; a starting
         * value, not a claim about the ground. */
        altitude_ft: p.points[p.points.length - 2]?.altitude_ft ?? t.cruise_ft,
      };
      const pts = [...p.points];
      /* A new point joins the ROUTE, not the end of the sortie: it goes in
       * before the recovery field, because an aircraft does not fly a leg after
       * it has landed. */
      const at = pts.length && pts[pts.length - 1].kind === "RECOVERY"
        ? pts.length - 1 : pts.length;
      pts.splice(at, 0, made);
      return { ...p, points: pts, type: "CUSTOM" };
    });
  }, [tool]);

  const movePoint = useCallback((id: string, lat: number, lon: number) => {
    setPlan((p) => ({
      ...p, type: "CUSTOM",
      points: p.points.map((q) => (q.id === id
        ? { ...q, lat_deg: lat, lon_deg: lon, base_id: undefined } : q)),
    }));
  }, []);

  const baseAction = useCallback((b: Airbase, role: BaseRole) => {
    setPlan((p) => {
      if (role === "ALTERNATE") return { ...p, alternate_id: b.id };
      return withBase(p, b, role === "DEPARTURE" ? "DEPARTURE" : "RECOVERY");
    });
  }, []);

  const patchPoint = useCallback((id: string, q: Partial<PlanPoint>) =>
    setPlan((p) => ({ ...p, type: "CUSTOM",
      points: p.points.map((x) => (x.id === id ? { ...x, ...q } : x)) })), []);

  const reorder = useCallback((i: number, d: number) => {
    setPlan((p) => {
      const j = i + d;
      if (j < 0 || j >= p.points.length) return p;
      const next = [...p.points];
      [next[i], next[j]] = [next[j], next[i]];
      return { ...p, points: next, type: "CUSTOM" };
    });
  }, []);

  const removePoint = useCallback((id: string) => {
    setSel(null);
    setPlan((p) => ({ ...p, type: "CUSTOM",
      points: p.points.filter((x) => x.id !== id) }));
  }, []);

  /* ---- the surface ------------------------------------------------------ */
  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 1600, h: 800 });
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const read = () => setBox((p) => {
      const n = { w: el.clientWidth, h: el.clientHeight };
      return p.w === n.w && p.h === n.h ? p : n;
    });
    const ro = new ResizeObserver(read);
    ro.observe(el);
    read();
    /* THE BAND'S OPENING POSITION, DECIDED ON THE SETTLED HEIGHT.
     *
     * On a panel too short to hold both, the instrument band starts shut so
     * the map has somewhere to be; it is one click to open. The threshold is
     * read from the element rather than from `box`, because `box` starts at a
     * placeholder and an effect watching it would decide on the placeholder.
     *
     * AND IT WAITS FOR ZONE B TO GET OUT OF THE WAY. The shell's engine strip
     * folds away for this view over 150 ms, which gives the work area about a
     * hundred more pixels -- so a decision taken on mount is taken against a
     * height that is about to be wrong, and the band shut itself on a 1366
     * panel that turned out to have room for it. */
    const settle = window.setTimeout(() => {
      const h = el.clientHeight;
      if (h > 0 && h < 480) setBandOpen(false);
    }, 220);
    return () => { window.clearTimeout(settle); ro.disconnect(); };
  }, []);

  const mode: Mode = flying ? "SIMULATING"
    : sim && locked ? (pb.ended ? "ANALYZE" : "PLAYBACK")
    : "PLAN";

  const floating = box.w < FLOAT_BELOW;
  const sideOpen = !sideShut;
  /* When the dock floats, the grid keeps only the rail: the map is not asked
   * to give up width it needs, and the panel is drawn over it instead. */
  /* Floating and open, the grid keeps NO track at all: a rail of vertical
   * tabs behind an open panel of horizontal ones is the same four words
   * twice. Floating and shut, the rail is how it is opened again. */
  const colW = floating ? (sideOpen ? 0 : RAIL_W) : sideOpen ? sideW : RAIL_W;
  /* THE STRIP EARNS ITS HEIGHT: no sortie, no time to show, no strip. */
  const stripH = mode === "PLAN" ? 0 : STRIP_H;
  const bandH = bandOpen ? stripH + INSTR_H : Math.max(stripH, BAND_SHUT);
  const bandW = box.w;
  const compact = bandW < 1150;

  /* NARROW: THE DOCK FLOATS, IT DOES NOT STAND DOWN.
   *
   * It used to shut itself below FLOAT_BELOW, on the argument that there was
   * not enough width for a column and a map. That was right when the column
   * was a form and wrong now that it carries the mission's identity, its
   * figures and its state: an operator arriving on a 1366 panel was shown a
   * rail and had to go looking for what the sortie was. So the panel opens,
   * over the map rather than beside it -- the map keeps its full width
   * underneath and one click on the chevron reveals all of it.
   */

  const ready = expansion.errors.length === 0 && expansion.waypoints.length >= 2;
  const mayRunScenarios = can("run:simulation");

  /* THE STANDING GO/NO-GO IS KEYED ON THE SERVER'S OWN PROFILE NAMES, and the
   * console's template keys are not them: "ISR_PATROL" never matched
   * "ISR PATROL", so two of the four highlights silently never fired. Matched
   * on letters alone against what the twin actually published. */
  const profile = useMemo(() => {
    const want = TYPE_BY_KEY[plan.type]?.profile;
    if (!want) return null;
    const key = (x: string) => x.replace(/[^a-z0-9]/gi, "").toUpperCase();
    const list: any[] = snap?.mission?.profiles ?? [];
    return list.find((p) => key(p.profile) === key(want))?.profile ?? want;
  }, [plan.type, snap?.mission?.profiles]);

  /* The legs, with everything geometry can give and everything the costing
   * has answered so far. */
  const segs = useMemo(() => segments(plan, expansion, cost),
                       [plan, expansion, cost]);

  const checks = useMemo(() => buildChecks({
    plan, ex: expansion, cost, env, sim, snap, constraints, stale,
    scenario: sim?.scenario
      ? { mode: sim.scenario.mode, severity: sim.scenario.severity,
          onset_s: sim.scenario.onset_s }
      : draft.mode
        ? { mode: draft.mode, severity: draft.severity, onset_s: draft.onset_s }
        : null,
  }), [plan, expansion, cost, env, sim, snap, constraints, stale, draft]);

  /* The worst thing the checks found, for the command bar and the commit. */
  const worst = useMemo(() => worstOf(checks), [checks]);

  /* FLYING THE FAULT.
   *
   * ONE PATH, whether the fault was configured before the sortie or from the
   * transport half way through it. The onset is a field on the draft, so this
   * does not need to know which door the operator came in by: the sortie is
   * flown again from the beginning with the fault appearing at that second,
   * and when there is a sortie on screen the cursor is put back where it was
   * so the difference can be read at the moment it starts.
   *
   * The live twin is not touched by any of it. */
  const flyFault = () => {
    if (!draft.mode) return;
    if (sim && draft.onset_s > 0) resumeAt.current = draft.onset_s;
    void fly({ mode: draft.mode, severity: draft.severity,
               ramp_hours: draft.ramp_hours, onset_s: draft.onset_s });
  };

  /* The sheet needs the dock open to be seen, so opening it opens the dock.
   * From the transport the onset starts at the second the aircraft has
   * reached; from the plan it starts wherever the draft left it. */
  const openFault = (atCursor: boolean) => {
    if (atCursor && sim) {
      setDraft({ ...draft, onset_s: Math.max(0, Math.round(pb.t)) });
    }
    setFaultOpen(true);
    setSideShut(false);
  };

  const editPlan = () => {
    setLocked(false);
    setTab("PLAN");
    setSel(null);
  };

  /* ONE PANEL, RENDERED IN ONE OF TWO PLACES. In a track of its own when
   * there is width for one, and over the map when there is not -- the rail
   * stays in the track either way, so the collapse always means the same
   * thing and the map never loses the space to a panel that is not there. */
  const dock = (collapsed: boolean, float: boolean) => (
    <Dock tab={tab} onTab={setTab}
          collapsed={collapsed} onCollapsed={setSideShut} floating={float}
          identity={identity} onIdentity={setIdentity}
          plan={plan} onPlan={setPlan} expansion={expansion}
          cost={cost} env={env} engine={engine} snap={snap}
          locked={locked} busy={flying || costing}
          sel={sel} onSel={setSel}
          onPatch={patchPoint} onReorder={reorder} onRemove={removePoint}
          segments={segs}
          coldStart={coldStart} onColdStart={setColdStart}
          checks={checks} constraints={constraints}
          onConstraints={setConstraints}
          costing={costing} onCost={price} canCost={ready} profile={profile}
          mode={mode} ready={ready} readiness={worst} elapsed={elapsed}
          sim={sim}
          baseline={baseline && baseline.key === flownKey.current
                    && baseline.sim !== sim ? baseline.sim : null}
          pb={pb} version={version}
          scenario={sim?.scenario ?? null}
          draft={draft} onDraft={setDraft}
          onSimulate={() => void fly(draft.mode
            ? { mode: draft.mode, severity: draft.severity,
                ramp_hours: draft.ramp_hours, onset_s: draft.onset_s }
            : null)}
          onEdit={editPlan}
          mayRunScenarios={mayRunScenarios}
          haveBaseline={!!baseline && baseline.key === planKey}
          faultOpen={faultOpen}
          onOpenFault={openFault}
          onCloseFault={() => setFaultOpen(false)}
          onFlyFault={() => { setFaultOpen(false); flyFault(); }}
          /* CLEAR means the sortie goes back to being clean: the staged fault
             is dropped as well as the flown one, so nothing offers to fly it
             again. */
          onClearFault={() => { setFaultOpen(false); setDraft(NEW_SCENARIO);
                                void fly(null); }} />
  );

  const simulate = () => void fly(draft.mode
    ? { mode: draft.mode, severity: draft.severity,
        ramp_hours: draft.ramp_hours, onset_s: draft.onset_s }
    : null);

  /* THE CONSOLE'S OWN FRAME DRAWS THE HEAD. Title, context line, primary
   * actions and the workspace's tabs all belong to `Workspace`; this page
   * used to carry a command bar of its own, which under that frame would
   * have been a second header for one page. What the bar said is now in the
   * two slots the frame already has -- see Actions.tsx. */
  return (
    <Workspace title="Mission planning"
               sub={<MissionLine plan={plan} identity={identity} mode={mode}
                                 ready={ready} readiness={worst} stale={stale}
                                 err={err} />}
               actions={<Actions mode={mode} ready={ready} costing={costing}
                                 busy={flying || costing} elapsed={elapsed}
                                 sim={sim} onCost={price} onSimulate={simulate}
                                 onEdit={editPlan} />}
               tabs={props.tabs} tab={props.tab} onTab={props.onTab} fixed>
    <div ref={wrapRef} className="mo-grid mo-rise"
         style={{ position: "relative", flex: 1, minHeight: 0, minWidth: 0,
                  display: "grid", gap: "var(--gap)",
                  gridTemplateColumns: "minmax(0, 1fr) " + colW + "px",
                  gridTemplateRows: "minmax(0, 1fr) " + bandH + "px" }}>

      {/* ---- the ground -------------------------------------------------- */}
      <div style={{ gridColumn: 1, gridRow: 1, minWidth: 0, minHeight: 0 }}>
        <MapPane mode={mode} plan={plan} expansion={expansion}
                 selectedId={selectedId}
                 onSelect={(id) => setSel(id ? { kind: "point", id } : null)}
                 selectedLeg={selectedLeg}
                 onSelectLeg={(i) => setSel(i == null ? null
                                                      : { kind: "leg", i })}
                 tool={tool} onTool={setTool}
                 onAddPoint={addPoint} onMovePoint={movePoint}
                 onBaseAction={baseAction}
                 pb={pb} sim={sim} cost={cost} env={env} snap={snap}
                 locked={locked} launch_utc={identity.launch_utc} />
      </div>

      {/* ---- the mission ------------------------------------------------- */}
      <div style={{ gridColumn: 2, gridRow: 1, minWidth: 0, minHeight: 0 }}>
        {(!floating || !sideOpen) && dock(!sideOpen, false)}
      </div>

      {/* THE HANDLE, ON THE JOIN, AND VISIBLE.
          It carries all three widths the dock has: DRAG for any width between
          320 and 560, DOUBLE-CLICK to swap between the working width and the
          wide one for the tables, and the button to shut it altogether. It
          used to be a seven-pixel invisible strip that only resized, and the
          two chrome buttons it should have been carrying were crowding the
          tab row instead. Pointer capture so a fast drag that leaves the
          strip still resizes. */}
      {sideOpen && !floating && (
        <div role="separator" aria-label="resize the mission panel"
             aria-orientation="vertical" className="mo-handle"
             title="drag to resize · double-click to widen"
             onDoubleClick={() => {
               const w = sideW >= WIDE_W - 1 ? SIDE_W : WIDE_W;
               setSideW(w); remember(w);
             }}
             onPointerDown={(e) => {
               drag.current = { x: e.clientX, w: sideW };
               (e.target as HTMLElement).setPointerCapture(e.pointerId);
             }}
             onPointerMove={(e) => {
               const d = drag.current;
               if (!d) return;
               const next = Math.max(320, Math.min(WIDE_W,
                 d.w - (e.clientX - d.x)));
               setSideW(next);
             }}
             onPointerUp={(e) => {
               if (drag.current) remember(sideW);
               drag.current = null;
               (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
             }}
             style={{ position: "absolute", top: 0, bottom: bandH + 10,
                      right: colW + 1, width: 11, zIndex: 6,
                      cursor: "col-resize", display: "flex",
                      /* CENTRED: beside the tabs they read as part of the
                         tab row and crowd it, which is what moving them off
                         the tab row was for. The two buttons are 84 px of a
                         600 px strip, so there is grab left everywhere. */
                      alignItems: "center", justifyContent: "center",
                      background: "transparent" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <button onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => setSideShut(true)}
                    aria-label="hide the mission panel"
                    title="hide the mission panel and give the map the width"
                    style={handleBtn}>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="3" strokeLinecap="round"
                   strokeLinejoin="round" aria-hidden="true">
                <path d="M10 6l6 6-6 6" />
              </svg>
            </button>
            {/* THE WIDE MODE, AS A CONTROL RATHER THAN A GESTURE. Dragging
                gives any width between 320 and 560; this is the one an
                operator reaches for when the segment table or the comparison
                wants the room, and it goes back the same way. */}
            <button onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => {
                      const w = sideW >= WIDE_W - 1 ? SIDE_W : WIDE_W;
                      setSideW(w); remember(w);
                    }}
                    aria-label={sideW >= WIDE_W - 1 ? "narrow the mission panel"
                                                    : "widen the mission panel"}
                    title={sideW >= WIDE_W - 1 ? "back to the working width"
                                               : "widen it for the tables"}
                    style={handleBtn}>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="3" strokeLinecap="round"
                   strokeLinejoin="round" aria-hidden="true">
                {sideW >= WIDE_W - 1
                  ? <path d="M15 6l-6 6 6 6" />
                  : <><path d="M11 6l-6 6 6 6" /><path d="M19 4v16" opacity="0.6" /></>}
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* The dock floats over the map when the page is too narrow to give it
          a track of its own. */}
      {floating && sideOpen && (
        <div style={{ position: "absolute", top: 0, right: 0,
                      bottom: bandH + 10, width: SIDE_W, maxWidth: "62%",
                      zIndex: 5 }}>
          {dock(false, true)}
        </div>
      )}

      {/* ---- the time, and the numbers -----------------------------------
       * THE CHEVRON DOES NOT GET A ROW OF ITS OWN WHILE PLANNING.
       *
       * It used to: the chrome row was `height: stripH || BAND_SHUT`, which is
       * 56 px with a sortie on screen and 42 px without one -- so a band that
       * had no transport in it still spent 42 px on a row holding a single
       * button, and the instruments underneath were left 54 px of the 88 they
       * need. The scale labels under every bar and the Zulu clock in the
       * source block were simply cut off the bottom, which is most of what
       * makes this an instrument face rather than a row of numbers.
       *
       * So the row exists when there is a transport to put in it, or when the
       * band is shut and its one line is the label. Otherwise the button sits
       * in the corner and the instruments get the height.                   */}
      <div style={{ gridColumn: "1 / -1", gridRow: 2, minWidth: 0, minHeight: 0,
                    position: "relative",
                    display: "flex", flexDirection: "column",
                    background: "var(--bg-panel)", border: "1px solid var(--line)",
                    borderRadius: "var(--radius)", overflow: "hidden",
                    padding: "0 var(--space-3)" }}>
        {stripH > 0 || !bandOpen ? (
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)",
                        flex: "0 0 auto", minWidth: 0,
                        height: stripH || BAND_SHUT }}>
            {stripH > 0 ? (
              <div className="mo-strip" style={{ flex: 1, minWidth: 0 }}>
                <Timeline mode={mode} plan={plan} expansion={expansion}
                          sim={sim} pb={pb} version={version} elapsed={elapsed}
                          compact={compact} identity={identity}
                          scenario={sim?.scenario ?? null}
                          mayInject={mayRunScenarios}
                          busy={flying || costing}
                          onOpenFault={() => openFault(true)}
                          onEdit={editPlan}
                          onResults={() => { setSideShut(false); setTab("RESULTS"); }}
                          onSelectEvent={(i) => setSel({ kind: "event", i })} />
              </div>
            ) : (
              <span style={{ flex: 1, minWidth: 0, fontSize: "var(--size-label)",
                             color: "var(--ink-mute)", letterSpacing: "0.1em",
                             whiteSpace: "nowrap", overflow: "hidden",
                             textOverflow: "ellipsis" }}>
                {sim && locked ? "ENGINE — FLOWN SORTIE" : "ENGINE — LIVE"}
              </span>
            )}
            <BandToggle open={bandOpen} onToggle={() => setBandOpen((v) => !v)} />
          </div>
        ) : (
          <div style={{ position: "absolute", right: "var(--space-3)", top: 7,
                        zIndex: 2 }}>
            <BandToggle open={bandOpen} onToggle={() => setBandOpen((v) => !v)} />
          </div>
        )}

        {bandOpen && (
          <>
            {stripH > 0 && (
              <div style={{ height: 1, background: "var(--line)",
                            flex: "0 0 auto", margin: "0 0 6px" }} />
            )}
            <div style={{ flex: 1, minHeight: 0, minWidth: 0,
                          paddingTop: stripH > 0 ? 0 : 8, paddingBottom: 8,
                          /* Clear of the corner button when it floats. */
                          paddingRight: stripH > 0 ? 0 : 36 }}>
              <TelemetryBar source={sim && locked ? "FLOWN" : "LIVE"} snap={snap}
                            pb={pb} sim={sim} engine={engine}
                            compact={compact} />
            </div>
          </>
        )}
      </div>
    </div>
    </Workspace>
  );
}
