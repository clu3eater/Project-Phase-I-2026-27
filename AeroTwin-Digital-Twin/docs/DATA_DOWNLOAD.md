# Getting the project's data

The code, and the trained models the twin loads at runtime (`data/models/`),
come with the repository through Git LFS (see the main
[README](../README.md#2--download-and-start)). That is enough to run and
demonstrate the twin: nothing below is needed for that.

## What this repository does not include

This repository was started fresh from another project's codebase, without
that project's GitHub Releases. Those releases held the larger data sets used
to **train and re-measure** the models — none of it is needed to run the twin,
only to reproduce a training run or a benchmark figure from scratch:

| Not included | What it was | Needed for |
|---|---|---|
| The run-to-failure training fleet (`data/synthetic/`) | Simulated engines the models are trained and evaluated on | Retraining |
| The hazard-scenario fleet (`data/synthetic_hazard/`) | Variant used in the RUL ceiling work | Retraining |
| NGAFID "2 days" flight-data benchmark | Published third-party benchmark | Re-measuring one benchmark figure |
| Recorded flights, older trained models, Rotax manuals, promo material | Historical / reference material | Not needed to run or evaluate the twin |

If you need any of this to reproduce a specific figure, say which one and
where it needs to come from — it is not something this README can safely
invent an instruction for.

## What IS available on demand

**NASA C-MAPSS** (the turbofan benchmark `layer3_ai/tests/test_cmapss.py`
checks against) is fetched directly from NASA, not redistributed here:

```bash
python scripts/fetch_benchmarks.py            # fetch what is missing
python scripts/fetch_benchmarks.py --check    # verify, download nothing
```

It checks the archive against a recorded SHA-256 before extracting it into
`data/benchmarks/`.

## What is deliberately NOT included, on any copy

`data/keys/` — the station's signing keys, audit key and user password store.
They are never shared. A fresh copy creates its own on first run, with one
account per role and random passwords written to
`data/keys/FIRST_RUN_CREDENTIALS.txt`.

`data/twin_state/` — the saved life of the local engine. A fresh copy starts
the engine as-new.

## Real engine data: NASA ACES (Altus II UAV, Rotax 912)

Real flight logs of a Rotax 912 (the same family as the 915 iS) in the Altus II UAV,
2002, 1 sample per second. Used only to check the physics model against a real engine
(`scripts/eval_aces_realdata.py`); it has no labelled faults and nothing is trained on it.

1. Create a free NASA Earthdata account: <https://urs.earthdata.nasa.gov>.
2. Download the 15 `aces1am_2002_DDD.tar` files of collection
   [C1977826980-GHRC_DAAC](https://search.earthdata.nasa.gov/search/granules?p=C1977826980-GHRC_DAAC)
   into `data/external/aces/` (git-ignored; about 1 GB). Day 233 is listed but not served.
3. `python scripts/aces_extract.py` then `python scripts/eval_aces_realdata.py`.
