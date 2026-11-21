"""Convert NASA ACES Altus II flight logs into engine tables the twin can read.

THE DATA. NASA's ACES campaign (2002) flew the Altus II UAV -- a General
Atomics airframe powered by a Rotax 912 (1352 cc, liquid-cooled heads) with a
two-stage turbocharger and electronic fuel injection. It is the same engine
family as the Rotax 915 iS this twin models, in a UAV, logged at 1 Hz. It is
the only public source of real flight data from a Rotax-family engine found.

    Source: NASA GHRC DAAC, "ACES Aircraft and Mechanical Data",
            collection C1977826980-GHRC_DAAC (free Earthdata login).
    Files:  data/external/aces/aces1am_2002_DDD.tar (never committed).

WHAT IT IS NOT. A weather-research campaign: there are no labelled engine
faults. It can test whether the twin gets a HEALTHY Rotax right, and how real
sensors behave (resolution, dropouts, noise). It cannot train a fault detector.

UNITS, established from the data rather than assumed:
  * engine temperatures are degF -- the cold engine before start reads
    70-79 degF against a 26 degC ambient;
  * outside air temperature is not logged in flight ("Atmos Temp" stays at
    25-28 over a climb to 12,000 ft), so it is derived from density altitude
    and pressure altitude, which gives 24.8 degC on that same ground run;
  * -55, -58 and -60 are the logger's invalid codes, not temperatures.

The channel names are stored as a character matrix whose columns overlap:
each column holds one name followed by the start of the next. They are split
by removing the longest suffix that is also the next column's prefix.

Run:  python scripts/aces_extract.py   ->  data/external/aces/aces_engine.parquet
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data" / "external" / "aces"

# name as stored -> (output column, conversion)
F_TO_C = lambda f: (f - 32.0) * 5.0 / 9.0  # noqa: E731
CHANNELS = {
    "Engine SpeedRPM": ("rpm", None),
    "MAP": ("map_bar", lambda v: v * 0.0338639),
    "Altitude MSLAlt": ("altitude_ft", None),
    "Density Alt.Alt": ("density_alt_ft", None),
    "Static Press": ("static_inhg", None),
    "AirspeedAir": ("kias", None),
    "True AirspdFron": ("ktas", None),
    "Throttle Cmd": ("throttle_cmd_pct", None),
    "EFI TAP": ("throttle_angle_pct", None),
    "CHT": ("cht_c", F_TO_C),
    "Water Temp": ("coolant_c", F_TO_C),
    "Oil Temp": ("oil_temperature_c", F_TO_C),
    "Oil   Press": ("oil_pressure_psi", None),
    "EGT 1": ("egt1_c", F_TO_C),
    "EGT 2": ("egt2_c", F_TO_C),
    "EGT 3": ("egt3_c", F_TO_C),
    "EGT 4": ("egt4_c", F_TO_C),
    # FUEL BURNED SO FAR, not a flow: it climbs through each flight (14, 45,
    # 91, 137 lb over consecutive hours) whatever its "lb/h" label says. The
    # flow is its rate of rise -- see `_fuel_flow`.
    "EFI Fuel BurnHP": ("fuel_burned_lb", None),
    "Fuel  Press": ("fuel_pressure_psi", None),
    "Cool Flp Pos": ("cowl_flap_pct", None),
    "Bat 1 Volt": ("battery_v", None),
    "Turbo RPMTSI": ("turbo_rpm", None),
    "Cmp out Press": ("compressor_out_inhg", None),
    "GPS Timesecsec": ("gps_time_s", None),
}
INVALID = (-60.0, -58.0, -55.0)


def _columns(char_matrix) -> list[str]:
    a = np.asarray(char_matrix)
    cols = ["".join(a[:, j]).replace("\x00", " ").replace("\x7f", " ") for j in range(a.shape[1])]
    out = []
    for k, s in enumerate(cols):
        nxt = cols[k + 1] if k + 1 < len(cols) else ""
        overlap = next((n for n in range(len(s) - 1, 0, -1) if nxt.startswith(s[-n:])), 0)
        out.append(s[: len(s) - overlap].strip())
    return out


def _fuel_flow(burned_lb, window_s: int = 60):
    """Fuel flow in L/h from the running total: the rise over a centred
    minute (the total is logged to 0.01 lb), avgas at 0.72 kg/L."""
    if burned_lb is None:
        return np.nan
    b = pd.Series(burned_lb, dtype=float)
    rate_lb_s = (b.shift(-window_s // 2) - b.shift(window_s // 2)) / window_s
    lph = rate_lb_s * 3600.0 * 0.45359 / 0.72
    return lph.where((lph >= 0) & (lph < 60)).to_numpy()


def _one_file(tf: tarfile.TarFile, member: tarfile.TarInfo, day: str) -> pd.DataFrame | None:
    from scipy.io import loadmat

    raw = loadmat(tf.extractfile(member), chars_as_strings=False)
    data = raw["data"]
    names = _columns(raw["m_name"])
    index = {}
    for n, k in ((n, k) for k, n in enumerate(names)):
        index.setdefault(n.split("\n")[0].strip(), k)
    frame = {}
    for stored, (col, conv) in CHANNELS.items():
        k = index.get(stored)
        if k is None:
            continue
        v = data[k].astype(float)
        v[np.isin(v, INVALID)] = np.nan
        frame[col] = conv(v) if conv else v
    if "rpm" not in frame:
        return None
    df = pd.DataFrame(frame)
    df.insert(0, "day", day)
    df.insert(1, "file", member.name)
    df.insert(2, "sample", np.arange(len(df)))
    # Pressure altitude from static pressure, then OAT from density altitude:
    #   DA = PA + 118.8 ft/degC x (OAT - ISA(PA)).
    pa = (1.0 - (df["static_inhg"] / 29.92126) ** 0.190284) * 145366.45
    df["pressure_alt_ft"] = pa.where(df["static_inhg"] > 5)
    isa = 15.0 - 1.98 * df["pressure_alt_ft"] / 1000.0
    df["oat_c"] = isa + (df["density_alt_ft"] - df["pressure_alt_ft"]) / 118.8
    df["airspeed_kmh"] = df["ktas"] * 1.852
    df["fuel_flow_lph"] = _fuel_flow(df.get("fuel_burned_lb"))
    egts = df[[c for c in ("egt1_c", "egt2_c", "egt3_c", "egt4_c") if c in df]]
    df["egt_max_c"] = egts.max(axis=1)
    df["egt_spread_c"] = egts.max(axis=1) - egts.min(axis=1)
    return df


def main() -> int:
    tars = sorted(SRC.glob("aces1am_2002_*.tar"))
    if not tars:
        print(f"no ACES archives in {SRC}; see docs/DATA_DOWNLOAD.md")
        return 1
    frames = []
    seen = set()
    for t in tars:
        day = t.stem.split("_")[-1]
        with tarfile.open(t) as tf:
            for m in tf.getmembers():
                if Path(m.name).name.startswith("M") and m.name.endswith(".mat"):
                    df = _one_file(tf, m, day)
                    # Some archives carry a file twice ("M088002.mat" and
                    # "M088002a.mat", identical data); count it once.
                    key = None if df is None else hash(df["rpm"].to_numpy().tobytes())
                    if key in seen:
                        print(f"  {t.name} {m.name}: duplicate of an earlier file, skipped")
                        continue
                    seen.add(key)
                    if df is not None:
                        frames.append(df)
                        run = (df["rpm"] > 1500).sum()
                        print(f"  {t.name} {m.name}: {len(df):5d} s, engine running {run:5d} s")
    out = pd.concat(frames, ignore_index=True)
    dest = SRC / "aces_engine.parquet"
    out.to_parquet(dest)
    running = out["rpm"] > 1500
    print(f"\n{len(out):,} samples ({len(out)/3600:.1f} h) from {len(frames)} files; "
          f"engine running {running.sum()/3600:.1f} h; airborne "
          f"{((out['kias'] > 40) & running).sum()/3600:.1f} h -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
