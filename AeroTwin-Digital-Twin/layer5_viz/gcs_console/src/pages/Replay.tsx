/* REPLAY -- PRD Part 4 s11 screen 5: transport, a scrubber with event
 * markers, the recorded trace, and the event log.
 *
 * TWO THINGS CAN BE REPLAYED, AND THEY ANSWER DIFFERENT QUESTIONS.
 *   Flights on this station   what happened on the sortie we just flew: the
 *                             station records every session, and each is
 *                             replayed from engine start to shutdown, with
 *                             take-off, landing, peaks and limit exceedances
 *                             found in the data (layer4_core/sortie_replay.py).
 *   Engine lives              whole recorded lives from the fleet data set,
 *                             for the engineer checking how early a fault was
 *                             visible (layer4_core/replay.py).
 * The page opened only on the second, so an operator who had just flown
 * found "no flights recorded" after every sortie.
 *
 * THE RULE THIS SCREEN IS BUILT AROUND (s7.3c): replayed history must never be
 * mistaken for live telemetry. A persistent REPLAY banner names what is shown
 * and the time within it; traces are dashed, never the solid stroke live data
 * uses (s7.4c).
 */

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { Button, Empty, Section, utc } from "../ui/kit";
import { type Level, Status, StatusSymbol, words } from "../ui/status";

interface Ev { x: number; kind: string; label: string; detail: string }
interface Loaded {
  title: string; source: string; xs: number[]; unit: "s" | "h";
  series: Record<string, (number | null)[]>; units: Record<string, string>;
  events: Ev[]; faults?: Record<string, boolean[]>;
}

const EVENT_LEVEL: Record<string, Level> = {
  exceedance: "caution", fault: "caution", health: "advisory", peak: "advisory",
  phase: "standby", residual: "standby",
};

const clock = (s: number) => {
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(r).padStart(2, "0")}`
    : `${m}:${String(r).padStart(2, "0")}`;
};

export function ReplayPage() {
  const [source, setSource] = useState<"flights" | "lives">("flights");
  const [flights, setFlights] = useState<any[] | null>(null);
  const [lives, setLives] = useState<any[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [data, setData] = useState<Loaded | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [idx, setIdx] = useState(0);
  const [speed, setSpeed] = useState(10);
  const [playing, setPlaying] = useState(false);
  const [channel, setChannel] = useState("");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api("/api/replay/flights").then((r) => (r.ok ? r.json() : [])).then((f) => {
      setFlights(f);
      if (f.length) setSel(f[0].id); else setSource("lives");
    }).catch(() => setFlights([]));
    api("/api/replay/sessions").then((r) => (r.ok ? r.json() : null)).then(setLives).catch(() => setLives(null));
  }, []);

  useEffect(() => {
    if (source === "lives" && lives?.length && !lives.some((l) => String(l.engine_id) === sel)) {
      setSel(String(lives[0].engine_id));
    }
    if (source === "flights" && flights?.length && !flights.some((f) => f.id === sel)) setSel(flights[0].id);
  }, [source, lives, flights]);

  useEffect(() => {
    if (!sel) return;
    setData(null); setErr(null); setIdx(0); setPlaying(false);
    const path = source === "flights" ? `/api/replay/flights/${sel}` : `/api/replay/${sel}`;
    api(path).then((r) => (r.ok ? r.json() : Promise.reject(new Error("Could not read this recording."))))
      .then((d) => {
        const loaded: Loaded = source === "flights" ? {
          title: `${d.tail} · ${sel?.split("_")[1] ? utc(isoFromStamp(sel.split("_")[1])) : ""}`,
          source: d.source, xs: d.t_s, unit: "s", series: d.series, units: d.units ?? {},
          events: d.events.map((e: any) => ({ x: e.t_s, kind: e.kind, label: e.label, detail: e.detail })),
        } : {
          title: `${d.tail} · recorded life of ${d.life_hours} h`, source: d.source, xs: d.hours, unit: "h",
          series: d.series, units: {}, faults: d.fault_active,
          events: d.events.map((e: any) => ({ x: e.hours, kind: e.kind, label: e.label, detail: e.detail })),
        };
        setData(loaded);
        const keys = Object.keys(loaded.series);
        setChannel(keys.includes("cht_max") ? "cht_max" : keys.includes("chi_true") ? "chi_true" : keys[0] ?? "");
      })
      .catch((e) => setErr(e.message));
  }, [sel, source]);

  // A fixed 100 ms tick advancing a variable distance, so the speeds differ in
  // distance covered rather than frame rate (s8.3).
  useEffect(() => {
    if (!playing || !data) return;
    const n = data.xs.length;
    const span = data.xs[n - 1] - data.xs[0];
    const perTick = data.unit === "s" ? speed * 0.1 : (speed / 10) * (span / Math.max(n, 1));
    const stride = Math.max(1, Math.round(perTick / Math.max(span / Math.max(n - 1, 1), 1e-9)));
    timer.current = window.setInterval(() => {
      setIdx((i) => {
        if (i + stride >= n - 1) { setPlaying(false); return n - 1; }
        return i + stride;
      });
    }, 100);
    return () => window.clearInterval(timer.current);
  }, [playing, speed, data]);

  const fmt = (x: number) => (data?.unit === "h" ? `${x.toFixed(1)} h` : clock(x));
  const now = data?.xs[idx] ?? 0;
  const next = useMemo(() => data?.events.find((e) => e.x > now) ?? null, [data, now]);
  const list = source === "flights" ? flights : lives;

  return (
    <div className="replay-page">
      <div className="replay-layout">
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="segmented" role="group" aria-label="What to replay">
            <button type="button" aria-pressed={source === "flights"} onClick={() => setSource("flights")}>
              Flights here</button>
            <button type="button" aria-pressed={source === "lives"} disabled={!lives}
                    title={lives ? "" : "No fleet data set on this station"}
                    onClick={() => setSource("lives")}>Engine lives</button>
          </div>
          <div className="card-flat" style={{ padding: 0, overflow: "hidden" }}>
            {list == null ? <div style={{ padding: 16 }}><Empty>Loading…</Empty></div>
              : list.length === 0 ? (
                <div style={{ padding: 16 }}>
                  <Empty>{source === "flights"
                    ? "Nothing flown on this station yet. Every sortie and ground run is recorded here once its engine has run."
                    : "No fleet data set on this station."}</Empty>
                </div>
              ) : list.map((x: any) => {
                const id = source === "flights" ? x.id : String(x.engine_id);
                return (
                  <button key={id} className="list-item" aria-current={id === sel} onClick={() => setSel(id)}>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <b>{x.tail}</b>
                        <span className="t-dim">{source === "flights" ? words(x.kind)
                          : x.censored ? "ran to TBO" : "failed"}</span>
                      </span>
                      <span className="t-dim" style={{ display: "block", marginTop: 2 }}>
                        {source === "flights"
                          ? `${utc(x.started_utc)} · engine ${clock(x.running_s)}${x.in_progress ? " · recording" : ""}`
                          : `${x.life_hours} h · ${x.faults.length ? `${x.faults.length} fault(s)` : "clean"}`}
                      </span>
                    </span>
                  </button>
                );
              })}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {err && <Section><Empty>{err}</Empty></Section>}
          {!data && !err && list && list.length > 0 && <Section><Empty>Reading the recording…</Empty></Section>}
          {data && (
            <>
              {/* s7.3c: persistent, full width, unmissable. */}
              <div className="well" style={{ display: "flex", gap: 20, alignItems: "baseline", flexWrap: "wrap" }}>
                <Status level="advisory" size={20} text="REPLAY, NOT LIVE" />
                <span className="t-dim">{data.title} · showing{" "}
                  <b className="t-num" style={{ color: "var(--ink)" }}>{fmt(now)}</b>{" "}
                  of {fmt(data.xs[data.xs.length - 1])} · {data.source}</span>
              </div>

              <Section>
                <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <Button kind="primary" onClick={() => {
                    if (idx >= data.xs.length - 1) setIdx(0);
                    setPlaying(!playing);
                  }}>{playing ? "Pause" : "Play"}</Button>
                  <div className="segmented" role="group" aria-label="Speed">
                    {(data.unit === "s" ? [1, 10, 60] : [1, 10, 100]).map((s) => (
                      <button key={s} type="button" aria-pressed={speed === s} onClick={() => setSpeed(s)}>{s}×</button>
                    ))}
                  </div>
                  <Button disabled={!next} onClick={() => {
                    if (!next) return;
                    const i = data.xs.findIndex((x) => x >= next.x);
                    if (i >= 0) setIdx(i);
                  }}>Next event{next ? `: ${next.label}` : ""}</Button>
                  <Button kind="quiet" onClick={() => { setIdx(0); setPlaying(false); }}>Rewind</Button>
                </div>

                <div style={{ marginTop: 20 }}>
                  <div style={{ position: "relative", height: 18, marginBottom: 4 }}>
                    {data.events.map((e, i) => (
                      <span key={i} title={`${fmt(e.x)}: ${e.label}${e.detail ? `, ${e.detail}` : ""}`}
                            style={{ position: "absolute", transform: "translateX(-50%)",
                                     left: `${pos(data, e.x)}%` }}>
                        <StatusSymbol level={EVENT_LEVEL[e.kind] ?? "standby"} size={14} />
                      </span>
                    ))}
                  </div>
                  <input type="range" min={0} max={Math.max(0, data.xs.length - 1)} value={idx}
                         onChange={(e) => setIdx(Number(e.target.value))} style={{ width: "100%" }}
                         aria-label="Position in the recording" />
                  <div className="t-dim t-num" style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>{fmt(data.xs[0])}</span><span>{fmt(data.xs[data.xs.length - 1])}</span>
                  </div>
                </div>
              </Section>

              <div className="replay-data-grid">
                <Section title="Recorded trace"
                         right={
                           <select className="input" style={{ width: "auto", minWidth: 200 }} value={channel}
                                   aria-label="Channel" onChange={(e) => setChannel(e.target.value)}>
                             {Object.keys(data.series).map((c) => <option key={c} value={c}>{words(c)}</option>)}
                           </select>
                         }>
                  <Trace data={data} values={data.series[channel] ?? []} idx={idx} />
                  <div className="t-dim" style={{ marginTop: 8 }}>
                    {words(channel)} at {fmt(now)}:{" "}
                    <b className="t-num" style={{ color: "var(--ink)" }}>
                      {data.series[channel]?.[idx] ?? "—"} {data.units[channel] ?? ""}</b>
                    {data.faults && (() => {
                      const on = Object.entries(data.faults).filter(([, a]) => a[idx]).map(([k]) => words(k));
                      return on.length ? <> · faults expressing: {on.join(", ")}</> : null;
                    })()}
                  </div>
                </Section>

                <Section title="At this moment">
                  <dl className="dl">
                    {Object.keys(data.series).filter((c) => c !== channel).slice(0, 10).map((c) => (
                      <Fragment key={c}><dt>{words(c)}</dt>
                        <dd className="t-num">{data.series[c]?.[idx] ?? "—"} {data.units[c] ?? ""}</dd></Fragment>
                    ))}
                  </dl>
                </Section>
              </div>

              <Section title="Events">
                {data.events.length === 0 ? <Empty>No events in this recording.</Empty> : (
                  <table className="table">
                    <tbody>
                      {data.events.map((e, i) => (
                        <tr key={i} className="row-click" style={{ opacity: e.x <= now ? 1 : 0.6 }}
                            onClick={() => { const j = data.xs.findIndex((x) => x >= e.x); if (j >= 0) setIdx(j); }}>
                          <td className="num" style={{ width: 90 }}>{fmt(e.x)}</td>
                          <td><Status level={EVENT_LEVEL[e.kind] ?? "standby"} text={e.label} bold={false} /></td>
                          <td className="t-dim">{e.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function isoFromStamp(stamp: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(stamp);
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z` : stamp;
}

function pos(d: Loaded, x: number): number {
  const lo = d.xs[0], hi = d.xs[d.xs.length - 1];
  return Math.min(99.5, Math.max(0.5, ((x - lo) / Math.max(hi - lo, 1e-9)) * 100));
}

/* The trace. Dashed throughout: s7.4c reserves the solid stroke for measured
 * live data, and this page has none. After the playhead it is dimmed, not
 * hidden, so nobody reads the end of the playback as the end of the record. */
function Trace({ data, values, idx }: { data: Loaded; values: (number | null)[]; idx: number }) {
  const W = 1000, H = 240, pad = 40;
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return <Empty>No data on this channel.</Empty>;
  const lo = Math.min(...nums), hi = Math.max(...nums), span = hi - lo || 1;
  const x = (i: number) => pad + (i / Math.max(values.length - 1, 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  const path = (from: number, to: number) => values.slice(from, to)
    .map((v, k) => (v == null ? null : `${x(from + k)},${y(v)}`)).filter(Boolean).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img"
         aria-label="Recorded trace">
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="var(--line)" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="var(--line)" />
      {data.events.map((e, i) => {
        const px = pad + (pos(data, e.x) / 100) * (W - 2 * pad);
        return <line key={i} x1={px} y1={pad} x2={px} y2={H - pad} strokeDasharray="2 4" strokeWidth={1}
                     stroke={e.kind === "exceedance" || e.kind === "fault" ? "var(--alert-caut)" : "var(--ink-mute)"}
                     opacity={0.6} />;
      })}
      <polyline points={path(idx, values.length)} fill="none" stroke="var(--ink-mute)" strokeWidth={1.5}
                strokeDasharray="6 4" opacity={0.5} />
      <polyline points={path(0, idx + 1)} fill="none" stroke="var(--ink)" strokeWidth={2} strokeDasharray="6 4" />
      <line x1={x(idx)} y1={pad} x2={x(idx)} y2={H - pad} stroke="var(--ref-selected)" strokeWidth={2} />
      <text x={pad} y={pad - 12} fill="var(--ink-dim)" fontSize={16} fontFamily="var(--font-num)">
        {hi.toFixed(1)}</text>
      <text x={pad} y={H - pad + 22} fill="var(--ink-dim)" fontSize={16} fontFamily="var(--font-num)">
        {lo.toFixed(1)}</text>
    </svg>
  );
}
