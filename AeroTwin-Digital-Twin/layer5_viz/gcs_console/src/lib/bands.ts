/* WHICH BAND A READING HAS ACTUALLY REACHED.
 *
 * Pulled out of the figure components so it is a pure function with no React
 * in it, and so the truth table below can be exercised directly.
 *
 * THE COMPARISONS ARE STRICT, AND THAT IS NOT A STYLE CHOICE.
 *
 * The console's rule is that a figure can never disagree with the alert
 * engine. The alert engine is layer1_edge/edge_rules.py, and it trips
 * strictly:
 *
 *     edge_rules.py:211   trip = value > self.limit        # direction "above"
 *     edge_rules.py:214   trip = value < self.limit        # direction "below"
 *
 * so a reading sitting exactly ON a limit does NOT raise an alert. An earlier
 * version of this used `>=`, which disagreed with the engine in two places
 * that were live on screen:
 *
 *   - the battery. A pack at 100 % state of health was painted in warning red
 *     and captioned OVER LIMIT, because the card passed critical_max: 100 and
 *     100 >= 100.
 *   - oil pressure. This engine defines normal_max and alert_max at the SAME
 *     figure (both 72.5 psi), so a reading at the top of its normal range
 *     escalated to caution while the engine said nothing.
 *
 * THE LOW SIDE IS BANDED TOO, WHICH IT WAS NOT.
 *
 * The old Limit type had no alert_min or critical_min, so a reading below its
 * floor fell through to "normal" or was drawn in the mute grey that means
 * "inactive / unavailable". Oil pressure publishes alert_min 29.0 psi, and
 * edge_rules.py raises on it; the figure showed nothing. A low reading is now
 * a band like any other.
 */

export interface Limit {
  normal_min?: number | null;
  normal_max?: number | null;
  alert_min?: number | null;
  critical_min?: number | null;
  alert_max?: number | null;
  critical_max?: number | null;
  range?: [number, number] | null;
}

/* "below" and "above" are OUTSIDE THE NORMAL BAND BUT NOT ALERTING. They are
 * kept apart because they are not the same statement and the UI says them out
 * loud: this engine's vibration sits normal to 3.5 and alerts over 5.0, so a
 * reading of 5.0 is above its normal band with the alert engine still silent.
 * A single "low" for both directions put the word and the colour for the wrong
 * one on screen -- the truth table caught it naming 5.0 m/s2 "low". */
export type Band = "none" | "below" | "normal" | "above" | "caution" | "warning";

/** The band `v` sits in, by the same comparisons the alert engine uses. */
export function bandOf(v: number | null | undefined, lim?: Limit | null): Band {
  if (v == null || !Number.isFinite(v) || !lim) return "none";

  // Critical first, either side: the worst true statement wins.
  if (lim.critical_max != null && v > lim.critical_max) return "warning";
  if (lim.critical_min != null && v < lim.critical_min) return "warning";

  if (lim.alert_max != null && v > lim.alert_max) return "caution";
  if (lim.alert_min != null && v < lim.alert_min) return "caution";

  // Outside the normal envelope, with the alert engine silent. Worth showing,
  // and it must NOT be coloured as an alert.
  if (lim.normal_min != null && v < lim.normal_min) return "below";
  if (lim.normal_max != null && v > lim.normal_max) return "above";

  return "normal";
}

/** Ink for a band.
 *
 * `below` and `above` are deliberately NOT the unavailable grey: a reading
 * outside its normal envelope is a real measurement, not a missing one, and
 * --ink-mute means "inactive / unavailable". They take the non-alert data
 * colour instead, which is the one thing on this page that means "this is a
 * measurement" without claiming anything is wrong. */
export function bandInk(b: Band): string {
  switch (b) {
    case "warning": return "var(--alert-warn)";
    case "caution": return "var(--alert-caut)";
    case "below":
    case "above":   return "var(--data)";
    case "normal":  return "var(--ink)";
    default:        return "var(--ink-mute)";
  }
}

/** The word that goes beside a figure, so colour is never the only carrier. */
export function bandWord(b: Band): string | null {
  switch (b) {
    case "warning": return "OVER LIMIT";
    case "caution": return "ALERT";
    case "above":   return "ABOVE NORMAL";
    case "below":   return "BELOW NORMAL";
    default:        return null;
  }
}

/** Does this band mean "an alert would be raised"? Used to decide whether a
 *  figure may carry an alert colour at all. */
export const isAlert = (b: Band): boolean => b === "caution" || b === "warning";
