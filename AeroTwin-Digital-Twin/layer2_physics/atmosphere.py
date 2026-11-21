"""Atmospheric model and environmental condition library.

PRD Part 3 section 18.1 requires simulation of engine behaviour under high
altitude, endurance, hot-weather, rapid-throttle, maritime and cold-weather
conditions. All of them enter the physics model through ambient temperature,
pressure, density, humidity and airspeed, so they are modelled here once.

Reference: International Standard Atmosphere (ISA), troposphere only
(0 - 11 km), which covers the entire TAPAS-class envelope (service ceiling
approx. 32,000 ft = 9.75 km).

    T = T0 - L * h
    P = P0 * (1 - L*h/T0) ** (g / (R*L))
    rho = P / (R * T)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

# ---------------------------------------------------------------------------
# ISA constants. These are physical constants of the standard atmosphere, not
# tunable parameters, so they live in code rather than in YAML (decision D6
# governs *engine* and *threshold* constants).
# ---------------------------------------------------------------------------
T0_K = 288.15  # sea-level standard temperature
P0_PA = 101325.0  # sea-level standard pressure
LAPSE_K_PER_M = 0.0065  # tropospheric lapse rate
G0 = 9.80665
R_AIR = 287.05287  # J/(kg K)
TROPOPAUSE_M = 11000.0
T_TROPOPAUSE_K = T0_K - LAPSE_K_PER_M * TROPOPAUSE_M  # 216.65 K

FT_PER_M = 3.280839895
KMH_PER_MS = 3.6


class EnvCondition(StrEnum):
    """The environmental scenarios of PRD Part 3 section 18.1."""

    STANDARD = "STANDARD"
    HIGH_ALTITUDE = "HIGH_ALTITUDE"
    ENDURANCE = "ENDURANCE"
    HOT_WEATHER = "HOT_WEATHER"
    RAPID_THROTTLE = "RAPID_THROTTLE"
    MARITIME = "MARITIME"
    COLD_WEATHER = "COLD_WEATHER"


@dataclass(frozen=True)
class Ambient:
    """Ambient state seen by the engine at one instant."""

    altitude_ft: float
    oat_c: float
    pressure_pa: float
    density_kg_m3: float
    humidity_pct: float
    airspeed_kmh: float

    @property
    def oat_k(self) -> float:
        return self.oat_c + 273.15

    @property
    def pressure_hpa(self) -> float:
        return self.pressure_pa / 100.0

    @property
    def density_ratio(self) -> float:
        """rho / rho_sea_level_ISA -- the driver of normally-aspirated power loss."""
        return self.density_kg_m3 / SEA_LEVEL_DENSITY

    @property
    def pressure_ratio(self) -> float:
        return self.pressure_pa / P0_PA


def isa_temperature_k(altitude_m: float) -> float:
    if altitude_m <= TROPOPAUSE_M:
        return T0_K - LAPSE_K_PER_M * altitude_m
    return T_TROPOPAUSE_K  # isothermal lower stratosphere


def isa_pressure_pa(altitude_m: float) -> float:
    if altitude_m <= TROPOPAUSE_M:
        return P0_PA * (1.0 - LAPSE_K_PER_M * altitude_m / T0_K) ** (
            G0 / (R_AIR * LAPSE_K_PER_M)
        )
    p_trop = P0_PA * (1.0 - LAPSE_K_PER_M * TROPOPAUSE_M / T0_K) ** (
        G0 / (R_AIR * LAPSE_K_PER_M)
    )
    import math

    return p_trop * math.exp(-G0 * (altitude_m - TROPOPAUSE_M) / (R_AIR * T_TROPOPAUSE_K))


def air_density(pressure_pa: float, temperature_k: float, humidity_pct: float = 0.0) -> float:
    """Density of moist air.

    Humid air is *less* dense than dry air because water vapour (M=18) displaces
    N2/O2 (M~29). The correction is small (<1% at 45 C, 100% RH) but it matters
    for hot-and-humid maritime operation, which is exactly one of the scenarios
    the problem statement asks us to simulate.

    Vapour pressure uses the Tetens approximation for saturation pressure.
    """
    import math

    t_c = temperature_k - 273.15
    p_sat = 610.78 * math.exp(17.27 * t_c / (t_c + 237.3))  # Pa
    p_vapour = (humidity_pct / 100.0) * p_sat
    p_dry = pressure_pa - p_vapour
    # rho = p_d/(R_d T) + p_v/(R_v T),  R_v = 461.495 J/(kg K)
    return p_dry / (R_AIR * temperature_k) + p_vapour / (461.495 * temperature_k)


SEA_LEVEL_DENSITY = air_density(P0_PA, T0_K, 0.0)


def ambient_at(
    altitude_ft: float,
    *,
    isa_deviation_c: float = 0.0,
    humidity_pct: float = 30.0,
    airspeed_kmh: float = 150.0,
) -> Ambient:
    """Ambient conditions at an altitude, with an ISA temperature deviation.

    ``isa_deviation_c`` is the standard way to express a hot or cold day:
    ISA+20 for an Indian summer, ISA-10 for a Himalayan winter. PRD Part 3
    section 18.1 calls for "ISA, ISA+10 (hot day), ISA-10 (cold day)"; any
    deviation is accepted here.
    """
    altitude_m = altitude_ft / FT_PER_M
    t_k = isa_temperature_k(altitude_m) + isa_deviation_c
    p_pa = isa_pressure_pa(altitude_m)  # pressure follows the standard column
    rho = air_density(p_pa, t_k, humidity_pct)
    return Ambient(
        altitude_ft=altitude_ft,
        oat_c=t_k - 273.15,
        pressure_pa=p_pa,
        density_kg_m3=rho,
        humidity_pct=humidity_pct,
        airspeed_kmh=airspeed_kmh,
    )


@dataclass(frozen=True)
class EnvProfile:
    """A named environmental scenario and the modifiers it applies."""

    condition: EnvCondition
    label: str
    isa_deviation_c: float
    humidity_pct: float
    default_altitude_ft: float
    default_airspeed_kmh: float
    # Multipliers applied to degradation rates while operating in this
    # environment. PRD Part 3 section 18.1: salt ingestion accelerates sensor
    # drift and compressor erosion; sustained high oil temperature accelerates
    # oil breakdown; cold starts load the battery and bearings.
    degradation_multipliers: dict[str, float]
    notes: str


ENV_PROFILES: dict[EnvCondition, EnvProfile] = {
    EnvCondition.STANDARD: EnvProfile(
        condition=EnvCondition.STANDARD,
        label="Standard day",
        isa_deviation_c=0.0,
        humidity_pct=30.0,
        default_altitude_ft=15000.0,
        default_airspeed_kmh=180.0,
        degradation_multipliers={},
        notes="ISA reference case used for model validation.",
    ),
    EnvCondition.HIGH_ALTITUDE: EnvProfile(
        condition=EnvCondition.HIGH_ALTITUDE,
        label="High-altitude operation",
        isa_deviation_c=0.0,
        humidity_pct=15.0,
        default_altitude_ft=25000.0,
        default_airspeed_kmh=200.0,
        degradation_multipliers={"turbocharger": 1.6},
        notes=(
            "Above the turbocharger critical altitude the wastegate is fully closed "
            "and boost can no longer hold manifold pressure, so power falls with "
            "ambient density and the turbo runs at sustained high speed."
        ),
    ),
    EnvCondition.ENDURANCE: EnvProfile(
        condition=EnvCondition.ENDURANCE,
        label="Endurance mission (18-24 h)",
        isa_deviation_c=0.0,
        humidity_pct=40.0,
        default_altitude_ft=18000.0,
        default_airspeed_kmh=170.0,
        degradation_multipliers={"oil_thermal": 1.4, "combustion_deposits": 1.3},
        notes=(
            "Sustained operation accumulates oil thermal breakdown and combustion "
            "chamber deposits. PRD Part 3 section 18.1: viscosity +5-10% over 18 h "
            "at 100 C, combustion efficiency -2-3%."
        ),
    ),
    EnvCondition.HOT_WEATHER: EnvProfile(
        condition=EnvCondition.HOT_WEATHER,
        label="Hot-weather operation (Thar / desert)",
        isa_deviation_c=25.0,
        humidity_pct=12.0,
        default_altitude_ft=8000.0,
        default_airspeed_kmh=160.0,
        degradation_multipliers={"cooling": 1.5, "oil_thermal": 1.8},
        notes=(
            "ISA+25: about 40 C at sea level, 37 C at 1,500 ft and 24 C at the 8,000 ft "
            "default altitude. Cooling margin shrinks, oil viscosity falls, vapour-lock "
            "risk rises. The manufacturer's 50 C ambient limit is exercised by the "
            "installation cooling test (DEV-236), not by this profile."
        ),
    ),
    EnvCondition.RAPID_THROTTLE: EnvProfile(
        condition=EnvCondition.RAPID_THROTTLE,
        label="Rapid throttle transitions",
        isa_deviation_c=0.0,
        humidity_pct=30.0,
        default_altitude_ft=12000.0,
        default_airspeed_kmh=180.0,
        degradation_multipliers={"bearing_wear": 1.5, "combustion_deposits": 1.2},
        notes=(
            "Repeated 0-100% transitions cause thermal shock (CHT rate limit 5 C/min), "
            "turbo lag, transient enrichment and oil pressure dips."
        ),
    ),
    EnvCondition.MARITIME: EnvProfile(
        condition=EnvCondition.MARITIME,
        label="Maritime operation",
        isa_deviation_c=6.0,
        humidity_pct=88.0,
        default_altitude_ft=6000.0,
        default_airspeed_kmh=175.0,
        degradation_multipliers={"turbocharger": 1.4, "sensor_drift": 2.5},
        notes=(
            "Salt-laden, humid air: compressor blade erosion, thermocouple oxidation "
            "and connector corrosion accelerate sensor drift."
        ),
    ),
    EnvCondition.COLD_WEATHER: EnvProfile(
        condition=EnvCondition.COLD_WEATHER,
        label="Himalayan / cold-weather operation",
        isa_deviation_c=-20.0,
        humidity_pct=20.0,
        default_altitude_ft=20000.0,
        default_airspeed_kmh=190.0,
        degradation_multipliers={"bearing_wear": 1.3},
        notes=(
            "Cold start raises oil viscosity by up to 400% at -30 C and halves usable "
            "battery capacity at -20 C; icing risk on intake and fuel."
        ),
    ),
}


def profile(condition: EnvCondition | str) -> EnvProfile:
    if isinstance(condition, str):
        condition = EnvCondition(condition)
    return ENV_PROFILES[condition]


def ambient_for(
    condition: EnvCondition | str,
    *,
    altitude_ft: float | None = None,
    airspeed_kmh: float | None = None,
    oat_c: float | None = None,
    humidity_pct: float | None = None,
) -> Ambient:
    """Ambient state for a named scenario, with optional operator overrides.

    ``oat_c`` overrides the computed temperature entirely -- used by the what-if
    engine when the operator asks a direct question ("climb to 20,000 ft at
    45 C ambient"), which is not the same as an ISA deviation.
    """
    prof = profile(condition)
    alt = prof.default_altitude_ft if altitude_ft is None else altitude_ft
    spd = prof.default_airspeed_kmh if airspeed_kmh is None else airspeed_kmh
    # Operator humidity override (REP-08); the profile's value otherwise.
    hum = prof.humidity_pct if humidity_pct is None else float(humidity_pct)
    amb = ambient_at(
        alt,
        isa_deviation_c=prof.isa_deviation_c,
        humidity_pct=hum,
        airspeed_kmh=spd,
    )
    if oat_c is not None:
        rho = air_density(amb.pressure_pa, oat_c + 273.15, hum)
        amb = replace(amb, oat_c=oat_c, density_kg_m3=rho)
    return amb


def power_available_ratio(amb: Ambient, critical_altitude_ft: float | None = None) -> float:
    """Fraction of sea-level power available, before turbocharger compensation.

    For a naturally aspirated engine this is essentially the density ratio.
    PRD Part 1 section 4.4 quotes approximately 0.75 at 10,000 ft and 0.55 at
    20,000 ft for the installed (turbocharged) Rotax 914; the turbocharger part
    of that compensation is applied in ``layer2_physics.turbo``, so this
    function deliberately returns the *un-boosted* figure.
    """
    ratio = amb.density_ratio
    if critical_altitude_ft is not None and amb.altitude_ft <= critical_altitude_ft:
        # Below critical altitude the turbo can hold manifold pressure, so the
        # un-boosted density ratio is not the limiting factor. The turbo module
        # applies the real correction; this is only an informational floor.
        ratio = max(ratio, 0.90)
    return ratio
