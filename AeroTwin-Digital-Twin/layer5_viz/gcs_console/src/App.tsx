/* The console shell -- PRD Part 4 sections 6 and 11, docs/UX_REDESIGN.md s5.
 *
 * Five bands, top to bottom, that never move and never reorder, because an
 * operator under load navigates by POSITION, not by reading:
 *
 *   A  global status bar  the app, this role's workspaces, what is live, the
 *                         master annunciators, the clock, the link, the user.
 *   B  engine strip       RPM, CHT max, EGT max, oil pressure, with limits.
 *   C  work area          the workspace; secondary tasks open in a drawer
 *                         inside it, never over A or B.
 *   D  rail               alerts, then "Waiting on you".
 *   E  one quiet line     where the data comes from, and whether to trust it.
 *
 * NO SIDEBAR. Each role has three to five workspaces named for its job, so
 * navigation fits in the status bar as tabs (Astro UXDS global status bar),
 * and the work area gets back the 240 px the rail of nineteen pages took. A
 * workspace with more than one view carries its views as tabs under its
 * title: ISA-101's Level 1 is the workspace, Levels 2-4 are one click down in
 * the same place, and nothing re-orients on the way.
 */

import { useEffect, useRef, useState } from "react";
import {
  acknowledge,
  can,
  logout,
  session,
  type Snapshot,
  useEngineInfo,
  useLiveState,
} from "./lib/api";
import { type Aircraft, type Focus, opsPost, OpsProvider, useOpsBoard } from "./lib/ops";
import { isAirborne } from "./lib/flight";
import { type AlertRow, AlertStack, Master, Readout } from "./components/Core";
import { ChecklistDrawer } from "./components/Checklist";
import { TwinLine } from "./components/TwinCompare";
import { useAlertAudio, testTone } from "./lib/audio";
import { procedureFor, useChecklists } from "./lib/checklists";
import { SortieCard } from "./components/Sortie";
import { EnginePage, ReportPage } from "./pages/Pages";
import { HealthPage } from "./pages/detail/Health";
import { PrognosticsPage } from "./pages/detail/Prognostics";
import { SimulationPage } from "./pages/detail/Simulation";
import { FleetPage } from "./pages/Fleet";
import { ReplayPage } from "./pages/Replay";
import { TestRigPage } from "./pages/TestRig";
import { AuditPage } from "./pages/Audit";
import { MaintenancePage } from "./pages/Maintenance";
import { EnginesPage } from "./pages/Engines";
import { UsersPage } from "./pages/Users";
import { ScenariosPage } from "./pages/Scenarios";
import { OverviewPage } from "./pages/Overview";
import { LoginScreen } from "./pages/Login";
import { MissionHome } from "./pages/home/Mission";
import { MissionOpsPage } from "./missionops/MissionOps";
import { SortieHistory } from "./pages/home/History";
import { FleetHome } from "./pages/home/Fleet";
import { ReviewHome } from "./pages/home/Review";
import { OperationsHome } from "./pages/home/Operations";
import { PageBoundary, Workspace, type Tab } from "./ui/kit";
import { type Level, Status, StatusSymbol, alertLevel, words } from "./ui/status";
import drdoSeal from "./assets/drdo-seal.svg";
import "./theme/tokens.css";
import "./theme/ui.css";

// ------------------------------------------------------------------ views

/* A COMPONENT THE OPERATOR ASKED TO SEE ON THE MODEL.
 *
 * Health can name a part -- a cylinder, from its balance figure -- but the 3D
 * model lives on Parameters, so the request has to survive the move between
 * views. `n` is a nonce so that asking for the SAME part twice still counts as
 * a fresh request; without it, clicking cylinder 3, wandering off and clicking
 * cylinder 3 again would change nothing. This is deliberately separate from
 * `Focus`, which is the ops board's aircraft/mission selection and means
 * something else entirely. */
export interface PartFocus { componentId: string; n: number }

interface Ctx {
  snap: Snapshot;
  engine: any;
  aircraft: Aircraft | null;
  airborne: boolean;
  focus: Focus | null;
  partFocus: PartFocus | null;
  focusPart: (componentId: string) => void;
  go: (legacy: string) => void;
  canGo: (legacy: string) => boolean;
  goSpace: (id: string) => void;
  openAircraft: (tail: string) => void;
  /* THE WORKSPACE A `home` VIEW HAS TO DRAW FOR ITSELF.
   *
   * A home view renders its own `Workspace` -- that is how it gets a title,
   * a context line and its own primary actions, which the compact frame
   * below has no slot for. Until now it could not also show the OTHER views
   * in its space, so a home view inside a multi-view space was a dead end:
   * no way back to Dashboard or Parameters without leaving the workspace.
   * These three are the same tabs the compact frame would have drawn. */
  tabs: Tab[];
  tab: string;
  onTab: (id: string) => void;
}

interface View {
  id: string;
  label: string;
  /** The scope the view needs (presentation only; the API enforces, s10c). */
  scope: string;
  /** The page id the older pages use to link to this one. */
  legacy?: string;
  /** A role's home draws its own title, actions and tabs. */
  home?: boolean;
  /* THIS VIEW CARRIES THE ENGINE'S NUMBERS ITSELF.
   *
   * s6.1 puts RPM, CHT, EGT and OIL PRESS in Zone B on every page, and that
   * is right for every page that does not already show them. Mission
   * planning shows all four -- and coolant, oil temperature, the health
   * index, the remaining life, each against its calibrated scale, and under
   * the transport the FLOWN values rather than the live ones. Zone B beside
   * that is the same four numbers twice, in two styles, one of them
   * answering a different question: what the engine is doing on the ground
   * now, while the operator is asking what a sortie would do to it.
   *
   * It costs 72 px of a workspace whose argument is that the map should be
   * big -- a third of the map's height on a 1366 panel. Recorded as a
   * deviation in docs/PRD_DEVIATIONS.md rather than taken silently. */
  ownsEngineStrip?: boolean;
  render: (c: Ctx) => React.ReactNode;
}

interface Space { id: string; label: string; views: View[] }

const V = {
  mission: { id: "mission", label: "Mission", scope: "fly:mission", legacy: "FLIGHT", home: true,
             render: (c: Ctx) => <MissionHome snap={c.snap} focus={c.focus} /> },
  operations: { id: "operations", label: "Operations", scope: "plan:mission", legacy: "OPERATIONS", home: true,
                render: (c: Ctx) => <OperationsHome go={c.goSpace} focus={c.focus} onAircraft={c.openAircraft} /> },
  fleetMaintain: { id: "fleet", label: "Fleet", scope: "write:maintenance", legacy: "AIRCRAFT", home: true,
                   render: (c: Ctx) => <FleetHome mode="maintain" focus={c.focus} /> },
  fleetCommand: { id: "fleet", label: "Fleet", scope: "admin:fleet", legacy: "AIRCRAFT", home: true,
                  render: (c: Ctx) => <FleetHome mode="command" focus={c.focus} /> },
  review: { id: "review", label: "Review", scope: "review:defects", legacy: "ENGINEERING", home: true,
            render: () => <ReviewHome /> },
  dashboard: { id: "dashboard", label: "Dashboard", scope: "read:telemetry", legacy: "OVERVIEW",
               render: (c: Ctx) => <OverviewPage snap={c.snap} go={c.go} canGo={c.canGo} aircraft={c.aircraft} airborne={c.airborne} /> },
  parameters: { id: "parameters", label: "Parameters", scope: "read:telemetry", legacy: "ENGINE",
                render: (c: Ctx) => <EnginePage snap={c.snap} limits={c.engine}
                                               partFocus={c.partFocus} /> },
  health: { id: "health", label: "Health", scope: "read:health", legacy: "HEALTH",
            render: (c: Ctx) => <HealthPage snap={c.snap} limits={c.engine} aircraft={c.aircraft}
                                            onFocusPart={c.focusPart} /> },
  prognostics: { id: "prognostics", label: "Prognostics", scope: "read:prognostics", legacy: "PROGNOSTICS",
                 render: (c: Ctx) => <PrognosticsPage snap={c.snap} /> },
  /* MISSION PLANNING. Draw a route, price it against THIS engine, check it,
     fly it through the mean-value model, and read what came back -- with an
     optional fault that belongs to the simulation and never touches the
     running twin. It replaces the route planner that used to live here: same
     slot, same scope, same `legacy` id, so `go("MISSION")` still lands.

     `home` because it draws its own Workspace: it needs the title row for
     COST IT and SIMULATE, which the compact frame has no slot for. */
  planning: { id: "planning", label: "Mission planning", scope: "read:mission",
              legacy: "MISSION", home: true, ownsEngineStrip: true,
              render: (c: Ctx) => <MissionOpsPage snap={c.snap} tabs={c.tabs}
                                                  tab={c.tab} onTab={c.onTab} /> },
  plan: { id: "plan", label: "Maintenance plan", scope: "read:advisory", legacy: "MAINTENANCE",
          render: (c: Ctx) => <MaintenancePage snap={c.snap} /> },
  sorties: { id: "sorties", label: "My sorties", scope: "read:ops", render: () => <SortieHistory /> },
  replay: { id: "replay", label: "Replay", scope: "read:replay", legacy: "REPLAY", render: () => <ReplayPage /> },
  reports: { id: "reports", label: "Reports", scope: "read:reports", legacy: "REPORT", render: () => <ReportPage /> },
  faults: { id: "faults", label: "Fault injection", scope: "run:simulation", legacy: "SIMULATION",
            render: (c: Ctx) => <SimulationPage snap={c.snap} /> },
  scenarios: { id: "scenarios", label: "Scenarios", scope: "run:simulation", legacy: "SCENARIOS",
               render: () => <ScenariosPage /> },
  testrig: { id: "testrig", label: "Test rig", scope: "run:simulation", legacy: "TEST RIG",
             render: (c: Ctx) => <TestRigPage snap={c.snap} /> },
  fleetdata: { id: "fleetdata", label: "Fleet data", scope: "read:fleet", legacy: "FLEET", render: () => <FleetPage /> },
  audit: { id: "audit", label: "Audit log", scope: "read:audit", legacy: "AUDIT", render: () => <AuditPage /> },
  accounts: { id: "accounts", label: "Accounts", scope: "admin:users", legacy: "USERS", render: () => <UsersPage /> },
  engines: { id: "engines", label: "Engine definitions", scope: "write:engines", legacy: "ENGINES",
             render: () => <EnginesPage /> },
} satisfies Record<string, View>;

/* EACH ROLE SEES ITS JOB, AND ONLY ITS JOB (AFRL Vigilant Spirit: preflight,
 * mission and emergency for the operator; engineering detail on a separate
 * interface). The commander used to see all nineteen pages, simulation and
 * fault injection included. Home first; the live engine second, under the
 * same name for everyone; records and configuration last. */
const ROLE_SPACES: Record<string, Space[]> = {
  ROLE_OPERATOR: [
    { id: "mission", label: "Mission", views: [V.mission] },
    { id: "engine", label: "Engine", views: [V.dashboard, V.parameters] },
    /* Mission planning is a SIMULATION, so it sits under Simulate rather than
       beside the live engine views -- see the note on the engineer's spaces.
       The simulation pages proper need run:simulation, which this role does not
       hold, so scope filtering leaves the operator this workspace with mission
       planning alone in it. */
    { id: "simulate", label: "Simulate",
      views: [V.planning, V.faults, V.scenarios, V.testrig] },
    { id: "history", label: "History", views: [V.sorties, V.replay] },
  ],
  ROLE_MAINTENANCE: [
    { id: "fleet", label: "Fleet", views: [V.fleetMaintain] },
    { id: "engine", label: "Engine", views: [V.plan, V.health, V.prognostics, V.dashboard] },
    { id: "reports", label: "Reports", views: [V.reports] },
  ],
  ROLE_ENGINEER: [
    { id: "review", label: "Review", views: [V.review] },
    { id: "engine", label: "Engine",
      views: [V.dashboard, V.parameters, V.health, V.prognostics] },
    /* MISSION PLANNING BELONGS WITH SIMULATE, NOT WITH THE LIVE ENGINE.
     *
     * It was grouped under Engine, beside the dashboard and the health page,
     * which put a page that flies a HYPOTHETICAL sortie through the mean-value
     * model in the same breath as the pages reading the engine that is actually
     * turning. Those are opposite things, and the distinction matters most
     * exactly where the page is used: it can inject a fault, and that fault
     * belongs to the simulated sortie and never touches the running twin. A
     * workspace called Engine is the wrong place to make that promise.
     *
     * First in the group because it is the one people come here to use; the
     * fault-injection, scenario and test-rig pages are the narrower tools. */
    { id: "simulate", label: "Simulate",
      views: [V.planning, V.faults, V.scenarios, V.testrig] },
    { id: "records", label: "Records", views: [V.reports, V.replay] },
    { id: "definitions", label: "Engines", views: [V.engines] },
  ],
  ROLE_COMMANDER: [
    { id: "operations", label: "Operations", views: [V.operations] },
    { id: "fleet", label: "Fleet", views: [V.fleetCommand] },
    { id: "engine", label: "Engine", views: [V.dashboard, V.parameters, V.health] },
    { id: "records", label: "Records", views: [V.reports, V.replay, V.fleetdata, V.audit] },
    { id: "admin", label: "Admin", views: [V.accounts, V.engines] },
  ],
};

/** The workspaces this session may open: its role's, less anything its
 *  scopes do not cover. An unknown role gets what its scopes allow. */
function spacesFor(role: string | undefined): Space[] {
  const base = ROLE_SPACES[role ?? ""] ?? [
    { id: "engine", label: "Engine", views: [V.dashboard, V.parameters, V.health, V.prognostics] },
    { id: "simulate", label: "Simulate", views: [V.planning, V.faults, V.scenarios, V.testrig] },
    { id: "records", label: "Records", views: [V.reports, V.replay] },
  ];
  return base.map((s) => ({ ...s, views: s.views.filter((v) => can(v.scope)) }))
    .filter((s) => s.views.length > 0);
}

/** Where a task on the rail belongs, by the page name the server gives it. */
const TASK_PAGE: Record<string, string> = {
  FLIGHT: "FLIGHT", OPERATIONS: "OPERATIONS", AIRCRAFT: "AIRCRAFT", ENGINEERING: "ENGINEERING",
};

// ------------------------------------------------------------------ app

export default function App() {
  const [signedIn, setSignedIn] = useState(false);
  if (!signedIn) return <LoginScreen onSignedIn={() => setSignedIn(true)} />;
  return (
    <OpsProvider>
      <Console onSignOut={() => { logout(); setSignedIn(false); }} />
    </OpsProvider>
  );
}

function Console({ onSignOut }: { onSignOut: () => void }) {
  const { snap, link, lastUpdate } = useLiveState();
  const engine = useEngineInfo(snap?.twin?.metadata?.engine_key);
  const { board, reload: reloadOps } = useOpsBoard();
  const who = session();
  const [spaces] = useState(() => spacesFor(who?.role));
  const [spaceId, setSpaceId] = useState(spaces[0]?.id ?? "engine");
  const [viewBy, setViewBy] = useState<Record<string, string>>({});
  const [focus, setFocus] = useState<Focus | null>(null);
  const [partFocus, setPartFocus] = useState<PartFocus | null>(null);
  const partSeq = useRef(0);

  // --- the audible alert (s4.7) and the electronic checklist ------------
  const checklists = useChecklists();
  const active: AlertRow[] = snap?.twin.alerts.active ?? [];
  const sound = useAlertAudio({
    masterWarning: !!snap?.twin.alerts.master_warning,
    masterCaution: !!snap?.twin.alerts.master_caution,
  });
  const [proc, setProc] = useState<null | { key: string; legend: string; level: number }>(null);
  const [switchingTail, setSwitchingTail] = useState<string | null>(null);
  const [aircraftSwitchError, setAircraftSwitchError] = useState<string | null>(null);
  const [procPhase, setProcPhase] = useState<Record<string, "airborne" | "ground">>({});
  const [procDone, setProcDone] = useState<Record<string, boolean[]>>({});
  const opened = useRef<Set<string>>(new Set());
  const alertKey = (a: AlertRow) => `${a.rule_id}@${a.first_seen_s}`;
  /* A NEW WARNING OPENS ITS PROCEDURE for the people flying or running the
     engine (ECAM does the same). Once per alert: closing it is respected. */
  useEffect(() => {
    if (!checklists || !["ROLE_OPERATOR", "ROLE_MAINTENANCE"].includes(who?.role ?? "")) return;
    const w = active.find((a) => a.level >= 5 && !a.acknowledged && !opened.current.has(alertKey(a))
                          && procedureFor(checklists, a.legend));
    if (w) {
      opened.current.add(alertKey(w));
      setProc({ key: alertKey(w), legend: w.legend, level: w.level });
    }
  }, [active.map(alertKey).join(","), checklists]);

  useEffect(() => {
    if (switchingTail && board?.active_tail === switchingTail) setSwitchingTail(null);
  }, [board?.active_tail, switchingTail]);

  const find = (legacy: string) => {
    for (const s of spaces) {
      const v = s.views.find((x) => x.legacy === legacy);
      if (v) return { s, v };
    }
    return null;
  };
  const open = (spaceIdTo: string, viewId?: string) => {
    setSpaceId(spaceIdTo);
    if (viewId) setViewBy((m) => ({ ...m, [spaceIdTo]: viewId }));
  };
  const go = (legacy: string) => { const f = find(legacy); if (f) open(f.s.id, f.v.id); };

  if (!snap) {
    return (
      <div style={{ height: "100%", display: "grid", placeItems: "center",
                    color: "var(--ink-dim)", fontSize: 18 }}>
        {link === "LOST" ? "Link lost. Retrying." : "Connecting to the engine twin…"}
      </div>
    );
  }

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0];
  const view = space.views.find((v) => v.id === viewBy[space.id]) ?? space.views[0];
  const selectedTail = board?.active_tail ?? snap.twin.metadata.aircraft_id;
  const selectedAircraft = board?.aircraft.find((a) => a.tail === selectedTail) ?? null;
  const airborne = isAirborne(snap, selectedAircraft?.status);
  const canConnectAircraft = can("write:maintenance") || can("review:defects") || can("plan:mission");
  const aircraftSwitchBlocked = switchingTail !== null || Boolean(board?.busy);
  const switchAircraft = async (nextTail: string) => {
    if (!nextTail || nextTail === selectedTail || switchingTail) return;
    setAircraftSwitchError(null);
    setSwitchingTail(nextTail);
    try {
      await opsPost(`/api/ops/aircraft/${encodeURIComponent(nextTail)}/connect`);
      reloadOps();
    } catch (e) {
      setAircraftSwitchError(e instanceof Error ? e.message : "Could not connect that aircraft.");
      setSwitchingTail(null);
    }
  };
  const ctx: Ctx = {
    snap, engine, aircraft: selectedAircraft, airborne, focus, go, canGo: (p) => find(p) !== null,
    partFocus,
    // Name the part, then go where the model is. ENGINE is the Parameters
    // view's legacy id, which is what `go` routes on.
    focusPart: (componentId: string) => {
      partSeq.current += 1;
      setPartFocus({ componentId, n: partSeq.current });
      go("ENGINE");
    },
    goSpace: (id) => open(id),
    openAircraft: (selectedTail) => {
      setFocus({ tail: selectedTail, n: Date.now() });
      open("fleet");
    },
    tabs: space.views.map((v) => ({ id: v.id, label: v.label })),
    tab: view.id,
    onTab: (id) => open(space.id, id),
  };

  const alerts = snap.twin.alerts;
  const pipe = snap.pipeline;
  const rep: any = snap.twin.reported ?? {};
  const lim = engine?.parameters ?? {};
  /* The oil-pressure minimum AT THE CURRENT ENGINE SPEED, published by the
     twin, which knows the speed. The manual gives two minima (2.0 bar above
     3,500 rpm, 0.8 bar below [OM s2.1]); taking only the first painted a
     perfectly legal taxi reading red. */
  const oilMin = snap.display?.oil_pressure_min_psi ?? lim.oil_pressure?.critical_min;

  /* The bus carries the flight phase as a numeric code (engine_sim
     PHASE_GROUND..PHASE_LANDING = 0..7); the sortie's own phase names tell
     apart what the code cannot: parked, warm-up hold, run-up, shut down. */
  const PHASE = ["Ground", "Start-up", "Taxi", "Take-off", "Climb", "Cruise", "Descent", "Landing"];
  const phaseCode = rep.environmental?.flight_phase;
  const so: any = snap.sortie ?? {};
  const running = so.state !== "complete" && so.state !== "parked";
  const phase = so.state === "complete" ? "Shut down"
    : so.state === "parked" ? "Parked, engine off"
    : ["WARM-UP", "RUN-UP", "COOL-DOWN"].includes(so.phase)
      ? (so.holding ? "Warm-up, holding" : words(so.phase))
    : typeof phaseCode === "number" ? PHASE[phaseCode] : "—";
  const tail = selectedTail;
  const run = so.kind === "mission" ? so.label : so.kind === "ground_run" ? "Ground run" : "";

  const tasks = board?.tasks ?? [];
  const taskSpace = (page: string) => find(TASK_PAGE[page] ?? page)?.s.id;
  const env = rep.environmental ?? {};
  const num = (m: any, f: (v: number) => string) => (m?.value != null ? f(m.value) : "—");

  return (
    <div className="console-shell" style={{ height: "100%", display: "flex", flexDirection: "column",
                  gap: "var(--gap)", padding: "var(--gap)", background: "var(--bg-void)" }}>

      {/* --- Zone A: global status bar ---------------------------------- */}
      <header className="gsb">
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingRight: 4 }}>
          <img src={drdoSeal} alt="" width={32} height={32} />
          <b style={{ fontSize: 18, letterSpacing: "0.12em" }}>ASTRA</b>
        </div>
        <span className="gsb-sep" />
        <nav className="gsb-nav" aria-label="Workspaces">
          {spaces.map((s) => {
            const n = tasks.filter((t) => taskSpace(t.page) === s.id).length;
            return (
              <button key={s.id} className="gsb-tab" aria-current={s.id === space.id ? "page" : undefined}
                      onClick={() => open(s.id)}>
                {s.label}{n > 0 && <span className="count">{n}</span>}
              </button>
            );
          })}
        </nav>

        <div style={{ flex: 1 }} />

        {/* Astro "application state": nobody should mistake this station for
            a live aircraft link. */}
        <span className="app-state" title="The engine on this station is the digital twin's simulation">
          SIMULATED ENGINE
        </span>
        <span className="gsb-sep" />

        <Master label="MSTR WARN" active={alerts.master_warning} confirm
                kind="warning" colour="var(--alert-warn)" onAck={acknowledge} />
        <Master label="MSTR CAUT" active={alerts.master_caution}
                kind="caution" colour="var(--alert-caut)" onAck={acknowledge} />
        {/* s4.7: the mute state is annunciated, not hidden in a menu. */}
        <button className="btn btn-quiet" style={{ paddingInline: 8 }}
                title={sound.state === "blocked" ? "The browser has not allowed sound yet. Press to enable."
                  : sound.state === "on" ? "Alert audio is on. A tone repeats until its master lamp is pressed. Press here to mute."
                  : sound.state === "muted" ? "Alert audio is muted. A new warning un-mutes it."
                  : "Alert audio is on. Press to mute."}
                onClick={() => sound.state === "blocked" ? sound.enable() : sound.toggleMute()}>
          {sound.state === "on" ? <Status level="off" text="Audio" bold={false} />
            : sound.state === "muted" ? <Status level="standby" text="AUDIO MUTED" />
            : sound.state === "blocked" ? <Status level="standby" text="Audio off: enable" />
            : <Status level="off" text="No audio" bold={false} />}
        </button>

        <span className="t-num" style={{ fontSize: 20, minWidth: 100, textAlign: "right" }}>
          {snap.wall_utc}
        </span>
        {/* Link state is annunciated, never hidden. PRD Part 4 s7.3. */}
        <Status level={link === "OK" ? "normal" : link === "STALE" ? "caution" : "warning"}
                text={link === "OK" ? "Link" : link === "STALE" ? "Link stale" : "Link lost"} />
        <UserMenu who={who} onSignOut={onSignOut} />
      </header>

      {/* --- Zone B: primary engine strip --------------------------------
       * PRD Part 4 s6.1: "The four highest-criticality parameters, always
       * visible on every page: RPM, CHT (max of 4), EGT (max of 4), OIL
       * PRESS." One compact row, each with its limit on the same line, and
       * the flight context after them at label size: context for the four,
       * not a peer of them (MIL-STD-1472H 5.17.17 criticality ordering).  */}
      <div className={"zone-b" + (view.ownsEngineStrip ? " zone-b-folded" : "")}
           aria-hidden={view.ownsEngineStrip || undefined}>
      <div style={{ minHeight: 0, overflow: "hidden" }}>
      <div className="strip">
        {/* Which aircraft these four numbers belong to, and what it is doing:
            the one piece of context the numbers cannot carry themselves. */}
        <div className="strip-cell station-aircraft" style={{ width: 280, flex: "0 1 280px" }}
             title={`${tail}${selectedAircraft?.engine_name ? ` · ${selectedAircraft.engine_name}` : ""} on the ground station${run ? `, ${run}` : ""}: ${phase}`}>
          {board?.aircraft.length ? (
            <select className="station-aircraft-select"
                    aria-label="Aircraft and engine on the ground station"
                    title={board.busy ? `Finish the active ${board.busy.kind} before changing aircraft`
                      : canConnectAircraft ? "Choose an aircraft to connect to the ground station"
                      : "Prepare your allotted mission to change aircraft"}
                    value={tail}
                    disabled={!canConnectAircraft || aircraftSwitchBlocked}
                    onChange={(ev) => { void switchAircraft(ev.target.value); }}>
              {board.aircraft.map((a) => (
                <option key={a.tail} value={a.tail}>{a.tail} · {a.engine_name || a.engine_key}</option>
              ))}
            </select>
          ) : <span className="t-label ellipsis">{tail}</span>}
          <span className="ellipsis station-aircraft-state" aria-live="polite">
            {switchingTail ? `Connecting ${switchingTail}…` : aircraftSwitchError
              ? "Aircraft switch failed" : `${running ? phase : so.state === "complete" ? "Shut down" : "Parked, engine off"}${run ? ` · ${run}` : ""}`}
          </span>
        </div>
        <div className="strip-cell" style={{ flex: 1 }}>
          <Readout compact label="RPM" m={rep.rpm} unit="rpm" digits={0}
                   limit={lim.rpm?.critical_max} warnAbove={lim.rpm?.critical_max} />
        </div>
        <div className="strip-cell" style={{ flex: 1 }}>
          <Readout compact label="CHT MAX" m={rep.cht_max} unit="°C"
                   limit={lim.cht?.critical_max} warnAbove={lim.cht?.critical_max} 
                   below={<TwinLine t={snap.display?.twin?.cht_max} digits={1} />} />
        </div>
        <div className="strip-cell" style={{ flex: 1 }}>
          <Readout compact label="EGT MAX" m={rep.egt_max} unit="°C" digits={0}
                   limit={lim.egt?.critical_max} warnAbove={lim.egt?.critical_max} 
                   below={<TwinLine t={snap.display?.twin?.egt_max} digits={0} />} />
        </div>
        <div className="strip-cell" style={{ flex: 1 }}>
          {/* No minimum on a stopped engine: it has no oil pressure by
              definition, and a parked aircraft flagged LOW is a false alarm. */}
          <Readout compact label="OIL PRESS" m={rep.oil_pressure} unit="psi" limit={oilMin}
                   warnBelow={(rep.rpm?.value ?? 0) > 500 ? oilMin : undefined} 
                   below={<TwinLine t={snap.display?.twin?.oil_pressure} digits={1} />} />
        </div>
        <div className="strip-cell strip-context">
          {[
            ["ALT", num(env.altitude_ft, (v) => `${Math.round(v).toLocaleString()} ft`)],
            ["IAS", num(env.airspeed_kmh, (v) => `${Math.round(v)} km/h`)],
            ["OAT", num(env.oat_c, (v) => `${v.toFixed(0)} °C`)],
            ["THR", num(rep.throttle_pct, (v) => `${v.toFixed(0)} %`)],
          ].map(([k, v]) => (
            <span key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span className="t-mute">{k}</span><span className="t-num">{v}</span>
            </span>
          ))}
        </div>
      </div>
      </div>
      </div>
      {aircraftSwitchError && (
        <div className="station-switch-error" role="alert">
          {aircraftSwitchError}
        </div>
      )}

      {link !== "OK" && (
        /* s7.3: values that are no longer live must not look live (HMI-03). */
        <div role="status" className="well">
          <Status level="caution" size={18}
                  text={`Data not live: values shown are from the last update${lastUpdate
                    ? ` at ${new Date(lastUpdate).toISOString().slice(11, 19)}Z` : ""}`} />
        </div>
      )}

      {/* --- Zones C and D ------------------------------------------------ */}
      <div className="console-workarea" style={{ flex: 1, minHeight: 0, display: "flex", gap: "var(--gap)", minWidth: 0 }}>
        <main style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: "hidden", position: "relative",
                       display: "flex", flexDirection: "column", opacity: link === "OK" ? 1 : 0.55 }}>
          <PageBoundary name={`${space.label}: ${view.label}`}>
            {view.home ? view.render(ctx) : (
              <Workspace compact title={view.label}
                         sub={`${tail} on the ground station · ${phase}`}
                         tabs={space.views.map((v) => ({ id: v.id, label: v.label }))}
                         tab={view.id} onTab={(id) => open(space.id, id)} fixed>
                <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                  {view.render(ctx)}
                </div>
              </Workspace>
            )}
          </PageBoundary>
          {proc && checklists && procedureFor(checklists, proc.legend) && (
            <ChecklistDrawer procedure={procedureFor(checklists, proc.legend)!}
                             legend={proc.legend} level={alertLevel(proc.level)}
                             phase={procPhase[proc.key] ?? (airborne ? "airborne" : "ground")}
                             onPhase={(p) => setProcPhase((m) => ({ ...m, [proc.key]: p }))}
                             done={procDone[`${proc.key}:${procPhase[proc.key] ?? (airborne ? "airborne" : "ground")}`] ?? []}
                             onDone={(d) => setProcDone((m) => ({
                               ...m, [`${proc.key}:${procPhase[proc.key] ?? (airborne ? "airborne" : "ground")}`]: d }))}
                             source={checklists.source}
                             onClose={() => setProc(null)} />
          )}
        </main>

        {/* Zone D. Fixed width, scrolls on its own, and collapses on a narrow
            panel (s6.3) -- the task counts then ride on the workspace tabs
            and the alert count on the master annunciators. */}
        <aside data-zone="D" style={{
          flex: "0 0 auto", width: "var(--alert-rail-w)", minHeight: 0,
          display: "var(--alert-rail-display)", flexDirection: "column",
          background: "var(--bg-panel)", border: "1px solid var(--line)",
          borderRadius: "var(--radius-lg)", padding: "14px 14px", overflow: "hidden",
        }}>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
            <section className="rail-section">
              <div className="rail-head">
                <span className="t-section">Alerts</span>
                <span className="t-num t-dim">{alerts.active.length}</span>
              </div>
              <AlertStack alerts={alerts.active} overflow={alerts.overflow_count}
                          hasProcedure={(a) => !!procedureFor(checklists, a.legend)}
                          onProcedure={(a) => setProc({ key: alertKey(a), legend: a.legend, level: a.level })} />
            </section>
            {/* A finished ground run is the maintainer's and the engineer's
                business; the operator's rail shows only a finished sortie. */}
            {(so.kind === "mission" || who?.role !== "ROLE_OPERATOR") && <section className="rail-section">
              <SortieCard snap={snap}
                          onDebrief={find("FLIGHT") ? () => go("FLIGHT") : undefined}
                          onReport={find("REPORT") ? () => go("REPORT") : undefined} />
            </section>}
            <section className="rail-section">
              <div className="rail-head">
                <span className="t-section">Waiting on you</span>
                <span className="t-num t-dim">{tasks.length}</span>
              </div>
              {tasks.length === 0 ? (
                <div className="t-mute">Nothing.</div>
              ) : tasks.slice(0, 12).map((t, i) => {
                const target = taskSpace(t.page);
                const level: Level = t.urgency === 0 ? "advisory"
                  : t.urgency === 1 && t.page !== "FLIGHT" ? "caution" : "standby";
                return (
                  <button key={i} className="task" disabled={!target}
                          onClick={() => {
                            if (!target) return;
                            open(target);
                            setFocus({ tail: t.tail, mission: t.mission, n: Date.now() });
                          }}>
                    <span style={{ paddingTop: 3 }}><StatusSymbol level={level} size={14} /></span>
                    <span style={{ flex: 1, minWidth: 0 }}>{t.text}</span>
                  </button>
                );
              })}
              {tasks.length > 12 && <div className="t-mute" style={{ marginTop: 6 }}>and {tasks.length - 12} more</div>}
            </section>
          </div>
        </aside>
      </div>

      {/* --- Zone E: where the data comes from -----------------------------
       * PRD Part 4 s7: the operator can always see whether to believe the
       * screen. Frame counts and latency percentiles are the engineer's;
       * everyone else gets source, rate and channel health.               */}
      <footer style={{
        display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap",
        padding: "2px 6px", fontSize: 16, color: "var(--ink-mute)",
      }}>
        <span>Source: virtual CAN · {pipe.hz} Hz · {pipe.speed_x}× real time</span>
        {pipe.data_quality >= 1
          ? <span>All {pipe.channels_total} channels</span>
          : <span className="foot-alert"><Status level="caution" bold={false}
                    text={`Channels ${pipe.channels_usable} of ${pipe.channels_total}`} /></span>}
        {who?.role === "ROLE_ENGINEER" && (
          <span className="t-num">
            frames {pipe.frames_decoded} · lost {pipe.frames_lost} · rejected {pipe.frames_rejected ?? 0}
            {" "}· err {pipe.decode_errors} · p50 {pipe.latency_p50_ms} ms · p95 {pipe.latency_p95_ms} ms
            {" "}· shadow {pipe.shadow_available ? "locked" : "standby"}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {pipe.error && <span className="foot-alert"><Status level="warning" bold={false} text={pipe.error} /></span>}
      </footer>
    </div>
  );
}

// ------------------------------------------------------------------ user menu

/* s10b: the active role is displayed persistently. Day and night are two
 * fixed brightness levels, not a dimmer (MIL-STD-1472H). */
function UserMenu({ who, onSignOut }: { who: any; onSignOut: () => void }) {
  const [openMenu, setOpenMenu] = useState(false);
  const [ambient, setAmbient] = useState<"night" | "day">(
    document.documentElement.getAttribute("data-ambient") === "night" ? "night" : "day");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!openMenu) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) {
        setOpenMenu(false);
      }
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); };
  }, [openMenu]);
  const flip = () => {
    const next = ambient === "night" ? "day" : "night";
    setAmbient(next);
    document.documentElement.setAttribute("data-ambient", next);
    setOpenMenu(false);
  };
  const role = words((who?.role ?? "").replace("ROLE_", ""));
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="btn" aria-haspopup="menu" aria-expanded={openMenu}
              onClick={() => setOpenMenu(!openMenu)}>
        <span style={{ fontWeight: 700 }}>{who?.subject}</span>
        <span className="t-dim" style={{ fontWeight: 500 }}>{role}</span>
        <span aria-hidden="true" className="t-dim">▾</span>
      </button>
      {openMenu && (
        <div className="menu" role="menu">
          <button role="menuitem" onClick={flip}>
            {ambient === "night" ? "Day display" : "Night display"}
          </button>
          {/* A speaker check before a sortie: one master-warning sweep. */}
          <button role="menuitem" onClick={() => { testTone(); setOpenMenu(false); }}>
            Test alert sound
          </button>
          <button role="menuitem" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}
