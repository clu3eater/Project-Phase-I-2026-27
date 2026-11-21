"""FADEC lane facts shared by the physics and the edge layers.

Which lanes each bus-carried sensor is fitted to comes from the manufacturer's
failure matrix [IM Rev.5, configs/engines/rotax_915is.yaml]. Only the mapping
from a sensor to this project's channel name is defined here.
"""

from __future__ import annotations

from typing import Any

# Manufacturer sensor abbreviation -> the telemetry channel it measures. Only
# sensors whose reading travels on this project's bus appear.
SENSOR_CHANNEL: dict[str, str] = {
    "CPS": "rpm",                          # crankshaft position sensor
    "MAPS": "manifold_pressure",           # manifold air pressure sensor
    "MATS": "manifold_air_temperature",    # manifold air temperature sensor
    "OPS": "oil_pressure",                 # oil pressure sensor
    "OTS": "oil_temperature",              # oil temperature sensor
    "CTS": "coolant_temperature",          # coolant temperature sensor
}


def sensor_lanes(engine: dict[str, Any]) -> dict[str, frozenset[str]]:
    """The lanes each bus-carried sensor is fitted to, from the failure matrix."""
    lanes: dict[str, set[str]] = {}
    for row in engine.get("failure_matrix", {}).get("items", []):
        if row.get("kind") == "sensor" and row.get("item") in SENSOR_CHANNEL:
            lanes.setdefault(row["item"], set()).add(str(row["lane"]))
    return {item: frozenset(v) for item, v in lanes.items()}


def dual_lane_channels(engine: dict[str, Any]) -> frozenset[str]:
    """Channels measured by a separate sensor on each FADEC lane."""
    return frozenset(
        SENSOR_CHANNEL[item] for item, lanes in sensor_lanes(engine).items()
        if lanes >= {"A", "B"}
    )
