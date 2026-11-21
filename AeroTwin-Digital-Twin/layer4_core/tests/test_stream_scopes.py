"""The WebSocket must enforce the same scopes the REST routes do.

WHY THIS FILE EXISTS
--------------------
Every REST route on the twin API is gated on a scope. ``/api/maintenance``
requires ``read:advisory``; ``/api/mission`` requires ``read:mission``. But
``/ws/state`` checked ``read:telemetry`` once, at handshake, and then sent the
COMPLETE snapshot twice a second -- including the costed maintenance plan, the
RUL, and the injected ground truth.

So every scope check on every other route was decorative. The data a role was
refused at the front door was already arriving through the window, and the
console's role separation was a rendering convention rather than an
authorisation boundary. PRD Part 4 section 10c puts enforcement server-side for
exactly this reason.

These tests pin the boundary so it cannot quietly reopen: a new field added to
the Snapshot dataclass without a scope entry will be caught by the last test
here rather than by whoever reads the transcript afterwards.
"""

from __future__ import annotations

from dataclasses import asdict, fields

import pytest

from layer4_core import security as sec
from layer4_core.live import Snapshot
from layer4_core.twin_api import SNAPSHOT_SCOPES, snapshot_for_role

ROLES = ["ROLE_OPERATOR", "ROLE_ENGINEER", "ROLE_MAINTENANCE", "ROLE_COMMANDER"]


def _snapshot() -> dict:
    """A snapshot with every section populated and distinguishable."""
    s = asdict(Snapshot())
    for f in fields(Snapshot):
        if f.name in ("t_s", "wall_utc"):
            continue
        s[f.name] = [{"marker": f.name}] if f.name == "faults_injected" else {
            "marker": f.name
        }
    return s


def _withheld(role: str) -> set[str]:
    out = snapshot_for_role(_snapshot(), role)
    return {
        k for k, v in out.items()
        if isinstance(v, dict) and v.get("authorised") is False
    }


# ---------------------------------------------------------------------------
# The boundary itself
# ---------------------------------------------------------------------------


def test_an_operator_is_not_sent_the_costed_maintenance_plan():
    """/api/maintenance refuses the operator; the stream must too."""
    assert not sec.has_scope("ROLE_OPERATOR", "read:advisory")
    assert "maintenance" in _withheld("ROLE_OPERATOR")


def test_an_operator_is_not_sent_the_injected_ground_truth():
    """Being shown the injected fault is being shown the answer.

    A demonstration in which the operator's console names the fault the
    detector is supposed to deduce demonstrates nothing about the detector.
    """
    assert "faults_injected" in _withheld("ROLE_OPERATOR")


def test_the_commander_is_withheld_nothing():
    """The wildcard role is the one role that sees the whole snapshot."""
    assert _withheld("ROLE_COMMANDER") == set()


@pytest.mark.parametrize("role", ROLES)
def test_every_role_still_receives_the_telemetry_it_flies_on(role):
    """Redaction must not take away the parameters the console is built on."""
    out = snapshot_for_role(_snapshot(), role)
    for key in ("twin", "trend", "history", "pipeline"):
        assert out[key] == {"marker": key}, f"{role} lost {key}"


@pytest.mark.parametrize("role", ROLES)
def test_a_withheld_section_says_so_rather_than_going_missing(role):
    """An absent key is the console's notation for a DEAD SENSOR.

    PRD Part 4 section 7.2 removes rather than substitutes a failed reading, so
    a missing section renders as "---". If a permissions boundary produced the
    same "---", an operator would read their own role as a hardware fault. The
    refusal is therefore explicit and names the scope required.
    """
    out = snapshot_for_role(_snapshot(), role)
    assert set(out) == set(_snapshot()), "a section vanished instead of refusing"
    for key, value in out.items():
        if isinstance(value, dict) and value.get("authorised") is False:
            assert value["scope"] == SNAPSHOT_SCOPES[key]


# ---------------------------------------------------------------------------
# The three audiences the problem statement names
# ---------------------------------------------------------------------------


def test_the_operator_can_see_the_go_no_go_call():
    """Section D is Mission Reliability Enhancement, and continuing or
    aborting the sortie is the OPERATOR's decision. Gating that behind
    read:prognostics left the person flying the aircraft unable to see the
    reliability assessment made for the flight they were conducting."""
    assert sec.has_scope("ROLE_OPERATOR", "read:mission")
    assert "mission" not in _withheld("ROLE_OPERATOR")


def test_the_maintenance_team_can_see_the_maintenance_advisory():
    """It held read:advisory but the page displaying it needed
    read:prognostics, which it did not hold -- so the advisory was addressed
    to a role that could not reach it."""
    assert sec.has_scope("ROLE_MAINTENANCE", "read:advisory")
    assert sec.has_scope("ROLE_MAINTENANCE", "read:prognostics")
    assert _withheld("ROLE_MAINTENANCE") == {"faults_injected"}


def test_the_engineer_can_see_the_consequence_of_the_diagnosis():
    """The engineer could open the prognostics page but not fetch the
    advisory on it: between them the engineer and the maintainer held both
    halves of one screen and neither could use it."""
    assert sec.has_scope("ROLE_ENGINEER", "read:advisory")
    assert _withheld("ROLE_ENGINEER") == set()


# ---------------------------------------------------------------------------
# The guard that keeps this from reopening
# ---------------------------------------------------------------------------


def test_every_snapshot_section_has_a_declared_scope():
    """A new Snapshot field defaults to BEING SENT TO EVERYONE.

    That default is the failure this whole file exists about, so adding a
    section without deciding who may see it fails here rather than shipping.
    """
    # The clock fields are exempt, not ungoverned. They carry a time and a
    # date and no content: `wall_iso` is `wall_utc` with the day attached, and
    # `started_iso` is the same stamp taken when the twin began running. A role
    # that may see the twin at all may see when it is running -- withholding
    # the date while showing the time would protect nothing.
    CLOCK_FIELDS = ("t_s", "wall_utc", "wall_iso", "started_iso")
    ungoverned = {
        f.name for f in fields(Snapshot)
        if f.name not in SNAPSHOT_SCOPES and f.name not in CLOCK_FIELDS
    }
    assert not ungoverned, (
        f"Snapshot sections with no scope, sent to every role: "
        f"{sorted(ungoverned)}"
    )


def test_declared_scopes_all_exist_on_some_role():
    """A scope no role holds withholds a section from everyone but the
    commander, silently."""
    granted = set()
    for role in sec.roles():
        granted |= sec.scopes_for(role)
    granted.discard("*")
    unreachable = set(SNAPSHOT_SCOPES.values()) - granted
    assert not unreachable, f"scopes no role holds: {sorted(unreachable)}"


# ---------------------------------------------------------------------------
# The operator view, and the prognostics figure inside it
# ---------------------------------------------------------------------------


def test_the_operator_view_reaches_every_role():
    """It is the summary the least privileged role exists to read."""
    for role in ROLES:
        out = snapshot_for_role(_snapshot(), role)
        assert not (isinstance(out["display"], dict)
                    and out["display"].get("authorised") is False), role


def test_remaining_life_is_stripped_from_the_operator_view_too():
    """`display` is gated on read:telemetry so that every role gets it -- but
    it carries a remaining-life figure, and that is prognostics.

    Hiding it only in the page would put the number on the wire for a role
    refused it on every other route, which is DEV-107 reintroduced one level
    down. It is REMOVED rather than nulled: the console renders an absent
    figure as "not predicted", which is true, where a 0 would read as an
    engine with no life left.
    """
    snap = _snapshot()
    snap["display"] = {"rul_hours": 312, "mission_success_pct": 87,
                       "band": "GOOD", "instruction": "No action required."}

    op = snapshot_for_role(snap, "ROLE_OPERATOR")["display"]
    assert "rul_hours" not in op
    assert not sec.has_scope("ROLE_OPERATOR", "read:prognostics")
    # ...but everything the operator IS entitled to survives.
    assert op["band"] == "GOOD"
    assert op["instruction"] == "No action required."
    assert op["mission_success_pct"] == 87

    for role in ("ROLE_ENGINEER", "ROLE_MAINTENANCE", "ROLE_COMMANDER"):
        assert snapshot_for_role(snap, role)["display"]["rul_hours"] == 312, role


def test_every_nested_scope_names_a_real_section():
    """A nested rule on a section that no longer exists silently stops
    protecting anything."""
    from layer4_core.twin_api import NESTED_SCOPES

    for section in NESTED_SCOPES:
        assert section in SNAPSHOT_SCOPES, f"{section} is not a snapshot section"


def test_a_non_finite_value_cannot_take_the_state_endpoint_down():
    """One NaN anywhere in the snapshot returned 500 for the WHOLE console.

    `health.track` returned float("nan") for a baseline it had not established
    yet -- the right meaning, but not JSON. So /api/state, the endpoint the
    console lives on, failed for the first 120 samples after every start:
    roughly the first minute, which is exactly when somebody opens it.

    Fixed at the source, and guarded here as well, because this is a class of
    bug rather than one instance of it: any future divide-by-zero in any
    derived quantity would otherwise blank the operator's screen.
    """
    import json

    from layer4_core.twin_api import _json_safe

    hostile = {
        "health": {"chi": float("nan"), "ok": 0.5},
        "trend": {"baseline": float("inf"), "cusum": -float("inf")},
        "series": [1.0, float("nan"), 3.0],
        "nested": {"deep": [{"v": float("nan")}]},
        "text": "unchanged", "int": 7, "none": None,
    }
    safe = _json_safe(hostile)

    # It must be serialisable, and by the STRICT encoder: Python emits a bare
    # NaN token by default, which is invalid JSON that other parsers reject.
    json.dumps(safe, allow_nan=False)

    assert safe["health"]["chi"] is None
    assert safe["health"]["ok"] == 0.5
    assert safe["trend"]["baseline"] is None
    assert safe["trend"]["cusum"] is None
    assert safe["series"] == [1.0, None, 3.0]
    assert safe["nested"]["deep"][0]["v"] is None
    # And nothing else is touched.
    assert safe["text"] == "unchanged" and safe["int"] == 7
    assert safe["none"] is None


def test_an_unestablished_baseline_is_null_rather_than_nan():
    """The source of that 500, pinned where it happens."""
    from layer3_ai import health as hl

    est = hl.HealthEstimator(use_residuals=True)
    out = est.track(0.97, flight_hours=0.1)
    # Far fewer than the 120 samples the baseline needs.
    assert out["baseline"] is None, out["baseline"]
    import json
    json.dumps(out, allow_nan=False)
