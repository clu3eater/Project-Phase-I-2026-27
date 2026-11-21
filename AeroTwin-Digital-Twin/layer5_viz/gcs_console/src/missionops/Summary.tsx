/* THE FIRST SCREEN — what this mission is, in the order it is asked.
 *
 * The old panel opened on a form: mission id, tasking ref, launch time, then
 * six accordions. An operator who wanted to know whether the sortie was worth
 * flying had to open every one of them and do the arithmetic themselves.
 *
 * This is the opposite order.
 *
 *   IDENTITY   what the sortie is and where it goes            (one glance)
 *   FIGURES    how far, how long, how long on station, how many waypoints
 *   STATUS     route, terrain, fuel, engine -- and NOT EVALUATED where
 *              nothing has answered yet
 *
 * Configuration comes after all three, behind the inspector rows. The rule
 * the status tiles keep is the same one CHECKS keeps: a tile is never green
 * because nobody looked. `PENDING` reads NOT COSTED in ink-mute, which is the
 * one state that is not a finding.
 */

import { useEffect, useRef, useState } from "react";

import { BASE_BY_ID } from "../data/airbases";
import type { FlightSim, RouteCost } from "../lib/api";
import {
  MISSION_TYPES, TYPE_BY_KEY, buildPlan, fmtMin,
  type Expansion, type MissionPlan,
} from "../mission/plan";
import { Chip, ghostButton, inputStyle } from "../mission/ui";
import { StatusSymbol, type Level } from "../ui/status";
import {
  groupLead, groupState, type Check, type CheckState, type MissionIdentity,
} from "./mission";

/* s14: status is a SHAPE plus a colour plus a word, from the console's own
 * vocabulary -- never a text glyph or an emoji. */
const LEVEL: Record<CheckState, Level> = {
  PASS: "normal", CAUTION: "caution", FAIL: "warning",
  PENDING: "standby", NA: "off",
};

const HUE: Record<CheckState, string> = {
  PASS: "var(--state-normal)",
  CAUTION: "var(--alert-caut)",
  FAIL: "var(--alert-warn)",
  PENDING: "var(--ink-mute)",
  NA: "var(--ink-mute)",
};

/* ------------------------------------------------------------------ *
 * Identity
 * ------------------------------------------------------------------ */

/** The name the plan gets when nothing has renamed it. */
function defaultName(plan: MissionPlan): string {
  const t = TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.CUSTOM;
  const dep = plan.points.find((q) => q.kind === "DEPARTURE");
  const rec = [...plan.points].reverse().find((q) => q.kind === "RECOVERY");
  return t.label + " — " + (dep?.name ?? "?") + " to " + (rec?.name ?? "?");
}

export function MissionHead(props: {
  plan: MissionPlan;
  onPlan: (p: MissionPlan) => void;
  identity: MissionIdentity;
  onIdentity: (v: MissionIdentity) => void;
  locked: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { plan, identity } = props;
  const t = TYPE_BY_KEY[plan.type] ?? TYPE_BY_KEY.CUSTOM;

  /* THE TITLE IS THE TYPE UNLESS SOMEBODY HAS SAID OTHERWISE. A plan nobody
   * renamed carries a generated name that repeats the two fields printed
   * directly underneath it; showing that twice is noise, so the generated
   * case shows the mission type instead and a renamed one shows the name. */
  const named = plan.name && plan.name !== defaultName(plan);
  const title = named ? plan.name : plan.type ? t.label : "New mission";

  const dep = plan.points.find((q) => q.kind === "DEPARTURE");
  const rec = [...plan.points].reverse().find((q) => q.kind === "RECOVERY");
  const base = (p: typeof dep) => {
    if (!p) return "—";
    const b = p.base_id ? BASE_BY_ID[p.base_id] : null;
    return b ? b.short + " (" + b.id + ")" : p.name;
  };

  return (
    <div style={{ position: "relative", flex: "0 0 auto",
                  padding: "10px var(--space-4) 12px",
                  borderBottom: "1px solid var(--line)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "0.01em",
                        lineHeight: 1.15, whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis" }}
               title={title}>
            {title.toUpperCase()}
          </div>
          <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                        marginTop: 3, whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>
            {base(dep)} <span style={{ color: "var(--ink-mute)" }}>→</span> {base(rec)}
          </div>
        </div>
        <button onClick={() => setOpen((o) => !o)} className="ms-chip"
                aria-expanded={open} aria-label="edit mission details"
                style={{ ...ghostButton, flex: "0 0 auto", minHeight: 30 }}
                title="mission number, tasking reference, launch time and name">
          EDIT
        </button>
      </div>

      {/* THE NUMBER AND THE CLOCK, WHICH ARE ALREADY FILLED IN.
          Both are generated when the console opens -- there is nothing to
          type before a route can be drawn -- and both are editable behind
          EDIT for the operator who has a real tasking reference to enter. */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                    marginTop: 7, fontSize: "var(--size-label)",
                    fontFamily: "var(--font-num)", color: "var(--ink-mute)",
                    whiteSpace: "nowrap", overflow: "hidden" }}>
        <span style={{ color: "var(--ink-dim)" }}>{identity.id}</span>
        {identity.tasking && <span>· {identity.tasking}</span>}
        <span style={{ marginLeft: "auto", flex: "0 0 auto" }}>
          <span style={{ fontFamily: "var(--font-ui)", letterSpacing: "0.08em",
                         marginRight: 6 }}>LAUNCH</span>
          <span style={{ color: "var(--ink-dim)" }}>
            {clockOf(identity.launch_utc)}
          </span>
        </span>
      </div>

      {open && (
        <IdentityEditor {...props} onClose={() => setOpen(false)} />
      )}
    </div>
  );
}

function clockOf(launch: string): string {
  const t = Date.parse(launch.length <= 16 ? launch + ":00Z" : launch);
  if (!isFinite(t)) return "—";
  const d = new Date(t);
  return String(d.getUTCHours()).padStart(2, "0") + ":"
    + String(d.getUTCMinutes()).padStart(2, "0") + "Z";
}

function IdentityEditor(props: {
  plan: MissionPlan;
  onPlan: (p: MissionPlan) => void;
  identity: MissionIdentity;
  onIdentity: (v: MissionIdentity) => void;
  locked: boolean;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const id = props.identity;
  const set = (patch: Partial<MissionIdentity>) =>
    props.onIdentity({ ...id, ...patch });

  /* Escape and a click outside both close it: it is a popover, not a mode. */
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") props.onClose(); };
    const down = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) props.onClose();
    };
    window.addEventListener("keydown", key);
    window.addEventListener("pointerdown", down, true);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("pointerdown", down, true);
    };
  }, [props]);

  const label: React.CSSProperties = {
    fontSize: "var(--size-label)", color: "var(--ink-mute)",
    letterSpacing: "0.09em", marginBottom: 4,
  };

  return (
    <div ref={box} className="ms-pop"
         style={{ position: "absolute", left: "var(--space-3)",
                  right: "var(--space-3)", top: "calc(100% - 4px)", zIndex: 30,
                  padding: "var(--space-4)", background: "var(--bg-panel)",
                  /* s14: a popover is edged, not shadowed. */
                  border: "1px solid var(--ink-mute)",
                  borderRadius: "var(--radius)",
                  display: "flex", flexDirection: "column",
                  gap: "var(--space-3)" }}>
      {/* THE TYPE IS THE TITLE, so it is changed where the title is.
          Picking one REBUILDS THE ROUTE from that template -- it is not a
          label on the sortie already drawn -- and the line underneath says
          so before the click rather than after it. */}
      <div>
        <div style={label}>MISSION TYPE</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {MISSION_TYPES.map((t) => (
            <Chip key={t.key} on={props.plan.type === t.key} title={t.blurb}
                  disabled={props.locked}
                  onClick={() => {
                    if (t.key === "CUSTOM") {
                      props.onPlan({ ...props.plan, type: "CUSTOM" });
                      return;
                    }
                    const p = props.plan;
                    const dep = p.points.find((q) => q.kind === "DEPARTURE");
                    const rec = [...p.points].reverse()
                      .find((q) => q.kind === "RECOVERY");
                    /* No fields yet: remember the type and wait for them,
                       rather than drawing it between two fields nobody chose.
                       withBase draws it when the second one is picked. */
                    if (!dep?.base_id || !rec?.base_id) {
                      props.onPlan({ ...p, type: t.key, airspeed_kmh: t.airspeed_kmh });
                      return;
                    }
                    props.onPlan(buildPlan(t, BASE_BY_ID[dep.base_id],
                                           BASE_BY_ID[rec.base_id], { ...p, name: "" }));
                  }}>
              {t.label}
            </Chip>
          ))}
        </div>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                      marginTop: 5, lineHeight: 1.45 }}>
          Choosing a type draws a fresh route of that shape between the two
          fields, as soon as both are chosen. Anything already drawn is replaced.
        </div>
      </div>

      <div>
        <div style={label}>MISSION NAME</div>
        <input value={props.plan.name} disabled={props.locked}
               aria-label="mission name" placeholder="name this sortie"
               onChange={(e) => props.onPlan({ ...props.plan, name: e.target.value })}
               style={{ ...inputStyle, minHeight: 34 }} />
      </div>
      <div style={{ display: "flex", gap: "var(--space-3)" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={label}>MISSION NUMBER</div>
          <input value={id.id} disabled={props.locked} aria-label="mission id"
                 onChange={(e) => set({ id: e.target.value.slice(0, 24) })}
                 style={{ ...inputStyle, minHeight: 34, fontWeight: 700,
                          fontFamily: "var(--font-num)" }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={label}>TASKING REF <span style={{ letterSpacing: 0 }}>
            · optional</span></div>
          <input value={id.tasking} disabled={props.locked}
                 aria-label="tasking reference" placeholder="—"
                 onChange={(e) => set({ tasking: e.target.value.slice(0, 24) })}
                 style={{ ...inputStyle, minHeight: 34 }} />
        </div>
      </div>
      <div>
        <div style={label}>LAUNCH · ZULU</div>
        <input type="datetime-local" value={id.launch_utc} disabled={props.locked}
               aria-label="planned launch, Zulu"
               onChange={(e) => set({ launch_utc: e.target.value })}
               style={{ ...inputStyle, minHeight: 34,
                        fontFamily: "var(--font-num)" }} />
      </div>
      {/* SAID ONCE, CALMLY, WHERE IT IS RELEVANT -- not as a warning under an
          empty field. The number and the time are real and usable; they are
          simply not filed anywhere, because there is nowhere to file them. */}
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    lineHeight: 1.5 }}>
        Generated for you and held in this console for the session. The API
        carries no mission store, so nothing here is filed anywhere — every ETA
        on the page is measured from the launch time.
      </div>
      <button onClick={props.onClose} className="ms-chip"
              style={{ ...ghostButton, alignSelf: "flex-end" }}>DONE</button>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * The four figures, and the four states
 * ------------------------------------------------------------------ */

export function Figures(props: { expansion: Expansion }) {
  const e = props.expansion;
  return (
    /* TWO BY TWO, NOT FOUR ACROSS. At the working width four cells are 95 px
       each, and "ON STATION" over "1 h 33 m" does not fit in 95 px at a 16 px
       type floor -- both the label and the figure were being clipped. The
       floor is not negotiable, so the grid is. */
    <div style={{ display: "grid", flex: "0 0 auto",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 1, background: "var(--line)",
                  borderBottom: "1px solid var(--line)" }}>
      <Figure k="distance" v={Math.round(e.distance_km).toLocaleString()} unit="km" />
      <Figure k="air time" v={fmtMin(e.air_minutes)}
              title="Distance over the ground at the planned airspeed. Geometry — the flight model adds the start, climb and landing." />
      <Figure k="on station" v={e.on_station_min > 0 ? fmtMin(e.on_station_min) : "—"} />
      <Figure k="waypoints" v={e.waypoints.length + " / 24"}
              tone={e.waypoints.length > 24 ? "var(--alert-warn)"
                : e.waypoints.length > 21 ? "var(--alert-caut)" : undefined} />
    </div>
  );
}

function Figure(props: { k: string; v: string; unit?: string; tone?: string;
                         title?: string }) {
  return (
    <div title={props.title}
         style={{ padding: "7px 10px 8px", background: "var(--bg-panel)",
                  minWidth: 0 }}>
      <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                    letterSpacing: "0.08em", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis" }}>
        {props.k.toUpperCase()}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <span className="mo-num"
              style={{ fontFamily: "var(--font-num)", fontSize: 19,
                       fontWeight: 700, color: props.tone ?? "var(--ink)",
                       whiteSpace: "nowrap" }}>
          {props.v}
        </span>
        {props.unit && (
          <span style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
            {props.unit}
          </span>
        )}
      </div>
    </div>
  );
}

const TILES: { group: Check["group"]; label: string }[] = [
  { group: "ROUTE", label: "route" },
  { group: "TERRAIN", label: "terrain" },
  { group: "FUEL", label: "fuel" },
  { group: "ENGINE", label: "engine" },
];

/* WHAT A TILE SAYS.
 *
 * A word where there is only a state to report, and THE FIGURE where there is
 * one -- an operator reading FUEL wants the litres, not the adjective, and
 * ENGINE means more as "0.64 POOR" than as "CHECK". The figure comes from the
 * same place the check did, so the tile and the finding under it can never
 * disagree. A tile whose source has not run says which thing has not run,
 * never a state that implies it passed. */
function tileValue(group: Check["group"], state: CheckState, lead: Check | null,
                   d: TileData): string {
  if (state === "PENDING") {
    return lead?.source === "flight" ? "NOT FLOWN" : "NOT COSTED";
  }
  if (state === "NA") return "—";
  if (group === "FUEL") {
    if (d.sim) return d.sim.fuel_used_l.toFixed(0) + " L USED";
    if (d.cost) return d.cost.fuel_l.toFixed(0) + " L";
  }
  if (group === "TERRAIN" && d.cost?.terrain?.available) {
    const legs = d.cost.terrain.legs ?? [];
    if (legs.length) {
      const worst = legs.reduce((m, l) => (l.margin_ft < m.margin_ft ? l : m));
      return Math.round(worst.margin_ft).toLocaleString() + " FT";
    }
  }
  if (group === "ENGINE") {
    const chi = d.snap?.display?.chi;
    if (typeof chi === "number") {
      return chi.toFixed(2) + (d.snap.display.band ? " " + d.snap.display.band : "");
    }
  }
  if (state === "FAIL") return "NO-GO";
  if (state === "CAUTION") return "CHECK";
  return "VALID";
}

interface TileData { cost: RouteCost | null; sim: FlightSim | null; snap: any }

export function StatusTiles(props: {
  checks: Check[];
  cost: RouteCost | null;
  sim: FlightSim | null;
  snap: any;
  onPick: (group: Check["group"]) => void;
}) {
  return (
    <div style={{ display: "grid", flex: "0 0 auto",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 1, background: "var(--line)",
                  borderBottom: "1px solid var(--line)" }}>
      {TILES.map((t) => {
        const st = groupState(props.checks, t.group);
        const lead = groupLead(props.checks, t.group);
        const hue = HUE[st];
        return (
          /* THE VALUE UNDER THE LABEL, NOT BESIDE IT. Side by side, a
             190 px tile has 79 px left for the value once the glyph and the
             word TERRAIN are in it, and "NOT COSTED" is 92 px at the type
             floor -- which is how a tile ends up reading "NOT CO...". */
          <button key={t.group} className="mo-tile"
                  onClick={() => props.onPick(t.group)}
                  title={lead ? lead.label + " — " + lead.detail
                              : "nothing to check yet"}
                  style={{ padding: "7px 10px 8px", textAlign: "left",
                           minWidth: 0, cursor: "pointer", border: "none",
                           borderLeft: "2px solid " + (st === "PENDING"
                             ? "var(--line)" : hue),
                           background: st === "PENDING" ? "var(--bg-panel)"
                             : "color-mix(in srgb, " + hue + " 7%, var(--bg-panel))",
                           fontFamily: "var(--font-ui)" }}>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-mute)",
                          letterSpacing: "0.08em", whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis" }}>
              {t.label.toUpperCase()}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 5,
                          color: hue, minWidth: 0 }}>
  <StatusSymbol level={LEVEL[st]} size={13} />
              <span style={{ minWidth: 0, fontSize: "var(--size-label)",
                             fontWeight: 700, letterSpacing: "0.03em",
                             whiteSpace: "nowrap", overflow: "hidden",
                             textOverflow: "ellipsis" }}>
                {tileValue(t.group, st, lead,
                           { cost: props.cost, sim: props.sim, snap: props.snap })}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
