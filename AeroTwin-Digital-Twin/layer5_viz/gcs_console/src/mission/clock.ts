/* The simulated clock, and the only one.
 *
 * ONE TIME, MANY VIEWS
 * --------------------
 * The map, the transport, the telemetry strip, the health trace and the event
 * list are five views of a single number: seconds into the sortie. The
 * previous implementation held that number in React state and advanced it on
 * every animation frame, which is correct and expensive -- a frame of playback
 * re-rendered the whole page, and the map re-projected several hundred flight
 * samples into a polyline string while it did.
 *
 * So the number lives here instead, in a plain object, and the views subscribe
 * to it. A subscriber that only has to move a marker or rewrite a readout does
 * that with one DOM write per frame and never re-renders. React state is
 * updated at a deliberately coarse rate for the things that genuinely change
 * identity -- the phase name, the leg, whether the transport says PLAY or
 * PAUSE -- because those are not per-frame facts.
 *
 * What is NOT changed here is the timing semantics. The index is still derived
 * from the time by binary search rather than stepped, so seeking, clicking an
 * event and playing all move the same thing and cannot disagree; and the
 * phase-dependent rate below is the same one the previous implementation used,
 * for the same reason.
 */

import type { FlightSample } from "../lib/api";

export type ClockSub = (t: number, playing: boolean) => void;

/* THE PLAYBACK SLOWS DOWN WHERE THERE IS SOMETHING TO SEE.
 *
 * A sortie is hours of cruise around four minutes that matter: the start, the
 * warm-up, the take-off and the landing. At one rate that is unwatchable in
 * both directions -- fast enough for the cruise and the engine start is over
 * in half a second; slow enough for the start and the cruise takes a quarter
 * of an hour. So the chosen speed is the CRUISE speed and the phases where the
 * numbers are actually moving are played at a fraction of it. The simulation
 * makes the same trade when it chooses its step size, so the two agree about
 * where the interesting parts of a flight are. */
export function phaseRate(phase: string | undefined): number {
  return phase === "START" ? 1 / 40
    : phase === "WARMUP" || phase === "LANDING" ? 1 / 12
    : phase === "TAKEOFF" ? 1 / 20
    : phase === "CLIMB" || phase === "DESCENT" ? 1 / 4
    : 1;
}

export class Playback {
  t = 0;
  duration = 0;
  playing = false;
  speed = 300;
  samples: FlightSample[] = [];

  /** Cumulative along-track distance as a fraction of the whole, per sample.
   *  Lets the map reveal the flown track by ARC LENGTH rather than by sample
   *  number -- the samples are spaced in time, not in distance, so revealing
   *  by index would run ahead of the aircraft through the cruise. */
  progress: number[] = [];

  private subs = new Set<ClockSub>();
  private raf = 0;
  private last = 0;
  /** Bumped whenever something a React view must re-render for has changed. */
  onDiscrete: (() => void) | null = null;

  load(samples: FlightSample[], duration: number) {
    this.stop();
    this.wasEnd = false;
    this.samples = samples;
    this.duration = duration;
    this.t = 0;
    this.progress = cumulative(samples);
    this.emit();
    this.onDiscrete?.();
  }

  clear() {
    this.stop();
    this.samples = [];
    this.progress = [];
    this.duration = 0;
    this.t = 0;
    this.emit();
    this.onDiscrete?.();
  }

  subscribe(fn: ClockSub): () => void {
    this.subs.add(fn);
    fn(this.t, this.playing);
    return () => { this.subs.delete(fn); };
  }

  /** The first sample at or after `t`. Binary search: a long sortie carries
   *  several hundred samples and this runs on every frame. */
  indexAt(t: number): number {
    const s = this.samples;
    if (!s.length) return 0;
    let lo = 0, hi = s.length - 1;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (s[m].t_s < t) lo = m + 1; else hi = m;
    }
    return lo;
  }

  /** Where the aircraft is BETWEEN two samples, so it moves continuously
   *  rather than stepping from one reported position to the next. */
  interpolate(t: number): { lat: number; lon: number; f: number; i: number } | null {
    const s = this.samples;
    if (!s.length) return null;
    const i = this.indexAt(t);
    const b = s[i];
    const a = s[Math.max(0, i - 1)];
    const span = b.t_s - a.t_s;
    const f = span > 1e-6 ? Math.max(0, Math.min(1, (t - a.t_s) / span)) : 1;
    return {
      lat: a.lat_deg + (b.lat_deg - a.lat_deg) * f,
      lon: a.lon_deg + (b.lon_deg - a.lon_deg) * f,
      f, i,
    };
  }

  /** Fraction of the track flown by arc length at `t`, in [0, 1]. */
  revealed(t: number): number {
    const p = this.progress;
    if (p.length < 2) return 0;
    const i = this.indexAt(t);
    const s = this.samples;
    const b = s[i], a = s[Math.max(0, i - 1)];
    const span = b.t_s - a.t_s;
    const f = span > 1e-6 ? Math.max(0, Math.min(1, (t - a.t_s) / span)) : 1;
    const pa = p[Math.max(0, i - 1)], pb = p[i];
    return pa + (pb - pa) * f;
  }

  seek(t: number) {
    this.t = Math.max(0, Math.min(this.duration, t));
    this.emit();
    this.checkEnd();
  }

  /* THE LAST SECOND IS THE END. `duration_s` is the model time the sortie
   * took and it is not an integer, while the scrubber steps in whole seconds
   * -- so a scrubber dragged to its own maximum lands a fraction of a second
   * SHORT of the duration, and an equality test there leaves the console
   * insisting the aircraft is still flying with the track fully drawn and the
   * clock reading the total. Half a second of tolerance, once, here. */
  get ended(): boolean {
    return this.duration > 0 && this.t >= this.duration - 0.5;
  }

  /* WHETHER THE SORTIE IS OVER IS A DISCRETE FACT, so the views that draw it
   * -- MISSION COMPLETE, the stage marker, the transport button -- have to be
   * told. Scrubbing to the last second ends the sortie exactly as playing to
   * it does, and a strip that appears only when the clock happened to run out
   * on its own would be a strip that reports how the end was reached. Fires
   * only on the transition, so dragging along the end costs one render. */
  private wasEnd = false;
  private checkEnd() {
    const end = this.ended;
    if (end === this.wasEnd) return;
    this.wasEnd = end;
    this.onDiscrete?.();
  }

  play() {
    if (!this.samples.length) return;
    // FLY IT AGAIN starts at the beginning, including after a scrub to the end.
    if (this.ended) { this.t = 0; this.wasEnd = false; }
    this.playing = true;
    this.last = performance.now();
    this.onDiscrete?.();
    this.tick(this.last);
  }

  /* PAUSING A PAUSED CLOCK CHANGES NOTHING, SO IT SAYS NOTHING. The scrubber
   * pauses on every input event before it seeks, and this used to announce a
   * discrete change each time -- one re-render of the whole mission page per
   * pixel of drag (measured: 153 renders for one sweep of the slider), which
   * is what made the map flicker under the cursor. Only the transition from
   * playing to paused is a fact the React views need. */
  pause() {
    if (!this.playing && !this.raf) return;
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.emit();
    this.onDiscrete?.();
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  setSpeed(x: number) { this.speed = x; this.onDiscrete?.(); }

  stop() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private tick = (now: number) => {
    if (!this.playing) return;
    const dt = Math.min((now - this.last) / 1000, 0.25);
    this.last = now;
    const i = this.indexAt(this.t);
    // The rate is taken from the phase the aircraft is in AT THIS INSTANT, so
    // the transition into and out of the cruise happens on its own.
    const next = this.t + dt * this.speed * phaseRate(this.samples[i]?.phase);
    if (next >= this.duration) {
      this.t = this.duration;
      this.playing = false;
      this.wasEnd = true;
      this.emit();
      this.onDiscrete?.();
      return;
    }
    this.t = next;
    this.emit();
    this.raf = requestAnimationFrame(this.tick);
  };

  private emit() {
    for (const fn of this.subs) fn(this.t, this.playing);
  }
}

function cumulative(s: FlightSample[]): number[] {
  if (s.length < 2) return s.map(() => 0);
  const out = new Array<number>(s.length);
  let acc = 0;
  out[0] = 0;
  for (let i = 1; i < s.length; i++) {
    const dx = (s[i].lon_deg - s[i - 1].lon_deg) *
               Math.cos(((s[i].lat_deg + s[i - 1].lat_deg) / 2) * Math.PI / 180);
    const dy = s[i].lat_deg - s[i - 1].lat_deg;
    acc += Math.sqrt(dx * dx + dy * dy);
    out[i] = acc;
  }
  /* A sortie that never moves -- every sample on the field -- would divide by
   * zero here and reveal nothing. Fall back to sample number, which is the
   * honest answer when there is no track to reveal along. */
  if (acc < 1e-9) return s.map((_, i) => i / (s.length - 1));
  for (let i = 0; i < out.length; i++) out[i] /= acc;
  return out;
}
