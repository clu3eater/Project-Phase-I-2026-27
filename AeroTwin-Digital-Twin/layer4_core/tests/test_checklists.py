"""Every alert the console can raise has a procedure to go with it.

ISA-18.2: an alarm without a defined response is not an alarm, it is noise.
This is the check that keeps it true as rules are added: a new rule with a new
legend and no procedure fails here, not in front of an operator.
"""

from __future__ import annotations

from common import config
from layer1_edge.edge_rules import build_rules


def test_every_alert_legend_has_a_procedure():
    legends = sorted({r.legend for r in build_rules()})
    assert legends, "the rule set is empty"
    missing = [lg for lg in legends if config.checklist_for(lg) is None]
    assert not missing, f"alerts with no procedure: {missing}"


def test_every_procedure_has_steps_for_both_phases():
    for p in config.load_checklists()["procedures"]:
        assert p["airborne"] and p["ground"], p["id"]
        for st in p["airborne"] + p["ground"]:
            assert st["do"].strip()


def test_wildcards_match_the_lane_legends():
    assert config.checklist_for("ECU LANE A FAULT")["id"] == "fadec_lane"
    assert config.checklist_for("ECU LANE B SENSOR")["id"] == "fadec_lane"
    assert config.checklist_for("NOT A REAL LEGEND") is None

