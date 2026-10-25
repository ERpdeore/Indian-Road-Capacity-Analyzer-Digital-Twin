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
| **DSV** | Design Service Volume = 0.70 C (Table 5.4, "computed for LOS-C"; note Table 5.7 lets divided-road LOS-C run to V/C 0.75) | — |
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

\*Derived from sections with 1–3 km signal spacing; "applicable for similar site conditions" (5.4.4.2). The ten-lane lane capacity of 2000 PCU/h corresponds to 89 km/h under Eq. 5.4, above its 40–80 km/h range.

Or, divided roads only, from the measured operating speed V at a **base section**:
`C_lane = 20.11 V + 210.8` (Eq. 5.4), valid 40–80 km/h, ≥ 100 free cars (5.4.5); C0 = C_lane × lanes.

**Step 2 — Side friction** (Eq. 5.5): `C = C0 × F_OP × F_BS × F_AC`

| Factor | Basis | Values |
|---|---|---|
| F_OP long-term parking (T 5.9) | kerb length occupied / segment length | < 25%: 0.70 · 25–50%: 0.65 · > 50%: 0.40 |
| F_OP short-term parking (T 5.10) | park-in + park-out per km per h | ≤ 500: 0.65 · > 500: 0.40 |
| F_BS bus stop (T 5.11) | buses/h | kerbside 0.80 / 0.60 · bay 0.90 / 0.80 (≤ 30 / > 30) |
| F_AC access points (T 5.12) | entry + exit veh/h | < 200: 0.90 · 200–500: 0.80 · > 500: 0.70 |

**Step 3 — Flow in PCU/h**: classified 5-min count × 12, × Table 5.3 medians
(existing road) or Table 5.2 (planning), or `Se × N` (Eq. 5.2/5.3).

**Step 4 — LOS** from V/C (Tables 5.6 / 5.7). Band edges as printed: A is strict
("< 0.15"), so V/C = 0.15 on a divided road is LOS B.

| LOS | Undivided V/C | Divided V/C |
|---|---|---|
| A | < 0.35 | < 0.15 |
| B | 0.36–0.55 | 0.15–0.45 |
| C | 0.56–0.70 | 0.46–0.75 |
| D | 0.71–0.85 | 0.76–0.85 |
| E | 0.86–1.00 | 0.86–1.00 |
| F | > 1.00 | > 1.00 |

Verified against manual Examples 5.5.1–5.5.4 in `tests/test_indo_hcm.py`.

## 3A. Single-lane and intermediate-lane roads (Indo-HCM Chapter 2)

Chapter 5 has no single-lane or intermediate-lane class. Indo-HCM covers them only in
**Chapter 2 (interurban roads)**, so the dashboard takes them from there. Indo-HCM has
no 4-lane or 6-lane **undivided** class in any chapter, so those are not offered.

| Item | Single lane | Intermediate lane | Source |
|---|---|---|---|
| Carriageway | 3.75 m, two-way | 5.5–6.0 m, two-way | 2.3.2, 2.3.3 |
| Base capacity C (both directions) | 800 PCU/h at 50 km/h | 2150 PCU/h at 75 km/h | 2.10.1 |
| From operating speed V | C = 187 + 12.4 V | C = 830 + 16.4 V | Eq. 2.12 / 2.11 |
| Width factor f_w | 3.50 m 0.76 · 3.75 1.00 · 4.00 1.24 · 4.20 1.43 | 5.5 m 1.00 · 5.6 1.03 · 5.8 1.09 · 6.0 1.15 | Table 2.6 |
| Roughness | C = 945 − 25 IRI | C = 2956 − 199 IRI | Eq. 2.20 / 2.19 |
| PCU | Table 2.4 single-lane medians | Table 2.4 two-lane/intermediate medians | Table 2.4 |
| LOS (V/C) | A ≤ 0.15, B ≤ 0.30, C ≤ 0.50, D ≤ 0.80, E ≤ 1.00 | A < 0.25, B ≤ 0.45, C ≤ 0.60, D ≤ 0.75, E ≤ 1.00 | Tables 2.10 / 2.9 |

C0 = base capacity × f_w (linear interpolation between printed widths; end value outside
the range). Roughness is used in relative form, F_R = C(IRI) / C(3), above IRI 3.

**Assumptions to state** (shown on every result for these roads):
1. Chapter 2 values come from interurban (rural) roads and are applied to an urban street.
2. Chapter 2 has no side-friction factors; Chapter 5's F_OP, F_BS, F_AC are applied.
3. Service volume: Chapter 2 gives no hourly DSV for these roads; the LOS-C upper V/C of
   the chapter's own table is used (0.50 single, 0.60 intermediate).
4. PCU: "car" = standard car 1.00; mini bus has no Table 2.4 value, Table 5.2's 1.80 is used.
5. Se (Eq. 5.2/5.3) is not used for these roads.

## 4. Project extensions (`extensions.py`) — not Indo-HCM

Indo-HCM has **no factor** for vendors, carts, garbage, barricades or potholes.

`C_extended = C_IndoHCM × F_W × F_R`

**F_W — effective width** (vendors, carts, garbage, barricades, potholes)
1. Width of each obstruction across the carriageway, from the photo.
2. Clear road: drivers keep 0.25 m from each kerb (Indo-HCM 5.1.2), so the clear
   effective width is W − 0.5 m.
3. Each obstruction removes its width + 0.25 m on each side. At a kerb, its shy band
   overlaps the kerb band and is counted once. Overlapping obstructions are merged.
4. `F_W = effective width with obstructions / clear effective width` (proportional), or
   `F_W = (C0 − lost effective width × 428.6) / C0`, using the capacity-per-metre slope
   between the four- and six-lane rows of Table 5.4.

Example, 7.0 m four-lane divided carriageway (clear effective width 6.5 m):
vendor at the kerb occupying 1.0 m → usable 5.5 m → F_W = 0.846.

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
| C — queue discharge (standard method, **not** in Indo-HCM) | capacity of the obstructed section | only while a queue stands behind it |
| Volume count alone | **demand, not capacity** | always — use for V/C and LOS |

Field capacity loss = (C_clear − C_obstructed) / C_clear. Compare with the
dashboard over several sites; report MAPE, RMSE and bias (`/api/field/compare`).

Run: `python -m road_analyzer.field_validation vehicles.csv 60 divided_4lane`

## 6. Advantages and limitations

**Advantages**
- Capacity values calibrated on Indian mixed traffic (67 sections in Table 5.1, 10 cities).
- Needs only width and a side-friction description, or a car free-speed survey.
- Every number in the result is traceable to a table, equation or stated assumption.

**Limitations**
- Indo-HCM values are national medians from small samples (Table 5.1: 2 base sections
  for two-lane undivided, 3 for ten-lane).
- Where Table 5.3 has no PCU ("-"), the Table 5.2 median is used (project choice).
- F_W and F_R are assumptions until validated with field data.
- A single photo gives one cross-section: widths are uncorrected for perspective,
  along-road positions are not measured, parking intensity is not visible.
- Eq. 5.4 is valid only for base sections of divided roads at 40–80 km/h.
- LOS requires a measured volume.

## 7. Errors found in the printed manual

Checked against the manual's own tables and arithmetic.

| Location | Printed | Correct |
|---|---|---|
| Eq. 5E.4 (p. 5-30) | PCU = (V_i/V_c)/(A_i/A_c) | (V_c/V_i)/(A_c/A_i). As printed, a bus (area ratio 3.96) would need to travel 18× faster than a car to reach Table 5.3's 4.60; the corrected form gives 4.60 at a realistic V_c/V_i = 1.16 |
| **Example 5.5.2** (p. 5-20) | MAT 12 × 5.90 = **710**; total 5228 PCU/h; V/C 0.77 → **LOS D** | 12 × 5.90 = 70.8; total **4587** PCU/h; V/C 0.67 → **LOS C**. Also uses mini-bus 2.61 (ten-lane value) on an eight-lane road; Table 5.3 gives 2.16 |
| Example 5.5.1 (p. 5-18) | total 3153 PCU/h; mini bus 44 × 2.16 = 101 | column sums to 3214; 44 × 2.16 = 95; exact total 3206. Conclusion (LOS C, then F with bus stop) unchanged |
| Example 5.5.4 (p. 5-23) | total 1459; 1890 − 1457 = 433 | printed rows sum to 1456 (mini bus 20 × 2.29 = 46 not 42; cycle rickshaw 12 × 2.04 = 24 not 29); with Table 5.3 medians 1454 → spare ≈ 436 PCU/h. Mini bus 2.29 and LCV 2.28 appear in neither PCU table |
| Example 5.5.3 (p. 5-21) | TAT 3.22 in the expression | table uses 3.90; the 1971 total matches 3.90 |
| Table 5.3 (p. 5-6) | two-lane cycle rickshaw: 1.80 in the Range column, Median "-" | code uses the Table 5.2 median 1.80 |
| 5.4.7.1 | parking: "Table 5.8" long-term, "Table 5.9" short-term | Tables 5.9 (length) and 5.10 (manoeuvres) |
| Table citations in 5.4.4.2 and Examples 5.5.1–5.5.4 | DSV "in Tables 5.6/5.7"; capacity "Table 5.3"; LOS "Table 7"/"5.6"; PCU "Tables 5.1/5.2"; "vide Table 5.11" | DSV and capacity: Table 5.4; divided LOS: Table 5.7; PCU: Table 5.3 (existing) or 5.2 (planning) |
| Shares in Eq. 5.2/5.3 (p. 5-7) | "Percentage composition" | must be fractions (Example 5.5.1 uses 0.360); percentages give Se ≈ −29 |
| Eq. 2.11 (p. 2-16) | "base capacity of intermediate lane road at 75 km/h is around 2150" | 830 + 16.4 × 75 = 2060; the code uses the stated 2150 as the base value and Eq. 2.11 only for a measured speed |
| Trap length | 5.3: 50–75 m | Annex 5C: 60–75 m (manual is inconsistent) |
| Free-flow definition | 5.2.2 "time gap > 8 s"; 5E.5 "headway ≥ 8 s" | code uses headway > 8 s to the vehicle ahead |
