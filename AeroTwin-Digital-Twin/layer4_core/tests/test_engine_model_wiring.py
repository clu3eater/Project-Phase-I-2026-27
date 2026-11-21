"""The 3D model's fault ids, the registry's, and the twin's must be one set.

The console lights a component by handing a faultId to the visualisation
package. If the twin grows a ninth fault, or the package renames one, nothing
fails loudly -- the fault simply never lights, and the first person to notice
is whoever is watching the engine on a screen instead of reading a log.

These are cheap identity checks that run without a browser, a GPU or the model
itself, which matters: the GLB is 19 MB and the render needs WebGL, so the
visual path cannot be exercised in CI. What CAN be checked here is that the
three lists agree, and that is the part that silently rots.
"""

from __future__ import annotations

import json
import re

import pytest

from common import config
from layer2_physics.degradation import FAULT_CLASS_ORDER

ROOT = config.repo_root() / "layer5_viz" / "gcs_console"
COMPONENT = ROOT / "src" / "components" / "EngineModel.tsx"
REGISTRY = ROOT / "public" / "engine3d" / "fault_registry.json"

needs_package = pytest.mark.skipif(
    not REGISTRY.exists(), reason="the engine-model package is not installed")


def _console_map() -> dict[str, str]:
    """The FAULT_ID table as the console actually declares it."""
    src = COMPONENT.read_text(encoding="utf-8")
    block = src.split("const FAULT_ID", 1)[1].split("};", 1)[0]
    return dict(re.findall(r"(\w+):\s*\"([A-Z_]+)\"", block))


@needs_package
def test_every_fault_the_twin_can_report_can_be_shown():
    missing = {m.value for m in FAULT_CLASS_ORDER} - set(_console_map())
    assert not missing, (
        f"the twin reports {sorted(missing)} and the model cannot light it")


@needs_package
def test_every_id_the_console_sends_exists_in_the_registry():
    ids = {f["faultId"] for f in json.loads(REGISTRY.read_text(encoding="utf-8"))["faults"]}
    unknown = set(_console_map().values()) - ids
    assert not unknown, (
        f"setFault would throw on {sorted(unknown)}: not in fault_registry.json")


@needs_package
def test_the_registry_carries_nothing_the_twin_cannot_produce():
    """A fault in the model with no detector behind it would never light.

    Worse, it would suggest the system watches for something it does not.
    """
    ids = {f["faultId"] for f in json.loads(REGISTRY.read_text(encoding="utf-8"))["faults"]}
    orphans = ids - set(_console_map().values())
    assert not orphans, f"the model can show {sorted(orphans)} and nothing detects it"


@needs_package
def test_the_threshold_is_declared_once():
    """The model must not call a fault present at a different point than the
    fault-probability list on the prognostics page."""
    src = COMPONENT.read_text(encoding="utf-8")
    m = re.search(r"const SHOW_AT = ([0-9.]+)", src)
    assert m, "SHOW_AT has been inlined; it exists so the two agree"
    assert 0.0 < float(m.group(1)) < 1.0


@needs_package
def test_the_model_speaks_the_console_s_colours():
    """Seven meaning-bearing hues on a console that declares six is a defect.

    The package's palette is chosen to read on the Rotax castings, and three of
    its choices collide with what colour means here: RECOVERING is GREEN, which
    on this console means normal and in tolerance; SUSPECT is a purple that
    carries meaning nowhere else; CONTEXT is a pale blue-grey. The registry is
    repainted to the console's tokens as it loads.
    """
    src = COMPONENT.read_text(encoding="utf-8")
    assert "repaintToConsolePalette" in src, (
        "the model is using the package palette; green would mean both "
        "'normal' and 'recovering from a fault' on the same screen")
    for state, token in (("HIGHLIGHT_RECOVERING", "--alert-advis"),
                         ("HIGHLIGHT_WARNING", "--alert-caut"),
                         ("HIGHLIGHT_CRITICAL", "--alert-warn"),
                         ("HIGHLIGHT_CONTEXT", "--phys")):
        assert re.search(rf'{state}:\s*\["{token}"', src), (
            f"{state} must map to {token}")
    assert '"--state-normal"' not in src, (
        "green is NORMAL on this console and must never mark a fault state")


@needs_package
def test_a_fault_is_released_lower_than_it_is_raised():
    """One threshold makes a part pulse between faulted and recovering.

    A probability sitting on the boundary sets the fault, clears it and sets it
    again on consecutive ticks, and every clear starts a three-second recovery
    glow while nothing about the engine has changed.
    """
    src = COMPONENT.read_text(encoding="utf-8")
    show = float(re.search(r"const SHOW_AT = ([0-9.]+)", src).group(1))
    # Each class is lit at ITS calibrated threshold and released below a fixed
    # fraction of it, so the band scales with the class instead of being one
    # absolute number that is wider than some thresholds and narrower than
    # others.
    num, den = re.search(r"const CLEAR_FRACTION = ([0-9.]+)\s*/\s*([0-9.]+)", src).groups()
    fraction = float(num) / float(den)
    assert fraction < 1.0, "the release threshold must sit below the raise one"
    assert show - show * fraction >= 0.05, "the band is too narrow to stop chatter"
    # ...and the release test actually uses it, against the held state.
    assert re.search(r"lit\.current\.has\(id\)\s*&&\s*p\s*>=\s*at\s*\*\s*CLEAR_FRACTION", src), (
        "a lit fault must be held until it falls below the release fraction")
