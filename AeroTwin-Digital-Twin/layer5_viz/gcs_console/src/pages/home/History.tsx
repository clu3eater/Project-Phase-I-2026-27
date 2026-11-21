/* The operator's own flown sorties. Replay sits beside it as a tab. */

import { useOpsBoard } from "../../lib/ops";
import { Empty, Section, utc } from "../../ui/kit";
import { Status, missionLevel, words } from "../../ui/status";

export function SortieHistory() {
  const { board } = useOpsBoard();
  const done = (board?.missions ?? []).filter((m) =>
    ["COMPLETED", "ABORTED", "CANCELLED"].includes(m.status));
  return (
    <div style={{ maxWidth: "var(--content-max)" }}>
      <Section title="Flown and closed missions">
        {done.length === 0 ? <Empty>No sortie flown yet.</Empty> : (
          <table className="table">
            <thead>
              <tr><th>Mission</th><th>Aircraft</th><th>Outcome</th>
                <th className="num">Engine h</th><th>Debrief</th><th>Closed</th></tr>
            </thead>
            <tbody>
              {done.map((m) => (
                <tr key={m.id}>
                  <td><b>{m.id}</b> {m.name}</td>
                  <td>{m.tail ?? "—"}</td>
                  <td><Status level={m.outcome === "ACCOMPLISHED" ? "normal" : missionLevel(m.status)}
                              text={words(m.outcome ?? m.status)} bold={false} /></td>
                  <td className="num">{m.engine_hours != null ? Number(m.engine_hours).toFixed(2) : "—"}</td>
                  <td className="t-dim">{m.debrief?.remarks || (m.cancel_reason ? `cancelled: ${m.cancel_reason}` : "")}</td>
                  <td className="t-dim t-num">{utc(m.completed_utc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}
