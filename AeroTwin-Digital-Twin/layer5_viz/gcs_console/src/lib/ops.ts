/* Squadron operations: the board every role's own page reads, and the
 * actions each role takes on it. See layer4_core/ops.py for the rules. */

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

export interface Aircraft {
  tail: string;
  twin_id: string;
  engine_key: string;
  engine_name: string;
  engine_validated: boolean;
  airframe: string;
  status: string;
  status_detail: string;
  grounding: string[];
  released: boolean;
  release_by: string | null;
  release_utc: string | null;
  release_note?: string;
  limitations: Record<string, any>;
  health: Record<string, any>;
  pending_maintenance: any[];
  open_defects: any[];
  sorties: number;
  ground_runs: number;
  mission: any | null;
  on_gcs: boolean;
}

export interface Board {
  unit: string;
  base: string;
  active_tail: string | null;
  busy: any | null;
  aircraft: Aircraft[];
  missions: any[];
  tasks: { page: string; urgency: number; text: string; mission?: string; tail?: string }[];
  mission_types: Record<string, any>;
  environments: string[];
  checklist: string[];
  operators: string[];
  inspection_interval_h: number;
  simulated_cruise_hours: number;
  live: any | null;
}

/** Where a "Waiting on you" task points: the aircraft or mission it is
 *  about. `n` changes on every click, so the same task opens it again. */
export interface Focus { tail?: string; mission?: string; n: number }

/* ONE BOARD FOR THE WHOLE CONSOLE.
 *
 * The status bar, the "waiting on you" rail and every squadron page read the
 * same board. Each page used to poll it on its own timer, so the rail and the
 * page could disagree for up to two seconds about the same aircraft. */
interface OpsState { board: Board | null; error: string | null; reload: () => void }
const OpsContext = createContext<OpsState>({ board: null, error: null, reload: () => {} });

export function OpsProvider({ children }: { children: React.ReactNode }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api("/api/ops/board")
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 403 ? "not available to your role"
                                                     : "squadron board unavailable");
        return r.json();
      })
      .then((b) => { setBoard(b); setError(null); })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    reload();
    const id = window.setInterval(reload, 2000);
    return () => window.clearInterval(id);
  }, [reload]);
  return React.createElement(OpsContext.Provider, { value: { board, error, reload } }, children);
}

/** The squadron board, re-read every two seconds. */
export function useOpsBoard(): OpsState {
  return useContext(OpsContext);
}

/** POST to the operations API. Resolves to the body, or throws the reason. */
export async function opsPost(path: string, body: any = {}): Promise<any> {
  const r = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  let data: any = null;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d
      : Array.isArray(d) ? d.map((x: any) => x.msg ?? JSON.stringify(x)).join("; ")
      : d?.problems ? d.problems.join("; ") : String(text).slice(0, 300));
  }
  return data;
}

export async function opsGet(path: string): Promise<any> {
  const r = await api(path);
  if (!r.ok) throw new Error((await r.text()).slice(0, 300));
  return r.json();
}

/** Colour for an aircraft status, on the console's alert palette. */
export function statusColour(status: string): string {
  switch (status) {
    case "SERVICEABLE": return "var(--state-normal)";
    case "UNSERVICEABLE": return "var(--alert-warn)";
    case "AWAITING INSPECTION": return "var(--alert-caut)";
    case "FLYING": case "ENGINE RUNNING": case "GROUND RUN": case "ON GCS":
      return "var(--alert-advis)";
    default: return "var(--ink-dim)";
  }
}

export function missionColour(status: string): string {
  switch (status) {
    case "PLANNED": return "var(--ink-dim)";
    case "APPROVED": return "var(--state-normal)";
    case "COMPLETED": return "var(--ink-mute)";
    case "CANCELLED": case "ABORTED": return "var(--ink-mute)";
    case "AWAITING_DEBRIEF": return "var(--alert-caut)";
    default: return "var(--alert-advis)";
  }
}

export const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(1)} %`;

export function healthColour(v: number | null | undefined): string {
  if (v == null) return "var(--ink-mute)";
  if (v >= 0.9) return "var(--state-normal)";
  if (v >= 0.75) return "var(--alert-caut)";
  return "var(--alert-warn)";
}

export const ACTION_NAMES: Record<string, string> = {
  A1: "Oil change / 100 h inspection",
  A2: "Cooling system flush",
  A3: "Injector cleaning / replacement",
  A4: "Spark plug replacement",
  A5: "Bearing inspection",
  A6: "Turbocharger inspection",
  A7: "Complete engine overhaul",
};
