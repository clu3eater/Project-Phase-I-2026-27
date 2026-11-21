/* THE SORTIE HAS AN END, AND THE STATION SAYS SO.
 *
 * The twin's flight used to finish on LANDING and hold it: the aircraft sat on
 * the runway at 110 km/h with the engine at 2,500 rpm for as long as the
 * station ran, and nothing ever said the flight was over. Now the engine is
 * shut down at the end of the sortie, the flight is written to the history
 * the moment it ends, and this card says what happened on it -- from the
 * flight record the post-flight report is built from, not from a summary
 * written for the card.
 *
 * It lives in the alert rail (Zone D) because that is the one region on every
 * page with room to spare once there are no alerts, and a finished flight is
 * the thing to read then. Nothing else on the page moves when it appears.
 */
import { can, type Snapshot } from "../lib/api";
import { Button } from "../ui/kit";
import { Status } from "../ui/status";

const clock = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

function Row(props: { k: string; v: string; tone?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8,
                  padding: "3px 0", borderBottom: "1px solid var(--line)",
                  fontSize: 16 }}>
      <span style={{ color: "var(--ink-dim)" }}>{props.k}</span>
      <span style={{ fontFamily: "var(--font-num)", color: props.tone ?? "var(--ink)",
                     textAlign: "right" }}>{props.v}</span>
    </div>
  );
}

export function SortieCard(props: { snap: Snapshot; onReport?: () => void;
                                   onDebrief?: () => void }) {
  const { snap } = props;
  const s: any = snap.sortie;
  if (!s || s.state !== "complete") return null;

  const fr = snap.flight_record ?? {};
  const exc: any[] = fr.exceedances ?? [];
  const dq = fr.data_quality ?? {};
  const a = snap.display?.assessment;
  const shutFor = s.ended_t_s != null ? Math.max(0, snap.t_s - s.ended_t_s) : 0;

  const ground = s.kind === "ground_run";

  return (
    <div data-testid="sortie-complete" className="well" style={{ marginBottom: "var(--space-3)" }}>
      <Status level="normal" size={17}
              text={`${ground ? "Ground run complete" : "Sortie complete"}${s.label && !ground ? ` · ${s.label}` : ""}`} />
      <div style={{ fontSize: 16, color: "var(--ink-dim)", margin: "4px 0 8px" }}>
        Engine shut down {clock(shutFor)} ago.
      </div>
      <Row k={ground ? "Run time" : "Flight time"} v={clock(s.flight_time_s)} />
      <Row k="Limits crossed" v={exc.length ? String(exc.length) : "none"}
           tone={exc.length ? "var(--alert-caut)" : undefined} />
      {exc.slice(0, 3).map((e, i) => (
        <Row key={i} k={`  ${e.parameter}`}
             v={`${e.peak} ${e.unit} · ${Math.round(e.seconds_above)} s`} />
      ))}
      <Row k="Health at end"
           v={snap.display?.chi != null
              ? `${Math.round(snap.display.chi * 100)} · ${snap.display.band ?? ""}`
              : "not assessed"} />
      {/* The trend across flights compares one stabilised cruise per flight;
          saying whether this flight produced one is saying whether it counts. */}
      <Row k="Trend point"
           v={dq.cruise_datum_captured ? "recorded" : "none: no stable cruise"}
           tone={dq.cruise_datum_captured ? undefined : "var(--ink-mute)"} />
      <Row k="Data coverage"
           v={dq.coverage_pct != null ? `${dq.coverage_pct} %` : "———"} />
      <Row k="Saved to history" v={s.recorded ? "yes" : "pending"} />
      {a?.state === "held" && (
        <div style={{ fontSize: 16, color: "var(--ink-mute)", marginTop: 6 }}>
          Health is the last warm assessment, held while the engine is off.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        {/* The next engine start is for the next approved mission, on the
            operator's Mission page, not a button here that flew on demand. */}
        {s.kind === "mission" && props.onDebrief && (
          <Button kind="primary" onClick={props.onDebrief}>Debrief</Button>
        )}
        {props.onReport && can("read:reports") && (
          <Button onClick={props.onReport}>View report</Button>
        )}
      </div>
    </div>
  );
}
