"""Combustion model -- PRD Part 1 section 4.2 (Level 0 of the model hierarchy).

Provides adiabatic flame temperature, burned-gas composition and an EGT
baseline, using Cantera with GRI-Mech 3.0 when it is installed and a
Cantera-generated lookup table when it is not (decision D7: Cantera install is
the single most-cited risk in PRD Part 0 section 0.12, and a real-time monitor
must not depend on a chemistry solve per sample anyway).

Two ignition modes, selected by ``identity.ignition`` in the engine YAML:

  SPARK        premixed charge, equivalence ratio near stoichiometric, flame
               temperature peaks slightly rich (phi ~ 1.05).
  COMPRESSION  diesel: globally lean (phi 0.3 - 0.8) with locally
               stoichiometric diffusion burning, so the peak temperature is set
               by the local flame rather than by the global phi.

This split is the *entire* code difference between the Rotax reference engine
and the TAPAS Austro AE330 adaptation (PRD Part 1 section 1.2).
"""

from __future__ import annotations

import functools
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common import config

# Lookup grid axes. Chosen to cover the operating envelope of both engines with
# enough resolution that linear interpolation error stays under ~5 K.
PHI_GRID = np.round(np.arange(0.30, 1.61, 0.05), 3)
T_INTAKE_GRID = np.array([250.0, 275.0, 300.0, 325.0, 350.0, 400.0, 450.0])
P_GRID_BAR = np.array([1.0, 5.0, 10.0, 20.0, 35.0, 60.0, 100.0, 160.0])

_TABLE_DIR = config.repo_root() / "data" / "physics"
_MECHANISM = "gri30.yaml"


@dataclass(frozen=True)
class CombustionState:
    """Result of an equilibrium combustion calculation."""

    t_adiabatic_k: float
    phi: float
    species_mole_fraction: dict[str, float]
    source: str  # "cantera" | "lookup"

    @property
    def t_adiabatic_c(self) -> float:
        return self.t_adiabatic_k - 273.15


# ---------------------------------------------------------------------------
# Cantera path
# ---------------------------------------------------------------------------


def cantera_available() -> bool:
    try:
        import cantera  # noqa: F401
    except Exception:
        return False
    return True


def _fuel_string(engine: dict) -> str:
    """Cantera composition string for the engine's fuel surrogate.

    PRD Part 1 section 4.2: Avgas 100LL is approximated as C7.2H15.5, which is
    not a GRI-Mech species. GRI-Mech 3.0 is a natural-gas mechanism whose
    largest hydrocarbon is C3H8, so an n-heptane surrogate cannot be burned in
    it directly either. For an *equilibrium* flame-temperature calculation the
    fuel need only supply the correct C:H ratio and heating value, so the fuel
    is represented by the CH4/C2H6/C3H8 blend that matches the surrogate's C:H
    ratio. Ignition-delay work would require a large-hydrocarbon mechanism
    instead; that is recorded as a production item, not claimed here.
    """
    surrogate = engine["fuel_properties"].get("surrogate", "C7H16")
    # Parse CxHy.
    import re

    m = re.match(r"(?:N?C)(\d+)H(\d+)", surrogate.upper())
    if not m:
        return "CH4:1"
    c, h = int(m.group(1)), int(m.group(2))
    ratio = h / c  # H per C: 2.286 for C7H16, 2.2 for C10H22
    # Blend CH4 (H/C=4) with C3H8 (H/C=2.667) and C2H6 (H/C=3) is still above
    # the target; the practical floor for GRI-Mech is C3H8. Solve a CH4/C3H8
    # blend on a per-carbon basis and accept the residual, which is reported.
    # x = carbon fraction from CH4.
    x = (ratio - 8.0 / 3.0) / (4.0 - 8.0 / 3.0)
    x = float(np.clip(x, 0.0, 1.0))
    # Convert carbon fractions to mole fractions (C3H8 carries 3 C per mole).
    n_ch4 = x
    n_c3h8 = (1.0 - x) / 3.0
    total = n_ch4 + n_c3h8
    return f"CH4:{n_ch4 / total:.6f}, C3H8:{n_c3h8 / total:.6f}"


def _cantera_flame(
    phi: float, t_intake_k: float, p_bar: float, engine: dict
) -> CombustionState:
    import cantera as ct

    gas = ct.Solution(_MECHANISM)
    gas.set_equivalence_ratio(phi, _fuel_string(engine), "O2:0.21, N2:0.79")
    gas.TP = t_intake_k, p_bar * 1e5
    # Constant-pressure adiabatic equilibrium: PRD Part 1 section 4.2 specifies
    # "Combustion: Constant pressure heat addition (HP equilibrium)".
    gas.equilibrate("HP")
    interesting = ("CO2", "H2O", "N2", "O2", "CO", "NO", "NO2", "OH", "H2")
    names = gas.species_names
    frac = {s: float(gas.X[names.index(s)]) for s in interesting if s in names}
    return CombustionState(
        t_adiabatic_k=float(gas.T), phi=phi, species_mole_fraction=frac, source="cantera"
    )


# ---------------------------------------------------------------------------
# Lookup table: generated from Cantera, shipped in-repo, used at runtime
# ---------------------------------------------------------------------------


def table_path(engine_key: str) -> Path:
    return _TABLE_DIR / f"flame_{engine_key}.json"


def generate_table(engine_key: str = "rotax_915is", *, force: bool = False) -> Path:
    """Generate the adiabatic-flame lookup table with Cantera.

    Run offline (``python -m layer2_physics.combustion --generate``). The result
    is committed so that the runtime never needs Cantera.
    """
    if not cantera_available():
        raise RuntimeError(
            "Cantera is required to GENERATE the flame table "
            "(pip install 'dt-uav-engine[physics]'). It is not required to USE it."
        )
    out = table_path(engine_key)
    if out.exists() and not force:
        return out

    engine = config.load_engine(engine_key)
    grid = np.zeros((len(PHI_GRID), len(T_INTAKE_GRID), len(P_GRID_BAR)))
    species_at_ref: dict[str, float] = {}
    for i, phi in enumerate(PHI_GRID):
        for j, t_in in enumerate(T_INTAKE_GRID):
            for k, p in enumerate(P_GRID_BAR):
                st = _cantera_flame(float(phi), float(t_in), float(p), engine)
                grid[i, j, k] = st.t_adiabatic_k
                if i == len(PHI_GRID) // 2 and j == 2 and k == 4:
                    species_at_ref = st.species_mole_fraction

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine_key": engine_key,
        "mechanism": _MECHANISM,
        "fuel_surrogate": engine["fuel_properties"].get("surrogate"),
        "fuel_composition": _fuel_string(engine),
        "phi_grid": PHI_GRID.tolist(),
        "t_intake_grid_k": T_INTAKE_GRID.tolist(),
        "p_grid_bar": P_GRID_BAR.tolist(),
        "t_adiabatic_k": grid.tolist(),
        "species_at_reference": species_at_ref,
        "note": (
            "Generated by layer2_physics/combustion.py with Cantera GRI-Mech 3.0, "
            "constant-pressure adiabatic equilibrium (PRD Part 1 section 4.2). "
            "Committed so the runtime does not require Cantera."
        ),
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def _table_for(engine_key: str) -> Path | None:
    """The flame table this engine uses: its own, else one for the same fuel.

    An adiabatic flame temperature is a property of the FUEL, not of the
    engine it burns in. A new engine definition had no table and so could not
    run at all without Cantera installed to generate one ("No flame table for
    'my_engine'"), even when it burned exactly the fuel an existing table was
    computed for. Its parents in `extends:` are tried first, then any table
    generated for the same surrogate.
    """
    own = table_path(engine_key)
    if own.is_file():
        return own
    try:
        eng = config.load_engine(engine_key)
    except Exception:  # noqa: BLE001 - no definition, no table
        return None
    fuel = eng.get("fuel_properties", {}).get("surrogate")
    for parent in eng.get("extends_chain", []):
        cand = table_path(str(parent))
        if cand.is_file() and _table_fuel(cand) == fuel:
            return cand
    for cand in sorted(_TABLE_DIR.glob("flame_*.json")):
        if _table_fuel(cand) == fuel:
            return cand
    return None


def _table_fuel(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("fuel_surrogate")
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=4)
def _load_table(engine_key: str) -> dict | None:
    p = _table_for(engine_key)
    if p is None:
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["t_adiabatic_k"] = np.asarray(raw["t_adiabatic_k"], dtype=float)
    raw["phi_grid"] = np.asarray(raw["phi_grid"], dtype=float)
    raw["t_intake_grid_k"] = np.asarray(raw["t_intake_grid_k"], dtype=float)
    raw["p_grid_bar"] = np.asarray(raw["p_grid_bar"], dtype=float)
    return raw


@functools.lru_cache(maxsize=4)
def _flame_interpolator(engine_key: str):
    """Cached interpolator over the flame table.

    Built once per engine: rebuilding it per sample cost more than the physics
    step it serves.
    """
    tbl = _load_table(engine_key)
    if tbl is None:
        return None, None
    from scipy.interpolate import RegularGridInterpolator

    interp = RegularGridInterpolator(
        (tbl["phi_grid"], tbl["t_intake_grid_k"], tbl["p_grid_bar"]),
        tbl["t_adiabatic_k"],
        method="linear",
        bounds_error=False,
        fill_value=None,
    )
    return interp, tbl


def _lookup_flame(phi: float, t_intake_k: float, p_bar: float, engine_key: str) -> CombustionState:
    interp, tbl = _flame_interpolator(engine_key)
    if interp is None or tbl is None:
        raise RuntimeError(
            f"No flame table for '{engine_key}' and Cantera is unavailable. "
            "Run: python -m layer2_physics.combustion --generate"
        )
    pt = [
        float(np.clip(phi, tbl["phi_grid"][0], tbl["phi_grid"][-1])),
        float(np.clip(t_intake_k, tbl["t_intake_grid_k"][0], tbl["t_intake_grid_k"][-1])),
        float(np.clip(p_bar, tbl["p_grid_bar"][0], tbl["p_grid_bar"][-1])),
    ]
    return CombustionState(
        t_adiabatic_k=float(interp([pt])[0]),
        phi=phi,
        species_mole_fraction=tbl.get("species_at_reference", {}),
        source="lookup",
    )


def adiabatic_flame(
    phi: float,
    t_intake_k: float,
    p_bar: float,
    engine_key: str = "rotax_915is",
    *,
    prefer_cantera: bool = False,
) -> CombustionState:
    """Adiabatic flame temperature at an operating point.

    ``prefer_cantera`` forces the live chemistry solve; the default uses the
    lookup because the real-time loop of PRD Part 1 section 6.4 budgets 10-20 ms
    for the whole physics update, and an equilibrium solve costs more than that.
    """
    if prefer_cantera and cantera_available():
        return _cantera_flame(phi, t_intake_k, p_bar, config.load_engine(engine_key))
    try:
        return _lookup_flame(phi, t_intake_k, p_bar, engine_key)
    except RuntimeError:
        if cantera_available():
            return _cantera_flame(phi, t_intake_k, p_bar, config.load_engine(engine_key))
        raise


# ---------------------------------------------------------------------------
# EGT baseline (PRD Part 1 section 4.2, "EGT Prediction Model")
# ---------------------------------------------------------------------------


def egt_baseline_c(
    *,
    phi: float,
    t_intake_k: float,
    p_peak_bar: float,
    eta_comb: float,
    exhaust_loss_fraction: float,
    engine: dict,
    engine_key: str = "rotax_915is",
    map_egt_c: float | None = None,
) -> tuple[float, CombustionState]:
    """Predicted exhaust gas temperature at the port [deg C].

    IMPORTANT -- deviation from PRD Part 1 section 4.2 (see docs/PRD_DEVIATIONS.md
    DEV-12). The PRD gives

        T_EGT = T_ad * eta_comb * (1 - dQ_exhaust_loss / Q_in)

    which omits the expansion stroke entirely. Adiabatic flame temperature is
    the *peak* temperature at top dead centre, around 2300 K; the gas then does
    work on the piston all the way down to exhaust valve opening, and blows down
    to manifold pressure, before it ever reaches the thermocouple. Applying the
    PRD formula directly yields roughly 1700 degC, against a real cruise EGT of
    about 620 degC (PRD Part 1 section 3.1 itself). The three physical stages
    are therefore modelled explicitly:

      1. Expansion to exhaust valve opening (PRD section 4.3.4):
             T_EVO = T_ad * (1/r_e)^(gamma_exh - 1)
         with the effective expansion ratio taken from the geometric
         compression ratio.
      2. Blowdown to the exhaust manifold (PRD section 4.3.4, verbatim):
             T_port = T_EVO * (P_exh / P_cyl_EVO)^((gamma_exh - 1)/gamma_exh)
      3. Heat loss to the exhaust pipe before the sensor
         (``exhaust_loss_fraction``, computed by the MVEM).

    Returns the EGT and the underlying combustion state so a caller can show
    the operator *why* (PRD Part 4 principle P6).
    """
    st = adiabatic_flame(phi, t_intake_k, p_peak_bar, engine_key)

    gamma_e = float(engine["thermodynamics"]["gamma_exhaust"])
    r_c = float(engine["geometry"]["compression_ratio"])
    # Effective expansion ratio is a little below the geometric compression
    # ratio because the exhaust valve opens before bottom dead centre.
    r_e = max(1.5, 0.88 * r_c)

    t_evo = st.t_adiabatic_k * eta_comb * (1.0 / r_e) ** (gamma_e - 1.0)

    p_exh = float(engine["exhaust"]["manifold_pressure_bar"])
    p_evo = max(float(engine["exhaust"]["cylinder_pressure_at_evo_bar"]), p_exh * 1.05)
    t_port = t_evo * (p_exh / p_evo) ** ((gamma_e - 1.0) / gamma_e)

    egt_k = t_port * (1.0 - exhaust_loss_fraction)

    if map_egt_c is None:
        return egt_k - 273.15, st

    # HYBRID CLOSURE (PRD Part 3 INNOVATION 4: hybrid thermodynamic +
    # data-driven). The expansion/blowdown chain above is thermochemically
    # sound but carries no load dependence: for a constant commanded phi it
    # returns nearly the same EGT at 25% and 100% power, because the real
    # load dependence comes from in-cylinder heat transfer, residual gas
    # fraction and valve timing that a 0-D equilibrium model does not resolve.
    #
    # The anchored MAP 5 of PRD Part 1 section 5.1 does carry that load
    # dependence and is pinned to the 620 degC cruise figure. So the map
    # supplies the magnitude and the load trend, and the Cantera chain supplies
    # the *sensitivity*: how EGT moves when mixture, intake temperature,
    # combustion efficiency or exhaust back-pressure change away from the
    # reference at which the map was built. Neither part is discarded and the
    # result stays anchored to published data.
    ref = _reference_port_temp_k(engine_key)
    sensitivity = (t_port * (1.0 - exhaust_loss_fraction)) / max(ref, 1.0)
    return float((map_egt_c + 273.15) * sensitivity - 273.15), st


@functools.lru_cache(maxsize=8)
def _reference_port_temp_k(engine_key: str) -> float:
    """Port temperature of the physical chain at the map's reference point.

    The reference is best-power mixture, standard intake temperature and
    nominal combustion efficiency -- the condition MAP 5 was generated at.
    """
    engine = config.load_engine(engine_key)
    gamma_e = float(engine["thermodynamics"]["gamma_exhaust"])
    r_c = float(engine["geometry"]["compression_ratio"])
    r_e = max(1.5, 0.88 * r_c)
    eta0 = float(engine["thermodynamics"]["combustion"]["efficiency_new"])
    p_peak = float(engine["thermodynamics"]["peak_cylinder_pressure_bar"])
    st = adiabatic_flame(1.0, 320.0, p_peak, engine_key)
    t_evo = st.t_adiabatic_k * eta0 * (1.0 / r_e) ** (gamma_e - 1.0)
    p_exh = float(engine["exhaust"]["manifold_pressure_bar"])
    p_evo = max(float(engine["exhaust"]["cylinder_pressure_at_evo_bar"]), p_exh * 1.05)
    t_port = t_evo * (p_exh / p_evo) ** ((gamma_e - 1.0) / gamma_e)
    return float(t_port * (1.0 - 0.10))


def stoichiometric_afr(engine: dict) -> float:
    """Stoichiometric air-fuel ratio by mass for the engine's fuel.

    For CxHy: AFR_s = (x + y/4) * 32/0.21 * (1/M_fuel) ... derived directly
    rather than tabulated so that a new fuel in a new engine YAML works without
    a code change.
    """
    import re

    surrogate = str(engine["fuel_properties"].get("surrogate", "C7H16")).upper()
    m = re.match(r"(?:N?C)(\d+)H(\d+)", surrogate)
    if not m:
        return 14.7
    c, h = int(m.group(1)), int(m.group(2))
    m_fuel = c * 12.011 + h * 1.008
    # Moles of O2 per mole of fuel for complete combustion.
    n_o2 = c + h / 4.0
    # Air is 21% O2 by mole; mean molar mass of air 28.96.
    m_air = n_o2 / 0.21 * 28.96
    return m_air / m_fuel


def equivalence_ratio(air_mass_flow: float, fuel_mass_flow: float, engine: dict) -> float:
    """phi from measured air and fuel mass flows [kg/s]."""
    if air_mass_flow <= 0.0:
        return 0.0
    afr = air_mass_flow / max(fuel_mass_flow, 1e-12)
    return float(np.clip(stoichiometric_afr(engine) / afr, 0.0, 3.0))


def wiebe_burn_fraction(theta_deg: float, engine: dict) -> float:
    """Cumulative burned mass fraction at crank angle theta after ignition.

        x_b(theta) = 1 - exp(-a * (theta/theta_dur)^(m+1))

    PRD Part 1 section 4.3.2 gives the *rate* form dQ/dtheta; this is its
    integral, which is what the heat-release model actually needs.
    """
    w = engine["thermodynamics"]["wiebe"]
    dur = float(w["duration_deg_ca"])
    m = float(w["shape_factor_m"])
    a = float(w["efficiency_factor_a"])
    if theta_deg <= 0.0:
        return 0.0
    if theta_deg >= dur:
        return 1.0
    return float(1.0 - math.exp(-a * (theta_deg / dur) ** (m + 1.0)))


def combustion_mode(engine: dict) -> str:
    """SPARK or COMPRESSION -- the one branch that differs between engines."""
    return str(engine["identity"]["ignition"])


def operating_phi(engine: dict, power_fraction: float) -> float:
    """Commanded equivalence ratio at a power setting.

    SPARK engines enrich toward and past stoichiometric as power rises (knock
    and thermal protection). COMPRESSION engines are quality-governed: phi
    rises with load but stays globally lean.
    """
    comb = engine["thermodynamics"]["combustion"]
    phi_cruise = float(comb["equivalence_ratio_cruise"])
    phi_climb = float(comb["equivalence_ratio_climb"])
    f = float(np.clip(power_fraction, 0.0, 1.0))
    if combustion_mode(engine) == "COMPRESSION":
        # Diesel: idle is very lean, full load approaches the smoke limit.
        return float(np.clip(0.25 + (phi_climb - 0.25) * f, 0.15, phi_climb))
    # Spark: throttled engine holds near-stoichiometric, enriching at high power.
    return float(phi_cruise + (phi_climb - phi_cruise) * max(0.0, (f - 0.7) / 0.3))


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Combustion model utilities")
    ap.add_argument("--generate", action="store_true", help="generate the flame lookup table")
    ap.add_argument("--engine", default="rotax_915is")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.generate:
        p = generate_table(args.engine, force=args.force)
        print(f"wrote {p}")
    else:
        eng = config.load_engine(args.engine)
        print(f"cantera available : {cantera_available()}")
        print(f"fuel surrogate    : {eng['fuel_properties']['surrogate']}")
        print(f"cantera fuel blend: {_fuel_string(eng)}")
        print(f"stoich AFR        : {stoichiometric_afr(eng):.2f}")
        print()
        print(" phi   T_ad[K] (35 bar, 300 K intake)")
        for phi in (0.6, 0.8, 0.95, 1.0, 1.05, 1.15, 1.3):
            st = adiabatic_flame(phi, 300.0, 35.0, args.engine, prefer_cantera=True)
            print(f" {phi:4.2f}  {st.t_adiabatic_k:8.1f}   [{st.source}]")
