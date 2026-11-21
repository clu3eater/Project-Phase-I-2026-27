# Rotax 915 iS performance table — provenance

`rotax_915is_om_performance.csv` is the manufacturer's performance table,
extracted verbatim from the **Operator's Manual 915 i Series, Ed. 0 Rev. 4**
(`engines manuals/OM_915i_Ed0_Rev4.pdf`), PDF pages **111–130**, table rows
numbered 1–988 in the manual. 941 rows parse as complete ten-column records; the
remainder are page furniture or split lines.

Tag for any value derived from it: **[OM]**.

| column | unit | meaning |
|---|---|---|
| `pdf_page` | – | page of the PDF the row was read from, for checking against the manual |
| `number` | – | row number printed in the manual |
| `rpm` | 1/min | engine speed: 4500, 5000, 5500, 5800 |
| `p_amb_bar` | bar | ambient pressure |
| `t_amb_c` | °C | ambient temperature |
| `throttle_pct` | % | throttle: 56.5, 72.0, 84.5, 94.1, 97.4, 98.8, 99.4, 100 |
| `alt_ft` | ft | pressure altitude: 0 to 22,999 in ten steps |
| `power_kw` | kW | engine power |
| `fuel_kg_h` | kg/h | fuel mass flow |
| `p_plenum_bar` | bar | plenum (manifold) pressure |
| `t_plenum_k` | K | plenum (manifold air) temperature |

The ambient temperature and altitude of each row place it in an ISA-deviation
block: **ISA −15, ISA, ISA +15 and ISA +30 °C** for 5500 and 5800 rpm; fewer
blocks at 4500 and 5000 rpm.

Why it is in the repository: the engine model's altitude lapse, charge-air
temperature and fuel flow were compared against this table during the review
of September 2026 (findings PHY-01, PHY-04, PHY-05, PHY-09) and disagreed with
it by up to 38 % of power above the critical altitude. A published
manufacturer table is the strongest reference available for this engine.

How it is used: `rotax_915is.yaml` names it under `performance_table`, and
`layer2_physics/om_table.py` reads it. The model keeps its sea-level torque
curve (pinned to the certified ratings) and takes from the table how power,
plenum pressure, plenum temperature and fuel consumption change with altitude
and ISA deviation, as ratios to sea level ISA at the same speed and throttle
position. See DEV-226 to DEV-232.

Gaps: 339 of the 1,280 cells in the full rpm x throttle x altitude x ISA grid
are not printed (the 56.5 % row at altitude, the hot blocks at 4500 and
5000 rpm). They are filled and flagged; tests compare only with printed cells.
Because the table is now an input to the model, agreement with it checks the
implementation. It is not independent validation, which needs rig data.

Extraction: PyMuPDF word positions grouped into lines; decimal commas converted
to points; no value was edited.
