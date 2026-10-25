# Methodology — capacity of obstructed urban roads

Reference: **Indo-HCM 2017 (CSIR-CRRI), Chapter 5 "Urban Roads"**.
Code: `road_analyzer/indo_hcm.py` (manual only), `road_analyzer/extensions.py`
(project additions), `road_analyzer/field_validation.py` (survey analysis).

---

## 1. Key terms

| Term | Meaning | Changes with time of day? |
|---|---|---|
| **Volume (V)** | Vehicles that actually pass, in PCU/h | Yes — demand |
| **Capacity (C)** | Maximum flow the road can carry | No — only when road conditions change |
| **PCU** | Passenger Car Unit: one car = 1.0 (Tables 5.2/5.3) | — |
| **Operating speed** | 85th percentile free-flow speed of cars (headway > 8 s) | — |
| **Space-mean speed (SMS)** | Trap length ÷ mean travel time (Eq. 5E.2) | — |
| **DSV** | Design Service Volume = capacity at LOS-C = 0.70 C | — |
| **V/C** | Volume ÷ capacity → LOS | Yes |

## 2. Scope of Indo-HCM Chapter 5 (Section 5.1)

- Urban **mid-block segments** between controlled intersections, signals ≥ 1 km apart.
- Road types: **two-lane undivided**, **4/6/8/10-lane divided**. No one-way class,
  no 4-lane undivided. A one-way street is analysed as one direction of a
  divided road with the same lanes (stated assumption).
- Plain terrain. Base section (Table 5B.1): paved width 7.0/10.5/14.0/17.5 m
  per direction (±0.5 m), sight distance > 300 m, low side friction, IRI < 3.

## 3. Indo-HCM procedure (what the code does in `indo_hcm.py`)

**Step 1 — Base capacity C0**

| Road | C0 (PCU/h) | Per lane | DSV |
|---|---|---|---|
| Two-lane undivided (both directions) | 2400 | 1200 | 1680 |
| Four-lane divided (per direction) | 2700 | 1350 | 1890 |
| Six-lane divided | 4200 | 1400 | 2940 |
| Eight-lane divided* | 6800 | 1700 | 4760 |
| Ten-lane divided* | 10000 | 2000 | 7000 |

\*Only where signal spacing is 1–3 km (5.4.4.2).

Or, divided roads only, from the measured operating speed V at a **base section**:
`C_lane = 20.11 V + 210.8` (Eq. 5.4), valid 40–80 km/h, ≥ 100 free cars; C0 = C_lane × lanes.

**Step 2 — Side friction** (Eq. 5.5): `C = C0 × F_OP × F_BS × F_AC`

| Factor | Basis | Values |
|---|---|---|
| F_OP long-term parking (T 5.9) | kerb length occupied / segment length | < 25%: 0.70 · 25–50%: 0.65 · > 50%: 0.40 |
| F_OP short-term parking (T 5.10) | park-in + park-out per km per h | ≤ 500: 0.65 · > 500: 0.40 |
| F_BS bus stop (T 5.11) | buses/h | kerbside 0.80 / 0.60 · bay 0.90 / 0.80 (≤ 30 / > 30) |
| F_AC access points (T 5.12) | entry + exit veh/h | < 200: 0.90 · 200–500: 0.80 · > 500: 0.70 |

**Step 3 — Flow in PCU/h**: classified 5-min count × 12, × Table 5.3 medians
(existing road) or Table 5.2 (planning), or `Se × N` (Eq. 5.2/5.3).

**Step 4 — LOS** from V/C (Tables 5.6 / 5.7):

| LOS | Undivided V/C | Divided V/C |
|---|---|---|
| A | < 0.35 | < 0.15 |
| B | 0.36–0.55 | 0.15–0.45 |
| C | 0.56–0.70 | 0.46–0.75 |
| D | 0.71–0.85 | 0.76–0.85 |
| E | 0.86–1.00 | 0.86–1.00 |
| F | > 1.00 | > 1.00 |

Verified against manual Examples 5.5.1–5.5.4 in `tests/test_indo_hcm.py`.

## 4. Project extensions (`extensions.py`) — not Indo-HCM

Indo-HCM has **no factor** for vendors, carts, garbage, barricades or potholes.

`C_extended = C_IndoHCM × F_W × F_R`

**F_W — effective width** (vendors, carts, garbage, barricades, potholes)
1. Width of each obstruction across the carriageway, from the photo.
2. + 0.25 m shy distance on each side facing traffic (Indo-HCM kerb shyness, 5.1.2).
3. Overlapping obstructions merged (no double counting).
4. `F_W = usable width / total width` (proportional), or
   `F_W = (C0 − blocked × 428.6) / C0`, using the capacity-per-metre slope between the
   four- and six-lane rows of Table 5.4.

**F_R — roughness** (optional, only if IRI is measured): Chapter 2 Eq. 2.15
(`V = 104 − 6.8 IRI`) in relative form above IRI 3, then Eq. 5.4.

**Parking is never in F_W.** Indo-HCM's F_OP already includes the width a parked
vehicle occupies. Each detected object feeds exactly one factor.

**Pothole size** (IRC:82-2015, width only) sets repair priority; it does not
change capacity separately — its capacity effect is through F_W.

## 5. Field validation (`field_validation.py`)

Survey (Annex 5C/5D): video over a 50–75 m trap, record each vehicle's type and
entry/exit time → `docs/field_templates/vehicles_template.csv`.

| Method | Gives | When valid |
|---|---|---|
| A — operating speed + Eq. 5.4 | capacity | divided road, ≥ 100 free cars, any time |
| B — Greenshields speed–flow fit (Annex 5E.4) | capacity | data cover low **and** near-capacity flows |
| C — queue discharge | capacity of the obstructed section | only while a queue stands behind it |
| Volume count alone | **demand, not capacity** | always — use for V/C and LOS |

Field capacity loss = (C_clear − C_obstructed) / C_clear. Compare with the
dashboard over several sites; report MAPE, RMSE and bias (`/api/field/compare`).

Run: `python -m road_analyzer.field_validation vehicles.csv 60 divided_4lane`

## 6. Advantages and limitations

**Advantages**
- Capacity values calibrated on Indian mixed traffic (68 sections, 10 cities).
- Needs only width and a side-friction description, or a car free-speed survey.
- Every number in the result is traceable to a table, equation or stated assumption.

**Limitations**
- Indo-HCM values are national medians from small samples (Table 5.1).
- F_W and F_R are assumptions until validated with field data.
- A single photo gives one cross-section: widths are uncorrected for perspective,
  along-road positions are not measured, parking intensity is not visible.
- Eq. 5.4 is valid only for base sections of divided roads at 40–80 km/h.
- LOS requires a measured volume.

## 7. Errors found in the printed manual

| Location | Printed | Correct |
|---|---|---|
| Eq. 5E.4 | PCU = (V_i/V_c)/(A_i/A_c) | (V_c/V_i)/(A_c/A_i) — only this reproduces Table 5.3 (bus ≈ 4.6) |
| Example 5.5.1 | 3153 PCU/h | ≈ 3214 (its own column); 3206 with Table 5.3 medians |
| Example 5.5.4 | 1890 − 1457 = 433 | 1890 − 1459 = 431 |
| Examples / 5.4.7.1 | cite Tables 5.3, 5.6, 5.8 | 5.4, 5.7, 5.9/5.10 |
