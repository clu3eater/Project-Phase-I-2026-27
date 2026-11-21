/* THE AUDIBLE HALF OF THE ALERTING SYSTEM -- PRD Part 4 s4.7.
 *
 * MIL-STD-411F 5.3.1 specifies the non-verbal master warning tone: "the
 * fundamental audio output frequency shall sweep from 700 to 1,700 Hz in
 * 0.85 seconds ... interruption interval shall be 0.12 seconds", repeating
 * until the master warning is reset. s4.7 said the console synthesised this.
 * It did not: nothing in the console made a sound, so a WARNING raised while
 * the operator was looking at another screen, or at the aircraft, had only a
 * lamp to announce it.
 *
 *   WARNING  the 411F sweep, repeating while the master warning is lit --
 *            until MSTR WARN is pressed or the warning clears.
 *   CAUTION  a double 1 kHz pip, repeated every 5 s while the master caution
 *            is lit -- until MSTR CAUT is pressed or the caution clears.
 *
 * The caution used to beep ONCE (PRD Part 2 s9.5's "single_beep"), and once
 * more every 30 s at Level 4. Reported from use: a caution raised while the
 * operator was looking elsewhere was heard as one beep and then silence, and
 * so was missed. An alert tone that stops before anyone has acknowledged it
 * has not done its job; it now repeats until the lamp is pressed, and the
 * lamp is the one control that both silences it and says it was seen.
 *
 * s4.7 also requires the tone to be mutable, the mute to be visible, and a
 * NEW warning to override the mute -- a mute set for yesterday's caution must
 * not silence today's engine fire.
 *
 * Browsers start audio suspended until the page has been interacted with;
 * signing in is an interaction, and any later click resumes it. If audio is
 * still blocked the status bar says so, because a silent alarm that looks
 * armed is worse than one that says it is off.
 */

import { useEffect, useRef, useState } from "react";

// MIL-STD-411F 5.3.1 (thresholds.yaml alerting.audio_master_warning).
const SWEEP_FROM_HZ = 700;
const SWEEP_TO_HZ = 1700;
const SWEEP_S = 0.85;
const GAP_S = 0.12;
// PRD Part 2 s9.5 (thresholds.yaml alert_levels).
const BEEP_HZ = 1000;
const BEEP_S = 0.15;
const CAUTION_REPEAT_MS = 5_000;
const GAIN = 0.12;

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (ctx) return ctx;
  const Ctor = (window as any).AudioContext ?? (window as any).webkitAudioContext;
  if (!Ctor) return null;
  try { ctx = new Ctor(); } catch { ctx = null; }
  return ctx;
}

function tone(fromHz: number, toHz: number, seconds: number) {
  const a = audio();
  if (!a || a.state !== "running") return;
  const t = a.currentTime + 0.01;
  const osc = a.createOscillator();
  const g = a.createGain();
  osc.type = "square";
  osc.frequency.setValueAtTime(fromHz, t);
  if (toHz !== fromHz) osc.frequency.linearRampToValueAtTime(toHz, t + seconds);
  // A 5 ms ramp in and out: a hard edge on a square wave clicks.
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(GAIN, t + 0.005);
  g.gain.setValueAtTime(GAIN, t + seconds - 0.005);
  g.gain.linearRampToValueAtTime(0, t + seconds);
  osc.connect(g).connect(a.destination);
  osc.start(t);
  osc.stop(t + seconds + 0.01);
}

export type AudioState = "on" | "muted" | "blocked" | "unavailable";

/** Drives the tones from the master annunciators. Returns what the status
 *  bar must show and how to change it. */
export function useAlertAudio(input: {
  masterWarning: boolean; masterCaution: boolean;
}): { state: AudioState; toggleMute: () => void; enable: () => void } {
  const [muted, setMuted] = useState(false);
  const [running, setRunning] = useState<boolean>(() => audio()?.state === "running");
  const wasWarning = useRef(false);

  // Resume on any interaction: the browser's autoplay rule.
  useEffect(() => {
    const a = audio();
    if (!a) return;
    const wake = () => { a.resume().then(() => setRunning(a.state === "running")).catch(() => {}); };
    const onState = () => setRunning(a.state === "running");
    a.addEventListener("statechange", onState);
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    wake();
    return () => {
      a.removeEventListener("statechange", onState);
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
    };
  }, []);

  // A NEW warning overrides the mute (s4.7).
  useEffect(() => {
    if (input.masterWarning && !wasWarning.current) setMuted(false);
    wasWarning.current = input.masterWarning;
  }, [input.masterWarning]);

  // WARNING: the 411F sweep, repeating while the master is lit.
  useEffect(() => {
    if (!input.masterWarning || muted || !running) return;
    tone(SWEEP_FROM_HZ, SWEEP_TO_HZ, SWEEP_S);
    const id = window.setInterval(() => tone(SWEEP_FROM_HZ, SWEEP_TO_HZ, SWEEP_S),
                                  (SWEEP_S + GAP_S) * 1000);
    return () => window.clearInterval(id);
  }, [input.masterWarning, muted, running]);

  // CAUTION: a double pip now and every 5 s while the master caution is lit.
  useEffect(() => {
    if (!input.masterCaution || muted || !running || input.masterWarning) return;
    const pip = () => {
      tone(BEEP_HZ, BEEP_HZ, BEEP_S);
      window.setTimeout(() => tone(BEEP_HZ, BEEP_HZ, BEEP_S), 250);
    };
    pip();
    const id = window.setInterval(pip, CAUTION_REPEAT_MS);
    return () => window.clearInterval(id);
  }, [input.masterCaution, muted, running, input.masterWarning]);

  const a = audio();
  const state: AudioState = !a ? "unavailable" : !running ? "blocked" : muted ? "muted" : "on";
  return {
    state,
    toggleMute: () => setMuted((m) => !m),
    enable: () => { a?.resume().then(() => setRunning(a.state === "running")).catch(() => {}); },
  };
}

/** One sweep, for the operator to check the speaker before a sortie. */
export function testTone() {
  tone(SWEEP_FROM_HZ, SWEEP_TO_HZ, SWEEP_S);
}
