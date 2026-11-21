"""Engine efficiency, and its trend against the as-new reference.

Problem statement section F requires the dashboard to show "Engine efficiency
trends". That is a harder requirement than it first reads, because efficiency
is not a channel on the bus -- nothing on the CAN bus reports it. It has to be
derived, and derived correctly, or it becomes a number that moves with the
throttle rather than with the engine's condition.

WHAT "EFFICIENCY" MEANS FOR A PISTON ENGINE
-------------------------------------------
Three distinct quantities, all of them standard, all of them reported here
because they degrade for different reasons and an engineer needs to tell them
apart:

  BRAKE SPECIFIC FUEL CONSUMPTION (BSFC), g/kWh
      Fuel burned per unit of shaft work. The primary figure of merit; every
      engine manufacturer publishes it. Rises as the engine deteriorates.

  BRAKE THERMAL EFFICIENCY, dimensionless
      The fraction of the fuel's chemical energy that leaves as shaft work.
      Derived from BSFC and the fuel's lower heating value:

          eta_th = 3.6e6 / (BSFC[g/kWh] * LHV[J/g])

      3.6e6 J is one kWh. For AVGAS at 43.5 MJ/kg and a BSFC of 280 g/kWh this
      gives 0.296 -- a physically sensible 30 % for a spark-ignition piston
      engine, and a useful sanity check on the whole chain.

  VOLUMETRIC EFFICIENCY, dimensionless
      Air actually inducted against the swept volume the cylinder could have
      taken at inlet density. It falls with valve, ring and induction wear and
      is the one that separates a breathing problem from a combustion problem.

          eta_vol = m_dot_air / (rho_inlet * V_disp * (rpm / 2) / 60)

      The rpm/2 is the four-stroke factor: one induction stroke per two
      revolutions.

      THE DENSITY MUST BE MANIFOLD DENSITY, NOT AMBIENT. This engine is
      turbocharged and intercooled, so the charge reaching the cylinder is far
      denser than the air outside. Referenced to ambient, the same measured
      cruise point reads eta_vol = 1.523 -- an engine apparently inducting half
      again more air than its cylinders hold, which is not a breathing
      measurement but a boost measurement wearing its clothes. Referenced to
      manifold density it reads 0.834, squarely inside the physical band, and
      it then falls with valve, ring and induction wear as it should.

WHY IT IS REPORTED AGAINST THE SHADOW MODEL, NOT AS AN ABSOLUTE
---------------------------------------------------------------
BSFC at climb power and BSFC at loiter differ by more than a badly worn engine
differs from a new one. An efficiency trend plotted as an absolute number is
therefore mostly a plot of what the pilot was doing, and an operator watching
it would learn to ignore it -- the same failure the alerting layer avoids by
never raising a caution the operator cannot act on.

So the reported quantity is the DETERIORATION: measured efficiency against what
the as-new shadow model predicts for the same operating point, at that instant.
That number is near zero on a healthy engine at any power setting, and grows
only as the engine actually deteriorates. It is the twin earning its keep --
without a synchronised as-new reference the comparison cannot be made at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from common import config

# One kWh in joules. Named rather than inlined so the unit chain is auditable.
JOULES_PER_KWH = 3.6e6


@dataclass
class Efficiency:
    """Efficiency now, and how far it has deteriorated from as-new."""

    bsfc_g_per_kwh: float | None = None
    bsfc_as_new_g_per_kwh: float | None = None
    bsfc_deterioration_pct: float | None = None

    thermal_efficiency: float | None = None
    thermal_as_new: float | None = None

    volumetric_efficiency: float | None = None

    # Fuel that the deterioration is costing, at the current operating point.
    excess_fuel_lph: float | None = None
    reason: str = ""

    @property
    def reportable(self) -> bool:
        return self.bsfc_g_per_kwh is not None

    def as_dict(self) -> dict:
        def r(v, n=3):
            return None if v is None else round(float(v), n)

        return {
            "bsfc_g_per_kwh": r(self.bsfc_g_per_kwh, 1),
            "bsfc_as_new_g_per_kwh": r(self.bsfc_as_new_g_per_kwh, 1),
            "bsfc_deterioration_pct": r(self.bsfc_deterioration_pct, 2),
            "thermal_efficiency": r(self.thermal_efficiency, 4),
            "thermal_as_new": r(self.thermal_as_new, 4),
            "volumetric_efficiency": r(self.volumetric_efficiency, 4),
            "excess_fuel_lph": r(self.excess_fuel_lph, 3),
            "reason": self.reason,
        }


class EfficiencyTracker:
    """Derives efficiency from the bus, and compares it against the twin."""

    def __init__(self, engine_key: str = "rotax_915is") -> None:
        eng = config.load_engine(engine_key)
        fp = eng["fuel_properties"]
        # J per gram. The config carries MJ/kg, which is numerically J/g, but
        # the conversion is written out rather than relied upon silently.
        self.lhv_j_per_g = float(fp["lhv_MJ_per_kg"]) * 1e6 / 1000.0
        self.fuel_density_kg_per_l = float(fp["density_kg_per_L"])
        self.displacement_l = float(eng["geometry"]["displacement_total_L"])
        # Below this there is no meaningful shaft work and BSFC diverges: at
        # idle the engine burns fuel to produce almost no power, so g/kWh goes
        # to infinity and would read as catastrophic deterioration.
        self.min_power_kw = 5.0

    # ------------------------------------------------------------------
    def update(
        self,
        *,
        fuel_flow_lph: float | None,
        power_kw: float | None,
        rpm: float | None,
        air_mass_flow_kg_s: float | None = None,
        inlet_density_kg_m3: float | None = None,
        fuel_flow_predicted_lph: float | None = None,
        power_predicted_kw: float | None = None,
    ) -> Efficiency:
        """One frame in, the current efficiency picture out."""
        out = Efficiency()

        if fuel_flow_lph is None or power_kw is None:
            out.reason = "fuel flow or shaft power unavailable"
            return out
        if power_kw < self.min_power_kw:
            # Not a failure: BSFC is simply undefined at idle, and printing a
            # huge number there would train the operator to ignore the panel.
            out.reason = (
                f"below {self.min_power_kw:.0f} kW -- BSFC is not meaningful "
                f"at idle, where fuel is burned for almost no shaft work"
            )
            return out

        if fuel_flow_lph <= 0.0:
            # The engine running down after the ignition is cut still turns
            # the shaft with no fuel going in. BSFC is zero there, and the
            # thermal efficiency derived from it divided by zero on every tick
            # of a shutdown.
            out.reason = "no fuel flow: engine not firing"
            return out
        fuel_g_per_h = fuel_flow_lph * self.fuel_density_kg_per_l * 1000.0
        out.bsfc_g_per_kwh = fuel_g_per_h / power_kw
        out.thermal_efficiency = JOULES_PER_KWH / (
            out.bsfc_g_per_kwh * self.lhv_j_per_g
        )

        if (
            air_mass_flow_kg_s is not None
            and inlet_density_kg_m3 is not None
            and rpm is not None
            and rpm > 100.0
            and inlet_density_kg_m3 > 1e-6
        ):
            # Four-stroke: one induction stroke every two revolutions.
            swept_m3_per_s = (
                self.displacement_l / 1000.0 * (rpm / 2.0) / 60.0
            )
            ideal = inlet_density_kg_m3 * swept_m3_per_s
            if ideal > 1e-9:
                out.volumetric_efficiency = air_mass_flow_kg_s / ideal

        # ---- the trend that matters: measured against as-new --------------
        if fuel_flow_predicted_lph is not None and fuel_flow_predicted_lph > 0:
            ref_power = power_predicted_kw if power_predicted_kw else power_kw
            if ref_power and ref_power >= self.min_power_kw:
                ref_g_per_h = (
                    fuel_flow_predicted_lph * self.fuel_density_kg_per_l * 1000.0
                )
                out.bsfc_as_new_g_per_kwh = ref_g_per_h / ref_power
                out.thermal_as_new = JOULES_PER_KWH / (
                    out.bsfc_as_new_g_per_kwh * self.lhv_j_per_g
                )
                out.bsfc_deterioration_pct = 100.0 * (
                    out.bsfc_g_per_kwh / out.bsfc_as_new_g_per_kwh - 1.0
                )
                out.excess_fuel_lph = fuel_flow_lph - fuel_flow_predicted_lph
                out.reason = (
                    "measured against the as-new shadow model at this "
                    "operating point"
                )
            else:
                out.reason = "absolute efficiency only -- no as-new reference"
        else:
            out.reason = (
                "absolute efficiency only -- the shadow model has no usable "
                "fuel-flow prediction yet"
            )
        return out


__all__ = ["Efficiency", "EfficiencyTracker", "JOULES_PER_KWH"]
