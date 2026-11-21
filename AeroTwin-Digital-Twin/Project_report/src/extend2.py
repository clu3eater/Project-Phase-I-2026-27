"""One-off: second round of additions (restores length after the white-space fix)."""
import pathlib

P = pathlib.Path(__file__).with_name("content.md")
s = P.read_text(encoding="utf-8")
if "SUB|(e) C3 AI" in s:
    raise SystemExit("already applied")


def after(anchor, text):
    global s
    assert s.count(anchor) == 1, anchor[:70]
    s = s.replace(anchor, anchor + "\n\n" + text.strip("\n") + "\n")


def before(anchor, text):
    global s
    assert s.count(anchor) == 1, anchor[:70]
    s = s.replace(anchor, text.strip("\n") + "\n\n" + anchor)


before("The comparison in Table 2.1 summarises these platforms", """
SUB|(e) C3 AI and the US Air Force PANDA Programme

C3 AI provides the Predictive Analytics and Decision Assistant (PANDA) used by the US Air Force as its official condition-based maintenance platform, applied across more than 3,000 aircraft. It shows that predictive maintenance can be run at the scale of a whole air force and that maintainers will adopt it when predictions are tied to concrete maintenance actions. However, it is an enterprise platform for large fleets, it runs on substantial central infrastructure, and it works on maintenance and sensor records gathered after flights rather than as a live model running beside a single engine.

LINK|https://c3.ai

SUB|(f) Airbus Skywise – Aviation Data Platform

Skywise is a data platform, built with Palantir, that collects operational and maintenance data from airline fleets and makes it available for analytics, including predictive maintenance applications. Its strength is the breadth of data it brings together across operators. However, it is a data platform rather than a model of a specific engine, it depends on cloud connectivity, and it is designed for commercial airline fleets rather than the small piston engines of unmanned aircraft.

LINK|https://aircraft.airbus.com/en/services/enhance/skywise
""")
s = s.replace("This chapter first reviews four existing platforms", "This chapter first reviews six existing platforms")
after("ROW|Rotax B.U.D.S.|Yes|No|No", "ROW|C3 AI PANDA (USAF)|No|No|Yes\nROW|Airbus Skywise|No|No|Yes")

after("Squadron operations are implemented in the OpsStore class, which enforces the mission state machine of Fig 3.10.1 and rejects any transition that is not allowed.", """
The permission check is implemented once, as a FastAPI dependency that every protected endpoint declares. The excerpt below is taken from the project source. A refused request is recorded in the audit log before the error is returned, because refused attempts are often the most important events for a security review.

CODE|def require(scope: str):
CODE|    def _dep(request: Request, c: dict = Depends(claims)) -> dict:
CODE|        role = str(c.get("role", ""))
CODE|        if not sec.has_scope(role, scope):
CODE|            AUDIT.record("AUTHZ_DENY", subject=str(c.get("sub", "?")),
CODE|                         role=role, scope=scope, path=request.url.path)
CODE|            raise HTTPException(403, f"role {role} lacks scope {scope!r}")
CODE|        return c
CODE|    return _dep
CODE|
CODE|@app.post("/api/faults/inject")
CODE|def inject_fault(req: FaultRequest, c: dict = Depends(require("run:simulation"))):
CODE|    ...

Mission transitions follow the same pattern of a single guarded function. Each transition names the states it may start from and the state it leads to, so an out-of-order request, such as launching a mission that has not started its engine, is refused with the mission's current state rather than corrupting the record. The excerpt below shows the shared transition function and the launch step that uses it.

CODE|def _step(self, mid, *, by, role, frm, to, kind, text, stamp=None):
CODE|    with self._lock, self._cx() as cx:
CODE|        m = self._mission(cx, mid)
CODE|        self._own(m, by, role)               # only the allotted operator
CODE|        if m["status"] not in frm:
CODE|            raise OpsError(f"{mid} is {m['status']}")
CODE|        cx.execute("UPDATE missions SET status=? WHERE id=?", (to, mid))
CODE|        self._log(cx, m["tail"], kind, f"{mid}: {text}", by=by, role=role)
CODE|        return self._mission(cx, mid)
CODE|
CODE|def launch(self, mid, *, by, role):
CODE|    return self._step(mid, by=by, role=role, frm=(ENGINE_RUNNING,),
CODE|                      to=AIRBORNE, kind="LAUNCH", text="launch clearance given")
""")

after("The eight-bit version is about three times smaller and changed only one decision in 300.", """
The latency measurements are listed in Table 4.4. Both runs measured the computation of the twin update only, on an x86-64 computer; the single-core run shows the margin that remains when the twin cannot use the other processor cores.

TABLE|Configuration|p50 (ms)|p95 (ms)|p99 (ms)|Budget (ms)
ROW|All cores, 3 clients connected|51.3|82.7|104.4|200
ROW|Pinned to a single core|45.3|95.3|144.0|200
CAPTION|Table 4.4 Twin Update Latency
""")

after("so that the maintainer knows where to look.", """
The operator does not need to open the engine pages to notice a fault. As shown in Fig 5.4.2, the alert appears in the alerts panel of every page, including the mission page used during flight, with its level, title, explanation and a button that opens the procedure to follow. The master caution annunciator in the top bar lights at the same time.

FIG|5.4.2|shot_alert.png|Screenshot – Caution Alert on the Operator's Mission Page|5.75
""")

after("These limitations define the main work for the second phase of the project.", """
Table 5.6 pairs each limitation with the work planned for the second phase of the project to remove it.

TABLE|Limitation observed|Planned Phase-II work
ROW|Fault data is simulated; no real-engine validation|Hardware-in-the-loop with a CAN adapter, then engine test-bench runs
ROW|Three of eight fault classes named below F1 0.80|Targeted fault data and features for cooling, sensor drift and combustion
ROW|Remaining-life intervals not yet calibrated|Calibrate intervals on held-out engines; publish coverage
ROW|Latency measured only on x86-64|Measure on the ARM edge computer under flight-like load
ROW|Real-flight score below the published baseline|Fine-tune on real piston-engine flight data
ROW|Diesel engine profile is a placeholder|Build and validate a second engine model from its manuals
CAPTION|Table 5.6 Limitations and Planned Phase-II Work
""")
s = s.replace("CAPTION|Table 5.5 Event Sequence", "CAPTION|Table 5.7 Event Sequence").replace(
    "is summarised in Table 5.5.", "is summarised in Table 5.7.")
P.write_text(s, encoding="utf-8")
print("applied")
