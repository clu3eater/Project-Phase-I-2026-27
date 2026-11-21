/* The screens of PRD Part 4 section 11. */

import { useEffect, useState } from "react";
import {
  Snapshot,
  Measurement,
  api,
  fetchReport,
} from "../lib/api";
import { KeyValue, Panel, Trend } from "../components/Core";
import { EngineModel } from "../components/EngineModel";
import { Cylinders } from "./detail/Cylinders";
import { CommanderParameters } from "./detail/CommanderParameters";

/* A grid of panels that stay READABLE rather than staying in one row.
 *
 * The prognostics page asked for five fixed columns. On any real console that
 * gives each panel a column narrower than a sentence, so the text sets in tall
 * thin ribbons of two or three words a line and one panel drags the row down
 * past the bottom of the screen while its neighbours sit half empty -- which
 * is exactly what it did.
 *
 * `min` is the narrowest a panel may be before the grid drops a column, so the
 * layout reflows instead of crushing. `cap` bounds the height of a row: the
 * Panel body already scrolls, so a panel with more content than fits scrolls
 * inside itself rather than stretching the page.
 */
const panels = (min: number): React.CSSProperties => ({
  display: "grid",
  // A compressed grid child still reports its full scrollHeight to the page
  // unless the overflow is contained here; that leak was the last 90 px.
  overflow: "hidden",
  gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
  // `cap` bounded a row and nothing made the grid fill the page, so a page
  // whose panels were shorter than the cap simply stopped: the mission page
  // used the top third of a 1080-line display and left the rest empty. On a
  // fixed GCS panel that is capability thrown away -- MIL-STD-1472H 5.4.3.4
  // wants information grouped and dense, not floated at the top.
  //
  // minmax(cap, 1fr) keeps the cap as the MINIMUM a row may claim and lets
  // rows share whatever is left, so short pages fill and long ones still
  // scroll inside their panels rather than dragging the page down.
  // `minmax(min(cap,100%), 1fr)` fills a short page, and on a page with two
  // or more rows it also GUARANTEES overflow: two rows of a 460 px minimum is
  // 920 px against the 824 a 1080-line display leaves for the work area.
  // Measured before this: PROGNOSTICS ran 580 px past the bottom, HEALTH and
  // REPORT 108 px each.
  //
  // `minmax(0, 1fr)` still fills the page -- 1fr is what does the filling --
  // but lets the rows SHARE the height they actually have, and a panel whose
  // content does not fit scrolls its own body and says so, which is where the
  // overflow belongs. `cap` survives as the documented intent for a future
  // single-row page that wants a floor -- it is not needed to fill one.
  gridAutoRows: "minmax(0, 1fr)",
  gap: "var(--gap)",
  alignItems: "stretch",
  height: "100%", minHeight: 0,
});

function m(snap: Snapshot, path: string): Measurement | undefined {
  return path.split(".").reduce((o: any, k) => (o ? o[k] : undefined), snap.twin.reported);
}

/* ------------------------------------------------------------------------ */
/* 1. ENGINE                                                                 */
/* ------------------------------------------------------------------------ */

export function EnginePage({ snap, limits, partFocus, unifiedLayout = true }: {
  snap: Snapshot; limits: any;
  unifiedLayout?: boolean;
  /** A component the operator asked for from another view -- today the
   *  Health page's cylinder balance. Carried by the shell. */
  partFocus?: { componentId: string; n: number } | null;
}) {
  const r = snap.twin.reported;
  const p = limits?.parameters ?? {};
  const cyl = (g: "cht" | "egt", i: number) => r[g]?.[`cyl_${i}`]?.value ?? null;
  // The speed-dependent oil-pressure minimum moved to Zone B with the
  // readout it belongs to (App.tsx).
  const [picked, setPicked] = useState<string | null>(null);

  /* A secondary reading with its value state, compact enough for ten of them
   * to share one panel. The number keeps --size-readout (s5.1's 30 px floor);
   * what is compact is the box around it, not the character height. */
  const mini = (label: string, meas: Measurement | undefined, unit: string,
                digits = 1) => {
    const st = meas?.state;
    const shown = st === "INVALID" || st === "MISSING" || meas?.value == null
      ? "———" : meas.value.toFixed(digits);
    return (
      <div key={label} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)",
                                minWidth: 0 }}>
        <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)",
                      letterSpacing: "0.06em", display: "flex",
                      justifyContent: "space-between", gap: 6 }}>
          <span>{label}</span>
          {st && st !== "VALID" && (
            <span style={{ color: "var(--alert-caut)" }}>{st}</span>
          )}
        </div>
        <div style={{ fontFamily: "var(--font-num)", fontSize: "var(--size-readout)",
                      lineHeight: 1.1, whiteSpace: "nowrap" }}>
          {shown}
          <span style={{ fontSize: 16, color: "var(--ink-dim)" }}> {unit}</span>
        </div>
      </div>
    );
  };
  const derived = (v: number | null | undefined): Measurement => ({
    value: v ?? null, state: v == null ? "MISSING" : "VALID", age_s: null, reason: "",
  } as any);

  if (unifiedLayout) return <CommanderParameters snap={snap} limits={limits} partFocus={partFocus} />;

  return (
    /* ONE SCREEN, THREE COLUMNS.
       The page was a single column -- engine and cylinder cards, a strip of
       five readouts, a full-width vibration table, five more readouts -- and
       the three panels at the bottom were left 24-42 px tall: cylinder
       temperatures, measured-vs-prediction and measured-minus-as-new all but
       invisible behind MORE BELOW, and the 3D engine a 170 px thumbnail. The
       engine now takes the full height of its own column; the cylinder cards
       and the cylinder bars (the same eight numbers, twice) are one table;
       the ten secondary readings share one panel; the model comparison keeps
       its chart and its differences together. */
    <div className="engine-telemetry-grid">
      {/* THE ENGINE, WITH THE DETECTED FAULT ON THE PART.
          Driven by the network's fault probabilities, not by the simulator's
          injected truth: a fault the twin has not found is not lit here. The
          component ids come from the same registry the highlight uses, so a
          click reports the part the operator actually pointed at. RPM, CHT
          max, EGT max and OIL PRESS are in Zone B above, on every page, and
          are not repeated here. */}
      <div className="engine-telemetry-visual">
        <Panel grow title="Engine — detected faults on the part"
               right={<span style={{ fontSize: 16, color: "var(--ink-dim)" }}>
                 {picked ? picked.replace(/^ROTAX_915IS_/, "").replace(/_/g, " ")
                         : "click a part to identify it"}
               </span>}
               bodyStyle={{ display: "flex", flexDirection: "column" }}>
          <EngineModel snap={snap} onSelect={setPicked} focusPart={partFocus ?? null} />
        </Panel>
      </div>

      <Panel title="Cylinders"
             right={<span style={{ fontSize: 16, color: "var(--ink-dim)" }}>
               spread CHT {r.cht?.spread?.toFixed(1) ?? "—"} · EGT {r.egt?.spread?.toFixed(0) ?? "—"} °C
             </span>}
             bodyStyle={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <Cylinders
          cht={(i) => cyl("cht", i)}
          egt={(i) => cyl("egt", i)}
          chtLimit={p.cht ?? null}
          egtLimit={p.egt ?? null}
        />
      </Panel>

      {/* PS section B names EIGHT parameter groups. ALTERNATOR CURRENT and
          INJECTION TIMING were carried on the bus and on no screen; timing is
          shown as DEVIATION FROM COMMANDED, the comparison that makes it mean
          something. COOLANT is in the model comparison opposite. */}
      <Panel title="Engine systems">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                      columnGap: "var(--space-3)" }}>
          {mini("OIL TEMP", m(snap, "oil_temperature"), "°C")}
          {mini("FUEL FLOW", m(snap, "fuel_flow"), "L/h")}
          {mini("MANIFOLD", m(snap, "manifold_pressure"), "bar", 2)}
          {mini("VIBRATION", derived(r.vibration?.rms_total), "m/s²", 2)}
          {mini("BUS VOLTS", m(snap, "electrical.bus_voltage"), "V")}
          {mini("ALT CURRENT", m(snap, "electrical.alternator_current"), "A")}
          {mini("INJ TIMING DEV", derived(r.timing?.injection_deviation_max), "°", 2)}
          {mini("IGN TIMING DEV", derived(r.timing?.ignition_deviation_max), "°", 2)}
          {mini("INJ DUTY", m(snap, "timing.injector_duty_pct"), "%")}
          {mini("KNOCK RETARD", m(snap, "timing.knock_retard_deg"), "°")}
        </div>
      </Panel>

      {/* PS section B "vibration signatures" and section C "abnormal vibration
          patterns" (PS1-09). Each defect order against the envelope floor it
          is judged on, with its meaning in words. */}
      <Panel title="Vibration — order analysis">
        {r.vibration?.spectral_peaks
          && Object.keys(r.vibration.spectral_peaks).length > 0 ? (
          <>
            {[
              ["BPFO", "outer race"], ["BPFI", "inner race"],
              ["BSF", "rolling element"], ["FTF", "cage"],
            ].map(([k, what]) => {
              const x = r.vibration.spectral_peaks[k];
              return (
                <KeyValue key={k} k={`${k} · ${what}`}
                          v={x == null ? "—" : `${Number(x).toFixed(2)} × floor`} />
              );
            })}
            {Object.entries(r.vibration.spectral_peaks)
              .filter(([k]) => !["BPFO", "BPFI", "BSF", "FTF"].includes(k))
              .map(([k, x]) => (
                <KeyValue key={k} k={k} v={`${Number(x).toFixed(2)} ×`} dim />
              ))}
            <KeyValue k="Dominant frequency"
                      v={r.vibration?.dominant_frequency_hz == null ? "—"
                        : `${Number(r.vibration.dominant_frequency_hz).toFixed(1)} Hz`} />
          </>
        ) : (
          <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
            No order analysis yet: it runs in stabilised cruise, above idle.
          </div>
        )}
      </Panel>

      {/* THE TWIN'S OWN COMPARISON: the head temperature measured against the
          as-new model, and every channel's difference from it. Differences
          in degC, signed, like every temperature on this console. */}
      <Panel title="Measured vs as-new model">
        {(snap.twin.simulated?.outside_manufacturer_data ?? []).length > 0 && (
          <div style={{ marginBottom: 6, fontSize: 16, color: "var(--ink-dim)" }}>
            Outside manufacturer data:{" "}
            {snap.twin.simulated.outside_manufacturer_data.join("; ")}
          </div>
        )}
        <Trend series={snap.history.cht} predicted={snap.history.cht_pred}
               label="Head temp — measured ──  model ╌╌" unit="°C" height={96} />
        {[
          ["Cyl head", snap.twin.residuals.cht, "°C"],
          ["Coolant", snap.twin.residuals.coolant, "°C"],
          ["EGT", snap.twin.residuals.egt, "°C"],
          ["Oil pressure", snap.twin.residuals.oil_pressure, "psi"],
          ["Fuel flow", snap.twin.residuals.fuel_flow, "L/h"],
        ].map(([label, res, unit]: any) => (
          <KeyValue key={label} k={label as string}
                    dim={!res?.usable}
                    v={res?.usable && res.mean_delta !== null
                      ? `${res.mean_delta >= 0 ? "+" : ""}${res.mean_delta.toFixed(2)} ${unit}`
                      : "not available"} />
        ))}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* 2. HEALTH                                                                 */
/* ------------------------------------------------------------------------ */

/* ------------------------------------------------------------------------ */
/* 5. MISSION -- moved                                                       */
/* ------------------------------------------------------------------------ */

/* MissionPage lived here: a route planner (components/RouteMap) above a
 * Go / No-Go table by mission profile. Both have moved.
 *
 * The planner is now `missionops/` -- the same job, with a mission that can be
 * checked, flown through the engine model, played back, and compared against
 * itself under a fault that belongs to the simulation and never touches the
 * running twin. It is registered as `V.planning` in App.tsx, in the slot this
 * page held, under the same `read:mission` scope and the same
 * `legacy: "MISSION"` id, so `go("MISSION")` still lands on a planner.
 *
 * The Go / No-Go table by profile is not lost: `GoNoGo` in mission/Analysis
 * renders it inside that page's CHECKS tab, beside the checks for the route
 * actually drawn.
 */

/* ------------------------------------------------------------------------ */
/* 6. REPORT                                                                 */
/* ------------------------------------------------------------------------ */

/* The report as a filed document.
 *
 * The PDF route is authenticated like every other, so it cannot simply be an
 * <a href>: a plain link carries no Authorization header and would 401. The
 * bytes are fetched with the token, turned into a blob URL and opened, and the
 * blob URL is revoked afterwards so the document does not sit in memory for
 * the rest of the session.
 */
function ExportPdf() {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  /* THREE FORMATS OF THE SAME REPORT.
   *
   * All three are built from the same /api/report payload, and each carries a
   * SHA-256 that matches the audit row recording that export. It does NOT
   * follow that a CSV and a PDF pulled a minute apart will match: each request
   * generates a fresh report from the live twin, so the timestamp and the
   * values differ and so do the digests. The digest ties an export to its own
   * audit entry, which is a narrower and true claim.
   *
   * PDF opens in a tab -- it is meant to be READ. CSV and JSON download, because
   * they are meant to be OPENED IN SOMETHING ELSE. */
  const save = async (fmt: "pdf" | "csv" | "json") => {
    setBusy(fmt);
    setErr(null);
    try {
      const r = await api(`/api/report.${fmt}`);
      if (!r.ok) {
        const e = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(e.detail ?? "export failed");
      }
      const url = URL.createObjectURL(await r.blob());
      if (fmt === "pdf") {
        window.open(url, "_blank", "noopener");
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = `postflight.${fmt}`;
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setBusy(null);
    }
  };

  const BTN: React.CSSProperties = {
    background: "transparent",
    color: "var(--ink-dim)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius)",
    padding: "5px 11px",
    fontSize: 16,
    fontFamily: "inherit",
    letterSpacing: "0.04em",
    minHeight: 34,
  };

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {err && (
        <span style={{ fontSize: 16, color: "var(--alert-caut)" }}>{err}</span>
      )}
      {(["pdf", "csv", "json"] as const).map((f) => (
        <button
          key={f}
          onClick={() => save(f)}
          disabled={busy !== null}
          style={{ ...BTN, cursor: busy ? "wait" : "pointer",
                   opacity: busy && busy !== f ? 0.4 : 1 }}
        >
          {busy === f ? "…" : f.toUpperCase()}
        </button>
      ))}
    </span>
  );
}

export function ReportPage() {
  const [rep, setRep] = useState<any>(null);
  useEffect(() => {
    const load = () => fetchReport().then(setRep).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  if (!rep) return <Panel title="Mission report">Loading…</Panel>;

  return (
    <div style={panels(380)}>
      <Panel title="Mission" right={<ExportPdf />}>
        <KeyValue k="Twin" v={rep.twin_id} />
        <KeyValue k="Aircraft" v={rep.aircraft_id} />
        <KeyValue k="Engine" v={rep.engine} />
        <KeyValue k="Generated" v={rep.generated_utc} />
        <KeyValue k="Simulated time" v={`${rep.mission.simulated_seconds} s`} />
        <KeyValue k="Flight hours" v={rep.mission.flight_hours} />
        <KeyValue k="Start-stop cycles" v={rep.mission.start_stop_cycles} />
        <KeyValue k="Thermal cycles" v={rep.mission.thermal_cycles} />
        <KeyValue k="TBO hours remaining" v={rep.tbo_hours_remaining} />
        <KeyValue k="Data quality" v={`${(rep.data_quality * 100).toFixed(1)} %`} />
      </Panel>
      <Panel title="Life-to-date extremes">
        <KeyValue k="Max CHT" v={`${rep.extremes.max_cht_c?.toFixed(1) ?? "—"} °C`} />
        <KeyValue k="Max coolant" v={`${rep.extremes.max_coolant_c?.toFixed(1) ?? "—"} °C`} />
        <KeyValue k="Max EGT" v={`${rep.extremes.max_egt_c?.toFixed(0) ?? "—"} °C`} />
        <KeyValue k="Max RPM" v={rep.extremes.max_rpm?.toFixed(0) ?? "—"} />
        <KeyValue k="Max vibration" v={`${rep.extremes.max_vibration?.toFixed(2) ?? "—"} m/s²`} />
        <KeyValue k="Above max continuous"
                  v={`${rep.extremes.time_above_max_continuous_s?.toFixed(0) ?? 0} s`} />
      </Panel>
      <Panel title="Assessment">
        <KeyValue k="Health index"
                  v={typeof rep.health.chi === "number"
                     ? (rep.health.chi as number).toFixed(3) : "not assessed"} />
        <KeyValue k="Band" v={rep.health.band} />
        {/* The interval shown must belong to the estimate shown (HMI-06): the
            physics interval only when physics is the source. */}
        <KeyValue k="Remaining life"
                  v={!rep.remaining_life.reportable ? "not determinable"
                    : rep.remaining_life.source !== "lstm"
                      && rep.remaining_life.lower != null && rep.remaining_life.upper != null
                      ? `${Math.round(rep.remaining_life.hours)} h [${Math.round(rep.remaining_life.lower)}–${Math.round(rep.remaining_life.upper)}]`
                      : `${Math.round(rep.remaining_life.hours)} h (network, no calibrated interval)`} />
        {rep.remaining_life.decision_floor_hours != null && (
          <KeyValue k="Planned on"
                    v={`${Math.round(rep.remaining_life.decision_floor_hours)} h`} dim />
        )}
        <KeyValue k="Advisory" v={rep.advisory.severity} />
        <div style={{ marginTop: 8, fontSize: 16 }}>{rep.advisory.recommended_action}</div>
        <div style={{ marginTop: 4, fontSize: 16, color: "var(--ink-dim)" }}>
          {rep.advisory.time_to_action}
        </div>
        {/* Same guard as the simulation page: a report fetched by a role
            that may not see injected faults carries an object here, and
            .length on it is undefined rather than an error -- so the crash
            landed one line later, on .map. */}
        {Array.isArray(rep.faults_injected) && rep.faults_injected.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: "var(--size-label)", color: "var(--ink-dim)" }}>
              INJECTED FAULTS (demonstration)
            </div>
            {rep.faults_injected.map((f: any, i: number) => (
              <KeyValue key={i} k={f.mode.replace(/_/g, " ")}
                        v={f.severity.toFixed(2)} dim />
            ))}
          </div>
        )}
      </Panel>
      {/* The report's own maintenance actions and cross-flight trend (HMI-08).
          Both reached the PDF and never the screen, so the on-screen report
          named no action and no drift. */}
      <Panel title="Maintenance actions">
        {(rep.actions ?? []).length === 0 ? (
          <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
            No maintenance action was raised on this flight.
          </div>
        ) : (
          (rep.actions ?? []).map((a: any, i: number) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <KeyValue k={a.action ?? "Action"} v={a.deadline ?? "—"} />
              <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
                {[a.ata, a.cost].filter(Boolean).join(" · ")}
              </div>
              {a.evidence && (
                <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>{a.evidence}</div>
              )}
            </div>
          ))
        )}
      </Panel>
      <Panel title="Trend across flights">
        {((rep.trend ?? {}).series ?? []).length === 0 ? (
          <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
            {(rep.trend ?? {}).reason ?? "Not enough comparable flights yet."}
          </div>
        ) : (
          <>
            {/* THE CAVEAT IS SAID ONCE, AND THE DATA IS SHOWN.
                Every row used to read "change only, span too short for a rate"
                whenever the flights so far did not span enough hours to divide
                by -- so six rows carried six copies of one sentence and not a
                single number, which reads as filler rather than as a
                measurement. The series already carries `change` and
                `span_hours`; those are real and are what there is to show. */}
            {(rep.trend.series as any[]).some((t: any) => t.drift_per_100h == null) && (
              <div style={{ fontSize: 16, color: "var(--ink-mute)",
                            marginBottom: "var(--space-2)" }}>
                Change since the first comparable flight
                {rep.trend.series[0]?.span_hours != null
                  ? ` (${Number(rep.trend.series[0].span_hours).toFixed(1)} h apart)`
                  : ""}
                . A per-100-hour rate needs a longer span than that.
              </div>
            )}
            {(rep.trend.series as any[]).map((t: any, i: number) => (
              <KeyValue key={i} k={t.name}
                        v={t.drift_per_100h == null
                          ? (t.change == null ? "—"
                            : `${t.change > 0 ? "+" : ""}${Number(t.change).toFixed(1)} ${t.unit ?? ""}`)
                          : `${t.drift_per_100h > 0 ? "+" : ""}${Number(t.drift_per_100h).toFixed(1)} ${t.unit ?? ""} / 100 h`
                            + (t.reach_limit_h != null ? ` · limit in ${Math.round(t.reach_limit_h)} h` : "")} />
            ))}
          </>
        )}
      </Panel>
    </div>
  );
}
