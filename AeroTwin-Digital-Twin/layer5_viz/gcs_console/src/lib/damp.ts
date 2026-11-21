/* HOLDING THE PRINTED DIGITS STILL. Presentation only.
 *
 * THE MEASURED PROBLEM
 * --------------------
 * The console receives about 3.7 snapshot frames per second, and the
 * simulation runs about 15.8x real time, so one frame covers roughly 4.2
 * simulated seconds. Measured over the live stream, the printed STRING of
 * every direct engine reading changed on 90-96 % of frames. On a PARKED
 * engine -- nothing running, nothing to report -- pure sensor scatter moved
 * EGT by 2.5 degC and vibration RMS by 67 % of its own value every half
 * second.
 *
 * A figure whose last digits churn twice a second is not read. It is a
 * chattering annunciator in numeric form: the operator learns that the field
 * is noise and stops looking at it, including on the frame where it finally
 * says something true.
 *
 * WHY A DEADBAND AND NOT AN ANIMATION
 * -----------------------------------
 * The obvious-looking fix -- ease the digits from the old value to the new one
 * -- is forbidden here, and not merely on taste:
 *
 *   - PRD Part 4 s14 forbids count-up / odometer animation on values outright,
 *     and s8.1b forbids decorative motion. A number part-way through a tween
 *     is DISPLAYING A VALUE THE SYSTEM NEVER MEASURED. That is the
 *     substitution s7.2 exists to prevent, dressed up as polish.
 *   - An eased value is always late by the length of its own ease, on every
 *     frame, including the frame of a genuine excursion.
 *   - A per-frame loop costs a paint on every display frame for a quantity
 *     that changes 3.7 times a second.
 *
 * So the sanctioned behaviour is the opposite of motion: QUANTISE + HYSTERESIS
 * DEADBAND. The displayed figure simply does not move until the source has
 * genuinely moved further than the deadband, and when it does move it goes
 * straight to the new reading in one step. No easing, no tween, no animation,
 * no per-frame loop, no interpolation over time, no timers at all. Every
 * number on screen is a number the system actually measured.
 *
 * The lag this trades away was measured too, and it is not visible: genuine
 * per-frame movement on these readings runs 12x to 270x the noise step, so
 * real movement crosses a one-step deadband on the frame it happens.
 *
 * The backend does the same thing for the slow derived quantities in
 * layer4_core/operator_view.py (EMA + quantise + hysteresis, and see the note
 * there on why comparing quantised values alone gives no deadband at all).
 * This module is the display-side half, and deliberately has NO smoothing
 * term: an EMA reports a value between two readings, and on a raw engine
 * reading that is exactly what must not be shown.
 *
 * THE THREE SNAP CONDITIONS
 * -------------------------
 * The deadband is bypassed entirely -- the new reading is adopted on the frame
 * it arrives -- in three cases:
 *
 *   1. STATE CHANGE.  The value's state word changed, e.g. VALID to STALE,
 *      INVALID or MISSING. The figure and its state annunciation must never
 *      disagree by a frame.
 *   2. BAND CHANGE.   The value crossed into a different band (see bandOf in
 *      ./bands). An exceedance is never delayed by damping; damping applies to
 *      the quiet digits inside a band, nowhere else.
 *   3. ABSENCE.       The source is null, undefined or non-finite, or nothing
 *      is held yet. A null outputs null IMMEDIATELY: PRD Part 4 s7.2 is
 *      remove-never-substitute, and a held number shown after its source has
 *      gone is a stale reading presented as current. There is nothing to hold
 *      across a gap either, so the first reading after one is adopted whole.
 *
 * WHAT THIS IS NOT FOR
 * --------------------
 * Not the alerting path. Alerts are raised in layer1_edge/edge_rules.py on the
 * raw ingest readings and never pass through here. This module changes when a
 * PRINTED FIGURE follows its source, and nothing else.
 */

import { useRef } from "react";

/** The deadband is in the value's OWN UNITS -- degC for EGT, psi for oil
 *  pressure, m/s2 for vibration. It is always caller-supplied, because only
 *  the call site knows the unit and the measured scatter of its reading. */
export interface DampOpts {
  deadband: number;
  /** The reading's state word, e.g. Measurement.state. A change snaps. */
  state?: string | null;
  /** The reading's band, e.g. bandOf(value, limit). A change snaps. */
  band?: string | null;
}

/** What is currently held for one reading: the figure on screen, and the two
 *  keys whose change forces it to follow immediately. */
export interface Hold {
  held: number | null;
  state: string | null;
  band: string | null;
}

/** One deadband step. Pure, React-free, and the whole mechanism.
 *
 * Pulled out of the hook so the truth table can be exercised directly, the way
 * bandOf's is: this decides what an operator reads, and a rule nobody can test
 * in isolation is a rule that drifts.
 */
export function dampStep(
  prev: Hold | null | undefined,
  value: number | null | undefined,
  opts: DampOpts,
): Hold {
  const state = opts.state ?? null;
  const band = opts.band ?? null;

  // SNAP 3, absence. Remove, never substitute.
  if (value == null || !Number.isFinite(value)) {
    return { held: null, state, band };
  }

  // Nothing held (first frame, or the first reading after a gap): adopt whole.
  if (prev == null || prev.held == null) return { held: value, state, band };

  // SNAP 1 and SNAP 2: the state word or the band moved. Follow at once.
  if (state !== prev.state || band !== prev.band) {
    return { held: value, state, band };
  }

  // THE DEADBAND. Hold while the source has not genuinely moved further than
  // the band; otherwise adopt the new reading outright, in one step. That is
  // all it does -- there is no easing between the two, and no figure between
  // them is ever printed.
  const width = Number.isFinite(opts.deadband) ? Math.abs(opts.deadband) : 0;
  if (Math.abs(value - prev.held) <= width) {
    return { held: prev.held, state, band };
  }
  return { held: value, state, band };
}

/**
 * The held figure for one reading.
 *
 * Cheap: one ref, one comparison, no timers, no intervals, no subscriptions,
 * and no re-render of its own. The hold lives in a ref rather than in state
 * precisely so that damping never SCHEDULES a paint -- it only decides what
 * the paint the snapshot already caused will print.
 *
 * Writing the ref during render is idempotent here, which is why it is safe:
 * re-running the same render (StrictMode, or a concurrent render that is
 * discarded) compares the new value against a hold that already equals it, and
 * holds. The worst a thrown-away render can do is let the display adopt a true
 * reading one frame early, which is the direction this module is allowed to
 * err in.
 */
export function useDamped(
  value: number | null | undefined,
  opts: { deadband: number; state?: string | null; band?: string | null },
): number | null {
  const hold = useRef<Hold | null>(null);
  hold.current = dampStep(hold.current, value, opts);
  return hold.current.held;
}

/** One reading's worth of input for the record form. */
export interface DampSpec {
  value: number | null | undefined;
  deadband: number;
  state?: string | null;
  band?: string | null;
}

/**
 * The same deadband over a whole record of readings, in ONE hook.
 *
 * A card with eight readings on it cannot call useDamped in a loop: the set of
 * keys in a snapshot changes between frames -- a sensor drops out, a section is
 * absent -- and that would reorder the hooks. So the holds live in a single ref
 * keyed by name, and a key that stops being supplied is forgotten rather than
 * left to accumulate.
 *
 * Deliberately NOT layered on useDamped: a record form that called a hook per
 * key would be the same bug wearing a helper.
 */
export function useDampedRecord<K extends string>(
  specs: Record<K, DampSpec>,
): Record<K, number | null> {
  const holds = useRef<Map<string, Hold>>(new Map());
  const out = {} as Record<K, number | null>;
  const seen = new Set<string>();

  for (const key of Object.keys(specs) as K[]) {
    const spec = specs[key];
    seen.add(key);
    const next = dampStep(holds.current.get(key), spec.value, {
      deadband: spec.deadband,
      state: spec.state,
      band: spec.band,
    });
    holds.current.set(key, next);
    out[key] = next.held;
  }

  // A reading that is no longer supplied is not a reading being held at its
  // last value. Drop it, so a key that returns later comes back as a fresh
  // adoption and not as a figure from minutes ago.
  for (const key of Array.from(holds.current.keys())) {
    if (!seen.has(key)) holds.current.delete(key);
  }

  return out;
}
