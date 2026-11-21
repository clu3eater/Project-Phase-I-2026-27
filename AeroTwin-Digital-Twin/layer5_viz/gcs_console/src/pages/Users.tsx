/* USERS — the commander manages the station's accounts.
 *
 * The API had create, disable, change-role and revoke functions and no route
 * to any of them, so the four seeded accounts were all the station would ever
 * have: nobody could be added, a leaver could not be disabled, and a forgotten
 * password meant editing the credential store by hand. Every change here is
 * audited, forces the account to sign in again, and a new or reset password
 * must be changed at first sign-in.
 */

import React, { useCallback, useEffect, useState } from "react";

import { Panel } from "../components/Core";
import { ComparisonChart } from "../components/ComparisonChart";
import { api, session } from "../lib/api";
import { Button, Drawer, Field } from "../ui/kit";

const BTN: React.CSSProperties = {
  minHeight: 40, padding: "4px 10px", background: "transparent",
  color: "var(--ink)", border: "1px solid var(--line)",
  borderRadius: "var(--radius)", cursor: "pointer", fontSize: 16,
  fontFamily: "inherit",
};
const FIELD: React.CSSProperties = {
  minHeight: 44, padding: "6px 10px", background: "var(--bg-panel)",
  color: "var(--ink)", border: "1px solid var(--line)",
  borderRadius: "var(--radius)", fontSize: 16, fontFamily: "inherit",
};

/* What each role is FOR, so the commander assigning one knows what it gives. */
export const ROLE_DUTY: Record<string, string> = {
  ROLE_OPERATOR: "Flies the missions approved for them: prepares the allotted aircraft, "
    + "runs the checklist, starts the engine, launches, recalls, debriefs and reports snags.",
  ROLE_ENGINEER: "Reviews the defects the engine twin raises (confirm, defer, no fault found), "
    + "sets operating limitations, diagnoses trends, writes engine definitions.",
  ROLE_MAINTENANCE: "Keeps the aircraft airworthy: inspects and signs the maintenance release, "
    + "rectifies defects, records scheduled work, runs engines on the ground.",
  ROLE_COMMANDER: "Plans missions and allots aircraft and operators with the twin's reliability "
    + "verdict; engine changes, accounts and the audit log.",
};

async function detail(r: Response): Promise<string> {
  const t = await r.text();
  try { const d = JSON.parse(t).detail; return typeof d === "string" ? d : JSON.stringify(d); }
  catch { return t.slice(0, 300); }
}

export function UsersPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [nu, setNu] = useState({ username: "", password: "", role: "ROLE_OPERATOR" });
  const me = session()?.subject;

  const load = useCallback(() => {
    api("/api/users")
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 403 ? "Commander only." : "accounts unavailable");
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const [resetFor, setResetFor] = useState<string | null>(null);
  const [pw, setPw] = useState("");
  const change = async (username: string, body: any, what: string) => {
    const r = await api(`/api/users/${encodeURIComponent(username)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setMsg(r.ok ? { ok: true, text: `${username}: ${what}. They must sign in again.` }
                : { ok: false, text: `${username}: ${await detail(r)}` });
    load();
  };

  const create = async () => {
    const r = await api("/api/users", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(nu),
    });
    if (r.ok) {
      setMsg({ ok: true, text: `${nu.username} created as ${nu.role.replace("ROLE_", "")}. `
        + "They must change the password at first sign-in." });
      setNu({ username: "", password: "", role: nu.role });
    } else {
      setMsg({ ok: false, text: await detail(r) });
    }
    load();
  };

  if (error) return <Panel title="Accounts"><div style={{ color: "var(--alert-caut)" }}>{error}</div></Panel>;
  if (!data) return <Panel title="Accounts"><div style={{ color: "var(--ink-dim)" }}>ACQUIRING</div></Panel>;
  const roleChart = data.roles.map((role: string) => {
    const count = data.users.filter((u: any) => u.role === role).length;
    return { label: role.replace("ROLE_", ""), value: data.users.length
      ? (count / data.users.length) * 100 : 0,
      display: `${count} (${data.users.length ? Math.round((count / data.users.length) * 100) : 0}%)` };
  });

  return (
    <div className="role-admin-layout">
      <Panel title="Accounts" grow>
        {msg && (
          <div role="status" style={{
            marginBottom: 10, padding: "8px 12px", borderRadius: "var(--radius)", fontSize: 16,
            border: `1px solid ${msg.ok ? "var(--state-normal)" : "var(--alert-warn)"}`,
            color: msg.ok ? "var(--state-normal)" : "var(--alert-warn)",
          }}>{msg.text}</div>
        )}
        <div className="user-table-wrap table-scroll">
        <table className="user-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 16 }}>
          <thead>
            <tr style={{ color: "var(--ink-dim)", textAlign: "left" }}>
              <th style={{ padding: "6px 8px" }}>User</th>
              <th style={{ padding: "6px 8px" }}>Role</th>
              <th style={{ padding: "6px 8px" }}>State</th>
              <th style={{ padding: "6px 8px" }} />
            </tr>
          </thead>
          <tbody>
            {data.users.map((u: any) => (
              <tr key={u.username} style={{ borderTop: "1px solid var(--line)" }}>
                <td data-label="User" style={{ padding: "8px" }}>{u.username}{u.username === me ? " (you)" : ""}</td>
                <td data-label="Role" style={{ padding: "8px" }}>
                  <select value={u.role} disabled={u.username === me}
                          onChange={(e) => change(u.username, { role: e.target.value },
                                                  `role set to ${e.target.value.replace("ROLE_", "")}`)}
                          style={{ ...FIELD, minHeight: 40 }}>
                    {data.roles.map((r: string) => (
                      <option key={r} value={r}>{r.replace("ROLE_", "")}</option>
                    ))}
                  </select>
                </td>
                <td data-label="State" style={{ padding: "8px",
                             color: u.disabled ? "var(--alert-warn)" : "var(--ink-dim)" }}>
                  {u.disabled ? "DISABLED" : u.must_change ? "must change password" : "active"}
                </td>
                <td data-label="Actions" style={{ padding: "8px" }}>
                  <div className="user-table-actions">
                  {u.username !== me && (
                    <button style={BTN} onClick={() => change(
                      u.username, { disabled: !u.disabled }, u.disabled ? "enabled" : "disabled")}>
                      {u.disabled ? "ENABLE" : "DISABLE"}
                    </button>
                  )}
                  <button style={BTN} onClick={() => { setResetFor(u.username); setPw(""); }}>
                    RESET PASSWORD
                  </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Panel>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)", minHeight: 0 }}>
        <Panel title="Add an account">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input style={FIELD} placeholder="username, e.g. mt.kapoor" value={nu.username}
                   aria-label="New username"
                   onChange={(e) => setNu({ ...nu, username: e.target.value.toLowerCase() })} />
            <input style={FIELD} placeholder="temporary password" type="password"
                   aria-label="Temporary password" value={nu.password}
                   onChange={(e) => setNu({ ...nu, password: e.target.value })} />
            <select style={FIELD} value={nu.role} aria-label="Role"
                    onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {data.roles.map((r: string) => (
                <option key={r} value={r}>{r.replace("ROLE_", "")}</option>
              ))}
            </select>
            <button style={{ ...BTN, minHeight: 44 }}
                    disabled={!nu.username || !nu.password} onClick={create}>
              CREATE ACCOUNT
            </button>
          </div>
        </Panel>
        <Panel title="What each role does" grow>
          <ComparisonChart label="Accounts by role" items={roleChart} tone="neutral" />
          {Object.entries(ROLE_DUTY).map(([r, d]) => (
            <div key={r} style={{ marginBottom: 10, fontSize: 16 }}>
              <b>{r.replace("ROLE_", "")}</b>
              <div style={{ color: "var(--ink-dim)" }}>{d}</div>
            </div>
          ))}
        </Panel>
      </div>
      {resetFor && (
        <Drawer open title={`Reset password · ${resetFor}`}
                sub="They must change it when they next sign in, and every session they hold now ends."
                onClose={() => setResetFor(null)}
                footer={<>
                  <Button kind="quiet" onClick={() => setResetFor(null)}>Cancel</Button>
                  <Button kind="primary" disabled={pw.length < 12}
                          onClick={async () => {
                            await change(resetFor, { password: pw }, "password reset");
                            setResetFor(null);
                          }}>Reset password</Button>
                </>}>
          <Field label="Temporary password"
                 hint="12 or more characters, with three of: lower case, upper case, digits, symbols.">
            <input className="input" type="password" autoComplete="new-password" value={pw}
                   onChange={(e) => setPw(e.target.value)} />
          </Field>
        </Drawer>
      )}
    </div>
  );
}
