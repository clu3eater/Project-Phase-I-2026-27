/* THE MAP PANE — the map, and the three things that belong ON it.
 *
 * Everything here is either the ground or something glued to a place on the
 * ground. The map keeps its own instruments (zoom, fit, layers, the scale and
 * the coordinate readout); this adds only what the MISSION page owns:
 *
 *   the tools      top left, what a click on the ground means. Only while the
 *                  mission is editable -- a locked one has no tools.
 *   the monitor    where the aircraft has got to, while it plays
 *   the engine     top right, what this sortie does to the engine, and
 *                  nothing else about the engine
 *
 * TWO THINGS THAT USED TO BE HERE HAVE MOVED, and both for the same reason:
 * there should be one of each on the page.
 *
 *   the state pill  is now the command bar's state chip, which is visible on
 *                   every tab and with the dock collapsed. Two state
 *                   indicators is one too many and they can disagree.
 *   the waypoint    card is now the dock's inspector. Editing a point in a
 *                   card on the map AND in a panel beside it is two editors
 *                   for one object; the inspector also has room for the
 *                   navigation figures the card never had.
 *
 * The map is NOT full bleed here: it sits in a grid cell beside a column, so
 * it keeps the console's panel border and corner radius like every other
 * surface on the page.
 */

import { useEffect, useRef } from "react";

import type { Airbase, BaseRole } from "../data/airbases";
import type { Envelope, FlightSim, RouteCost } from "../lib/api";
import { MissionMap } from "../components/MissionMap";
import { Playback } from "../mission/clock";
import { Palette, type Tool } from "./Palette";
import type { Expansion, MissionPlan } from "../mission/plan";
import type { Mode } from "./Timeline";

export function MapPane(props: {
  mode: Mode;
  plan: MissionPlan;
  expansion: Expansion;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** The leg picked on the map, or from the segment table. */
  selectedLeg: number | null;
  onSelectLeg: (i: number | null) => void;
  /** What a click on open ground means. */
  tool: Tool;
  onTool: (t: Tool) => void;
  onAddPoint: (lat: number, lon: number) => void;
  onMovePoint: (id: string, lat: number, lon: number) => void;
  onBaseAction: (b: Airbase, role: BaseRole) => void;
  pb: Playback;
  sim: FlightSim | null;
  cost: RouteCost | null;
  env: Envelope | null;
  snap: any;
  locked: boolean;
  /** Planned launch, so the map can say when the aircraft gets home. */
  launch_utc: string;
}) {
  const stage: "PLAN" | "FLYING" | "ANALYZE" =
    props.mode === "SIMULATING" ? "FLYING"
      : props.mode === "PLAN" ? "PLAN" : "ANALYZE";

  return (
    <MissionMap
      points={props.plan.points}
      patrols={props.expansion.patrols}
      routeLine={props.expansion.waypoints}
      selectedId={props.selectedId}
      onSelect={props.onSelect}
      onAddPoint={props.onAddPoint}
      onMovePoint={props.onMovePoint}
      onBaseAction={props.onBaseAction}
      alternateId={props.plan.alternate_id}
      clickIntent={props.tool === "SELECT" ? "select" : "add"}
      onSelectLeg={props.onSelectLeg}
      selectedLeg={props.selectedLeg}
      playback={props.pb}
      events={props.sim?.events}
      onSeek={(t) => { props.pb.pause(); props.pb.seek(t); }}
      envKm={props.env?.radius_km}
      envNewKm={props.env?.radius_new_km}
      height="100%"
      stage={stage}
      editable={!props.locked}
      overlays={
        <>
          <Palette tool={props.tool} onTool={props.onTool}
                   locked={props.locked} />
          {(props.mode === "PLAYBACK" || props.mode === "ANALYZE") && props.sim && (
            <Monitor pb={props.pb} sim={props.sim} launch={props.launch_utc} />
          )}
          <EngineCost snap={props.snap} cost={props.cost} sim={props.sim} />
        </>
      }
    />
  );
}

/* ------------------------------------------------------------------ *
 * MONITOR — where the aircraft has got to, on the map, while it plays
 *
 * Three facts, and all three are read off the sortie rather than estimated:
 * the leg being flown (`FlightSample.leg`, which names the waypoint being flown
 * TO), how much of the sortie has been played, and -- when a launch time has
 * been set -- the Zulu clock the aircraft gets home at. Written straight to the
 * DOM from the clock, like every other per-frame readout on this page.
 *
 * THE PERCENTAGE IS HONEST BECAUSE PLAYBACK HAS ONE. The sortie is already
 * flown and its duration is known, so "42 % of the sortie" is a fact about the
 * transport. The SIMULATION has no progress -- the server reports none -- and
 * nothing here pretends otherwise.
 * ------------------------------------------------------------------ */

function Monitor(props: { pb: Playback; sim: FlightSim; launch: string }) {
  const next = useRef<HTMLSpanElement>(null);
  const pct = useRef<HTMLSpanElement>(null);
  const fault = useRef<HTMLSpanElement>(null);

  useEffect(() => props.pb.subscribe((t) => {
    const s = props.pb.samples[props.pb.indexAt(t)];
    if (!s) return;
    if (next.current) {
      // `leg` is "FROM→TO" where the model named it; the half after the arrow
      // is the waypoint being flown to.
      const to = (s.leg || "").split(/→|->/).pop()?.trim();
      next.current.textContent = to && to !== s.leg ? to : (s.leg || "—");
    }
    if (pct.current && props.pb.duration > 0) {
      pct.current.textContent =
        Math.round((t / props.pb.duration) * 100) + "% flown";
    }
    if (fault.current) {
      const sc = props.sim.scenario;
      const on = !!sc && t >= sc.onset_s;
      fault.current.style.display = on ? "inline" : "none";
      if (on && sc) {
        fault.current.textContent =
          sc.mode.replace(/_/g, " ").toUpperCase() + " ACTIVE";
      }
    }
  }), [props.pb, props.sim]);

  const lands = (() => {
    if (!props.launch) return null;
    const t0 = Date.parse(props.launch.length <= 16
      ? props.launch + ":00Z" : props.launch);
    if (!isFinite(t0)) return null;
    const d = new Date(t0 + props.sim.duration_s * 1000);
    return String(d.getUTCHours()).padStart(2, "0") + ":"
         + String(d.getUTCMinutes()).padStart(2, "0") + "Z";
  })();

  return (
    <div className="mo-fade"
         style={{ position: "absolute", left: 56, top: 10, display: "flex",
                  alignItems: "center", gap: 10, height: 28, maxWidth: "60%",
                  padding: "0 12px", pointerEvents: "none",
                  /* s14: no blur backdrop. A solid panel with a hairline
                     edge, in the imagery palette, which is what this console
                     uses for chrome drawn over map tiles. */
                  background: "var(--bg-panel)",
                  border: "1px solid var(--line)", borderRadius: "var(--radius)",
                  fontSize: "var(--size-label)", whiteSpace: "nowrap" }}>
      <span style={{ color: "var(--ink-mute)", letterSpacing: "0.08em" }}>NEXT</span>
      <span ref={next} className="mo-num"
            style={{ fontWeight: 700, overflow: "hidden",
                     textOverflow: "ellipsis" }} />
      <span ref={pct} className="mo-num"
            style={{ fontFamily: "var(--font-num)", color: "var(--ink-dim)" }} />
      {lands && (
        <span style={{ color: "var(--ink-mute)" }}>
          lands <b style={{ fontFamily: "var(--font-num)",
                            color: "var(--ink-dim)" }}>{lands}</b>
        </span>
      )}
      <span ref={fault}
            style={{ display: "none", fontWeight: 800, letterSpacing: "0.06em",
                     color: "var(--alert-caut)" }} />
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * What this mission does to the engine
 * ------------------------------------------------------------------ */

function EngineCost(props: { snap: any; cost: RouteCost | null; sim: FlightSim | null }) {
  const d = props.snap?.display ?? {};
  const chi = typeof d.chi === "number" ? d.chi : null;
  const rul = typeof d.rul_hours === "number" ? d.rul_hours : null;
  const life = props.cost?.life_hours ?? null;

  return (
    /* TOP RIGHT, WHICH IS THE ONLY FREE CORNER. The map owns its bottom left
       (scale, compass, coordinates) and its bottom right (attribution), and
       the state pill has the top left. */
    <div className="mo-fade"
         style={{ position: "absolute", right: 10, top: 10, width: 218,
                  pointerEvents: "none", padding: "9px 11px",
                  background: "var(--bg-panel)",
                  border: "1px solid var(--line)", borderRadius: "var(--radius)" }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.1em", marginBottom: 5 }}>
        THIS SORTIE, ON THIS ENGINE
      </div>
      <Row k="health χ" v={chi != null ? chi.toFixed(2) : "—"}
           note={d.band ?? ""} />
      <Row k="life left" v={rul != null ? rul.toFixed(1) : "—"} note="h" />
      <Row k="sortie costs" v={life != null ? life.toFixed(2) : "—"} note="eng-h"
           hue={life != null ? "var(--alert-caut)" : undefined} />
      {/* ONE SUBTRACTION OF TWO REAL NUMBERS, AND IT SAYS SO. The twin's
          remaining life less what the route costing prices this route at.
          There is no forecast behind it and it does not claim to be one. */}
      {rul != null && life != null && (
        <div style={{ marginTop: 6, paddingTop: 6,
                      borderTop: "1px solid var(--line)",
                      fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      lineHeight: 1.4 }}>
          leaves ≈ <b style={{ fontFamily: "var(--font-num)", color: "var(--ink)" }}>
            {Math.max(0, rul - life).toFixed(1)} h</b>, first order
        </div>
      )}
      {props.cost?.limiting_component && (
        <div style={{ marginTop: 4, fontSize: "var(--size-label)",
                      color: "var(--ink-mute)", whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis" }}
             title={"The component the route costing found closest to its limit: "
                    + props.cost.limiting_component}>
          limited by {props.cost.limiting_component.replace(/_/g, " ")}
        </div>
      )}
    </div>
  );
}

function Row(props: { k: string; v: string; note?: string; hue?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 6, minWidth: 0 }}>
      <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                     flex: 1, minWidth: 0, whiteSpace: "nowrap",
                     overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.k}
      </span>
      <span className="mo-num"
            style={{ fontFamily: "var(--font-num)", fontSize: 17, fontWeight: 700,
                     color: props.hue ?? "var(--ink)", whiteSpace: "nowrap" }}>
        {props.v}
      </span>
      {props.note && (
        <span style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                       whiteSpace: "nowrap" }}>{props.note}</span>
      )}
    </div>
  );
}
