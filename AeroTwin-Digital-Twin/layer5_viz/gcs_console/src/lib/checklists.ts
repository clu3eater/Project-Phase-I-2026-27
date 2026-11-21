/* The abnormal procedures (configs/checklists.yaml), read once at sign-in.
 *
 * Held in memory and matched locally, so opening a checklist during an
 * emergency never waits on the network. */

import { useEffect, useState } from "react";

import { api } from "./api";

export interface Step { do: string; why?: string }
export interface Procedure {
  id: string; title: string; legends: string[];
  airborne: Step[]; ground: Step[];
}
export interface Checklists { source: string; procedures: Procedure[] }

let cache: Checklists | null = null;

const glob = (pat: string) =>
  new RegExp("^" + pat.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");

export function procedureFor(c: Checklists | null, legend: string): Procedure | null {
  if (!c) return null;
  return c.procedures.find((p) => p.legends.some((l) => glob(l).test(legend))) ?? null;
}

export function useChecklists(): Checklists | null {
  const [c, setC] = useState<Checklists | null>(cache);
  useEffect(() => {
    if (cache) return;
    api("/api/checklists")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) { cache = d; setC(d); } })
      .catch(() => undefined);
  }, []);
  return c;
}
