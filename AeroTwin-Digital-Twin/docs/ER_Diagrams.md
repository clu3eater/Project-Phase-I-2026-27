# Entity-Relationship Diagrams

This project has two separate ER diagrams, because they describe two different
things:

1. **The application database** — what the running ground-control-station
   software stores (users, aircraft, missions, defects, flight records).
2. **The ML training dataset** — the flat, simulation-generated data the
   fault-detection and remaining-life models are trained and evaluated on.

Both diagrams below are written in [Mermaid](https://mermaid.js.org/) syntax
(the ` ```mermaid ` fenced code blocks). They render automatically on GitHub,
in VS Code (with the Mermaid extension), and in most Markdown viewers — no
extra tool needed. Pasting either block into the
[Mermaid Live Editor](https://mermaid.live) also exports it directly as a PNG
or SVG image.

---

## 1. Project / application database ER diagram

Source: `docs/implementation_reference/database_er.mmd`

Commander, Operator, Maintainer and Engineer are *values* of a `role` column,
not four separate tables. Local users live in `data/keys/users.db`; the
central-fleet directory lives in PostgreSQL. Engine definitions are YAML
files (`configs/engines/*.yaml`), not a SQL table — `ENGINE_CONFIG_YAML` below
is explicitly marked as such.

**Storage boundaries** (which physical store each entity actually lives in):

| Store | Holds |
|---|---|
| `data/ops/squadron.db` | Aircraft, missions, defects, logbook, station |
| `data/keys/users.db` | Users |
| `data/history/flights.db` | Flights |
| `data/history/outbox.db` | Outbox |
| EdgeBuffer's SQLite path | Telemetry, alerts |
| Central PostgreSQL (`DT_FLEET_DSN`) | Stations, flight records, directory |
| `data/audit/audit.jsonl` | Audit records (a file, not a SQL table) |

**Reading the diagram:** a solid relationship line is a declared SQL foreign
key; a dashed line is a logical/application-level link, often crossing
between separate stores above — the database itself does not enforce dashed
links. Lines express the intended multiplicity, and an optional identifier
can be absent (e.g. a mission with no `approved_by` yet).

```mermaid
erDiagram
    USERS {
        string username PK
        string role
        string hash
        int disabled
        int must_change
        int token_epoch
    }
    ENGINE_CONFIG_YAML {
        string engine_key "YAML filename key"
        string identity
        object geometry
        object thermodynamics
    }
    AIRCRAFT {
        string tail PK
        string engine_key
        int released
        string release_by
        string limitations "JSON"
        string last_health "JSON"
    }
    MISSIONS {
        string id PK
        string tail
        string operator
        string created_by
        string approved_by
        string status
        float engine_hours
    }
    DEFECTS {
        int id PK
        string tail
        string mission_id
        string status
        string raised_by
        string disposed_by
        string rectified_by
    }
    LOGBOOK {
        int id PK
        string tail
        string by
        string role
        string kind
        string data "JSON"
    }
    STATION_LOCAL {
        string key PK
        string value
    }
    FLIGHTS {
        int flight_id PK
        string engine_key
        string aircraft_id
        float flight_hours
        float health_chi
        string health_json
        string events_json
    }
    OUTBOX {
        int id PK
        string record_uuid UK
        string kind
        string payload
        int synced
    }
    TELEMETRY {
        int id PK
        float t_s
        int uploaded
        string payload
    }
    ALERTS {
        int id PK
        float t_s
        string rule_id
        int level
        string category
    }
    STATIONS_CENTRAL {
        string station_id PK
        string name
        string api_key_hash
        boolean disabled
    }
    FLIGHT_RECORDS_CENTRAL {
        uuid record_uuid PK
        string station_id FK
        string engine_key
        string aircraft_id
        jsonb payload
    }
    DIRECTORY_CENTRAL {
        string username PK
        string role
        string hash
        boolean disabled
        string full_name
    }
    ENGINE_CONFIG_YAML ||..o{ AIRCRAFT : engine_key
    ENGINE_CONFIG_YAML ||..o{ FLIGHTS : engine_key
    AIRCRAFT o|..o{ MISSIONS : tail
    USERS o|..o{ MISSIONS : "commander creates approves"
    USERS o|..o{ MISSIONS : "operator assigned"
    USERS o|..o{ AIRCRAFT : "maintainer releases"
    AIRCRAFT ||..o{ DEFECTS : tail
    MISSIONS o|..o{ DEFECTS : mission_id
    USERS o|..o{ DEFECTS : "raise disposition rectify"
    AIRCRAFT o|..o{ LOGBOOK : tail
    USERS o|..o{ LOGBOOK : by
    AIRCRAFT o|..o{ FLIGHTS : aircraft_id
    FLIGHTS o|..o| OUTBOX : "serialized flight payload"
    OUTBOX o|..o| FLIGHT_RECORDS_CENTRAL : record_uuid
    STATIONS_CENTRAL ||--o{ FLIGHT_RECORDS_CENTRAL : station_id
    DIRECTORY_CENTRAL o|..o{ USERS : "username synchronized across stations"
```

---

## 2. ML dataset ER diagram

Source: `docs/implementation_reference/ml_dataset_er.mmd`

This is a **conceptual** decomposition of flat Parquet records and model
artifact files — not a claim that these exist as SQL tables. Sample identity
is engine + sortie + time; `SHADOW_RESIDUAL` and `TRAINING_TRUTH` are extra
*columns* on the same physical `SENSOR_SAMPLE` row, not separately generated
rows, and are kept logically distinct from the features so that a model never
trains on its own label by accident (leakage).

```mermaid
erDiagram
    DATASET_RUN {
        string manifest_path "manifest.json"
        string engine_key
        int seed
    }
    VIRTUAL_ENGINE {
        int engine_id "unique within dataset run"
        string split
        float life_hours
        boolean failed
    }
    SORTIE {
        int engine_id
        int sortie
        float flight_hours
    }
    SENSOR_SAMPLE {
        int engine_id
        int sortie
        float t_s
        float rpm
        float cht_max
        float oil_pressure
        float fuel_flow
    }
    SHADOW_RESIDUAL {
        float res_cht
        float res_coolant
        float res_oil_pressure
        float res_fuel_flow
    }
    TRAINING_TRUTH {
        float chi_true
        float rul_hours
        boolean censored
        float lab_fault "eight severity labels"
        float deg_factor "hidden physical state"
    }
    SORTIE_FEATURE_ROW {
        float mean_c
        float sd_c
        float rate_c
        float flight_hours
        float health_est
    }
    MODEL_ARTIFACT {
        string filename
        string ordered_features
        string model_type
    }
    HORIZON_CLASSIFIER {
        float horizon_h
        string backend
        string calibrator
    }
    EVALUATION_REPORT {
        string json_path
        float auc
        float brier
        float f1
    }
    DATASET_RUN ||..o{ VIRTUAL_ENGINE : manifest
    VIRTUAL_ENGINE ||..o{ SORTIE : flies
    SORTIE ||..o{ SENSOR_SAMPLE : records
    SENSOR_SAMPLE ||..o| SHADOW_RESIDUAL : "same physical row"
    SENSOR_SAMPLE ||..|| TRAINING_TRUTH : "same physical row label only"
    SORTIE ||..|| SORTIE_FEATURE_ROW : aggregates
    SENSOR_SAMPLE }o..o{ MODEL_ARTIFACT : "anomaly fault sequence inputs"
    SORTIE_FEATURE_ROW }o..o{ MODEL_ARTIFACT : "RUL survival inputs"
    TRAINING_TRUTH }o..o{ MODEL_ARTIFACT : "offline targets only"
    MODEL_ARTIFACT ||..o{ HORIZON_CLASSIFIER : "survival head only"
    MODEL_ARTIFACT ||..o{ EVALUATION_REPORT : scored
```

---

## Where these came from

Both diagrams, and the fuller discussion behind them (why each design choice
was made, what each table's columns mean, the actual SQL and dataclass
definitions they were read from), live in
[`docs/implementation_reference/ASTRA_Engine_ML_Datasets_Database.md`](implementation_reference/ASTRA_Engine_ML_Datasets_Database.md)
— sections 8 and 9. This file is a focused extract of just the two diagrams
for quick reference and submission, not a replacement for that document.
