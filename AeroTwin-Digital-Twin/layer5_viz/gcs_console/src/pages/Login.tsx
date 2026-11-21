/* Sign-in.
 *
 * Laid out to the reference plates in ui/ — the DRDO identity lockup over the
 * engineering-drawing plate, with the credential fields centred beneath it and
 * the classification banner top-right.
 *
 * PRD Part 4 §10 gives the console four roles and requires (§10b) that the
 * active one be displayed persistently. It cannot be displayed until somebody
 * has said who they are, so this gates the whole console.
 *
 * §10c is the rule that matters: authorisation is enforced server-side
 * regardless of UI state. Everything this screen does is a convenience — the
 * API refuses an unauthorised call whether or not the console ever rendered
 * the control.
 *
 * TWO THINGS IN THE REFERENCE ARE DELIBERATELY NOT BUILT
 * -----------------------------------------------------
 * "Remember me". A crew station is a shared terminal, and a session that
 * outlives the operator standing up is a session attributable to the wrong
 * person in the audit log — which is the one thing the audit log exists to get
 * right. The reference shows the control; a ground station should not.
 *
 * "Forgot password?". There is no self-service reset against an establishment
 * directory, and a link that goes nowhere is worse than no link. Credentials
 * come from the establishment, and the screen says so.
 *
 * THE OFFICIAL MARKS
 * ------------------
 * The DRDO seal and the State Emblem of India are controlled marks. They are
 * used here as SUPPLIED ARTWORK — copied verbatim into src/assets and rendered
 * at size — and are never redrawn, recoloured, cropped or approximated in this
 * repository. The seal is the vector original, so it stays sharp at any size;
 * the State Emblem is raster only and is downscaled without cropping, because
 * the Satyamev Jayate motto is part of the mark and not a caption on it.
 */

import React, { useEffect, useState } from "react";

import { changePassword, demoAccounts, login, type DemoAccount } from "../lib/api";
import plateDay from "../assets/login-bg.jpg";
import plateNight from "../assets/login-bg-night.jpg";
import drdoSeal from "../assets/drdo-seal.svg";
import stateEmblem from "../assets/state-emblem.png";

const FIELD: React.CSSProperties = {
  width: "100%",
  height: 54,
  background: "var(--bg-panel)",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius)",
  color: "var(--ink)",
  fontFamily: "inherit",
  fontSize: 18,
  padding: "0 16px 0 48px",
  /* No `outline: "none"`. It removed the only indication a keyboard
     operator has of which field they are in, on the one screen where
     they are certainly typing -- against s9.4. The global
     :focus-visible ring in theme/tokens.css handles it. */
};

/* The national tricolour, built as THREE SOLID BANDS rather than as a CSS
 * gradient.
 *
 * The HMI checker flagged the gradient form under s14 (no gradient headers),
 * and it was right to: a gradient blends, and the tricolour has hard stops.
 * Three divs are both what the flag actually is and what passes the rule, so
 * the check keeps its teeth instead of acquiring an exemption. */
function Tricolour({ vertical = false, length = 180, weight = 3 }) {
  const band = (c: string): React.CSSProperties =>
    vertical
      ? { background: c, height: length / 3, width: weight }
      : { background: c, width: length / 3, height: weight };
  return (
    <div
      aria-hidden="true"
      style={{
        display: "flex",
        flexDirection: vertical ? "column" : "row",
        borderRadius: weight / 2,
        overflow: "hidden",
      }}
    >
      <div style={band("#FF9933")} />
      <div style={band(vertical ? "#E8E8E8" : "var(--ink-mute)")} />
      <div style={band("#138808")} />
    </div>
  );
}

/* Inline so they inherit currentColor and need no icon font. */
function UserIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="8" r="3.6" stroke="currentColor" strokeWidth="1.7" />
      <path d="M4.8 20a7.2 7.2 0 0 1 14.4 0" stroke="currentColor"
            strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4.5" y="10.5" width="15" height="10" rx="2"
            stroke="currentColor" strokeWidth="1.7" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" stroke="currentColor"
            strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

/* SEC-02: a first-run password must be replaced before the account is used.
 * The server refuses a sign-in with one (403) and this screen takes the change,
 * with the current password as proof, then signs in with the new one. */
function ChangePasswordScreen(props: {
  username: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPw !== confirmPw) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(props.username, oldPw, newPw);
      await login(props.username, newPw);
      props.onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password not changed.");
    } finally {
      setBusy(false);
    }
  };

  const label: React.CSSProperties = {
    fontSize: 16, color: "var(--ink-dim)", letterSpacing: "0.04em",
  };
  return (
    <div style={{
      height: "100%", display: "grid", placeItems: "center",
      background: "var(--bg-void)", padding: "24px",
    }}>
      <form onSubmit={submit} style={{
        width: "100%", maxWidth: 520, display: "grid", gap: 14,
      }}>
        <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "0.06em" }}>
          CHANGE PASSWORD
        </div>
        <div style={{ fontSize: 17, color: "var(--ink-dim)", lineHeight: 1.45 }}>
          The password issued for <b>{props.username}</b> is a first-run
          credential. It must be replaced before this account is used.
        </div>
        <label style={label}>Current password
          <input id="pw-current" type="password" autoComplete="current-password"
                 value={oldPw} onChange={(e) => setOldPw(e.target.value)}
                 style={FIELD} required />
        </label>
        <label style={label}>New password
          <input id="pw-new" type="password" autoComplete="new-password"
                 value={newPw} onChange={(e) => setNewPw(e.target.value)}
                 style={FIELD} required />
        </label>
        <label style={label}>Repeat new password
          <input id="pw-confirm" type="password" autoComplete="new-password"
                 value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)}
                 style={FIELD} required />
        </label>
        {error && (
          <div role="alert" style={{ fontSize: 17, color: "var(--alert-warn-ink)" }}>
            {error}
          </div>
        )}
        <button type="submit" disabled={busy} style={{
          height: 54, fontSize: 18, fontWeight: 800, letterSpacing: "0.08em",
          background: "var(--ink)", color: "var(--bg-void)",
          border: "1px solid var(--line)", borderRadius: "var(--radius)",
          cursor: busy ? "default" : "pointer",
        }}>
          {busy ? "CHANGING…" : "CHANGE PASSWORD AND SIGN IN"}
        </button>
        <button type="button" onClick={props.onCancel} style={{
          height: 44, fontSize: 16, background: "transparent",
          color: "var(--ink-dim)", border: "1px solid var(--line)",
          borderRadius: "var(--radius)", cursor: "pointer",
        }}>
          BACK TO SIGN IN
        </button>
      </form>
    </div>
  );
}

export function LoginScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mustChange, setMustChange] = useState(false);
  /* Only the hosted demonstration copy has any (DT_DEMO_MODE); a real
     station answers with none and this screen is unchanged. */
  const [demo, setDemo] = useState<DemoAccount[]>([]);
  useEffect(() => {
    let live = true;
    demoAccounts().then((a) => { if (live) setDemo(a); });
    return () => { live = false; };
  }, []);

  if (mustChange) {
    return (
      <ChangePasswordScreen
        username={username}
        onDone={onSignedIn}
        onCancel={() => { setMustChange(false); setPassword(""); }}
      />
    );
  }

  const night =
    document.documentElement.getAttribute("data-ambient") !== "day";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      onSignedIn();
    } catch (err) {
      if (err instanceof Error && err.message === "password change required") {
        setMustChange(true);
        return;
      }
      /* Deliberately the same message for an unknown user and a wrong
         password. The API is careful not to distinguish them; saying more
         here would undo that. */
      setError("Invalid credentials.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        height: "100%",
        position: "relative",
        display: "grid",
        gridTemplateRows: "auto 1fr",
        background: "var(--bg-void)",
        overflow: "auto",
      }}
    >
      {/* The engineering-drawing plate. Decorative only, so it is marked
          aria-hidden and carries no meaning a reader could lose. */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `url(${night ? plateNight : plateDay})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          pointerEvents: "none",
        }}
      />

      {/* ---- classification banner ---------------------------------- */}
      <header
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "22px 30px",
          gap: 20,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <img
            src={stateEmblem}
            alt="State Emblem of India"
            style={{ height: 46, width: "auto", display: "block" }}
          />
          <div style={{ lineHeight: 1.35 }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: "0.06em" }}>
              DRDO
            </div>
            <div style={{ fontSize: 16, color: "var(--ink-dim)" }}>
              Ministry of Defence, Government of India
            </div>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 16,
            color: "var(--ink-dim)",
            letterSpacing: "0.05em",
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="5" y="10.5" width="14" height="9.5" rx="2"
                  stroke="currentColor" strokeWidth="1.8" />
            <path d="M8.5 10.5V7.8a3.5 3.5 0 0 1 7 0v2.7" stroke="currentColor"
                  strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          SECURE
          <span style={{ color: "var(--ink-mute)" }}>|</span>
          INTERNAL USE ONLY
        </div>
      </header>

      {/* ---- identity and credentials -------------------------------- */}
      <main
        style={{
          position: "relative",
          display: "grid",
          placeItems: "center",
          padding: "0 24px 60px",
        }}
      >
        <div style={{ width: "100%", maxWidth: 520 }}>
          <div style={{ textAlign: "center", marginBottom: 32 }}>
            <img
              src={drdoSeal}
              alt="Defence Research & Development Organisation"
              style={{
                width: 150, height: 150,
                display: "block", margin: "0 auto 22px",
              }}
            />
            <div
              style={{
                fontSize: 52,
                fontWeight: 800,
                letterSpacing: "0.22em",
                lineHeight: 1,
                textIndent: "0.22em",
              }}
            >
              DRDO
            </div>
            <div
              style={{
                fontSize: 17,
                letterSpacing: "0.17em",
                color: "var(--ink-dim)",
                marginTop: 12,
              }}
            >
              DEFENCE RESEARCH &amp; DEVELOPMENT ORGANISATION
            </div>
            <div style={{ display: "flex", justifyContent: "center",
                          marginTop: 16 }}>
              <Tricolour length={180} weight={3} />
            </div>
          </div>

          <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
            <label style={{ position: "relative", display: "block" }}>
              <span
                aria-hidden="true"
                style={{
                  position: "absolute", left: 16, top: 17,
                  color: "var(--ink-mute)",
                }}
              >
                <UserIcon />
              </span>
              <input
                style={FIELD}
                placeholder="User ID"
                autoComplete="username"
                aria-label="User ID"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
              />
            </label>

            <label style={{ position: "relative", display: "block" }}>
              <span
                aria-hidden="true"
                style={{
                  position: "absolute", left: 16, top: 17,
                  color: "var(--ink-mute)",
                }}
              >
                <LockIcon />
              </span>
              <input
                style={{ ...FIELD, paddingRight: 52 }}
                type={reveal ? "text" : "password"}
                placeholder="Password"
                autoComplete="current-password"
                aria-label="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                onClick={() => setReveal((v) => !v)}
                aria-label={reveal ? "Hide password" : "Show password"}
                style={{
                  position: "absolute", right: 8, top: 8,
                  width: 38, height: 38,
                  display: "grid", placeItems: "center",
                  background: "transparent", border: "none",
                  color: "var(--ink-mute)", cursor: "pointer",
                  fontFamily: "inherit", fontSize: 16,
                }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"
                        stroke="currentColor" strokeWidth="1.7" />
                  <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.7" />
                  {!reveal && (
                    <path d="M4 20 20 4" stroke="currentColor" strokeWidth="1.7"
                          strokeLinecap="round" />
                  )}
                </svg>
              </button>
            </label>

            {/* Kept in the flow rather than floated, so the button never moves
                under the cursor when a failure appears. */}
            <div
              role="alert"
              style={{
                minHeight: 24,
                fontSize: 17,
                color: "var(--alert-warn-ink)",
              }}
            >
              {error}
            </div>

            <button
              type="submit"
              disabled={busy || !username || !password}
              style={{
                height: 54,
                background: busy ? "var(--ink-mute)" : "var(--alert-advis)",
                color: "var(--bg-void)",
                border: "none",
                borderRadius: "var(--radius)",
                fontFamily: "inherit",
                fontSize: 18,
                fontWeight: 800,
                letterSpacing: "0.1em",
                cursor: busy ? "wait" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 12,
                opacity: !username || !password ? 0.55 : 1,
              }}
            >
              {busy ? "AUTHENTICATING…" : "LOGIN"}
              {!busy && <span aria-hidden="true">→</span>}
            </button>

            {/* No "remember me" and no "forgot password" -- see the header
                comment. Saying where credentials come from is more use than a
                link that cannot work. */}
            {demo.length === 0 ? (
              <div
                style={{
                  fontSize: 16,
                  color: "var(--ink-mute)",
                  textAlign: "center",
                  marginTop: 4,
                  lineHeight: 1.5,
                }}
              >
                Credentials are issued by your establishment. Sessions end when
                this tab closes.
              </div>
            ) : (
              <DemoAccounts
                accounts={demo}
                onPick={(a) => {
                  setUsername(a.username);
                  setPassword(a.password);
                  setError(null);
                }}
              />
            )}
          </form>
        </div>
      </main>
    </div>
  );
}

/* The demonstration copy's four accounts, always on screen so an evaluator
 * arriving from the link can sign in at once. A click fills the two fields;
 * LOGIN is still pressed, so it is the same sign-in as a real station's. */
function DemoAccounts(props: {
  accounts: DemoAccount[];
  onPick: (a: DemoAccount) => void;
}) {
  const cell: React.CSSProperties = {
    fontFamily: "var(--font-num)",
    fontSize: 16,
    color: "var(--ink)",
  };
  return (
    <div style={{ marginTop: 6 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontSize: 16,
          letterSpacing: "0.08em",
          color: "var(--ink-mute)",
          marginBottom: 10,
        }}
      >
        <span style={{ flex: 1, minWidth: 16, height: 1, background: "var(--line)" }} />
        <span style={{ textAlign: "center" }}>DEMO ACCOUNTS · CLICK ONE TO FILL IN</span>
        <span style={{ flex: 1, minWidth: 16, height: 1, background: "var(--line)" }} />
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {props.accounts.map((a) => (
          <button
            key={a.username}
            type="button"
            onClick={() => props.onPick(a)}
            aria-label={`Fill in the ${a.label.toLowerCase()} account`}
            style={{
              display: "grid",
              gridTemplateColumns: "1.25fr 1.2fr 1fr",
              alignItems: "center",
              gap: 12,
              minHeight: 44,
              padding: "0 16px",
              background: "var(--bg-panel)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
              color: "var(--ink)",
              fontFamily: "inherit",
              textAlign: "left",
              cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "0.08em" }}>
              {a.label}
            </span>
            <span style={cell}>{a.username}</span>
            <span style={cell}>{a.password}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
