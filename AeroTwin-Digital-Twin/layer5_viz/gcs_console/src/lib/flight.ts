/** Use the fleet's operational state when available, with simulator telemetry
 * as a fallback for standalone sorties not recorded on the operations board. */
export function isAirborne(snapshot: any, aircraftStatus?: string | null): boolean {
  if (aircraftStatus === "FLYING") return true;
  if (["GROUND RUN", "ENGINE RUNNING", "ON GCS"].includes(aircraftStatus ?? "")) return false;
  // Telemetry phase/altitude can remain at its final in-flight value after
  // landing. Only use it for a running standalone sortie when the ops board
  // has no active flight state to report.
  if (snapshot?.sortie?.state !== "running") return false;
  const reported = snapshot?.twin?.reported ?? {};
  const phase = reported.environmental?.flight_phase;
  const altitude = reported.environmental?.altitude_ft?.value ?? 0;
  const groundPhase = ["WARM-UP", "RUN-UP", "COOL-DOWN"].includes(snapshot?.sortie?.phase);
  return altitude > 100 || (typeof phase === "number" && phase >= 3 && phase <= 7 && !groundPhase);
}
