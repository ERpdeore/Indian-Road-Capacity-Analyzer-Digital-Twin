# Indian Road Capacity Analyzer — Digital Twin

Estimates how much mid-block capacity an urban road loses to on-carriageway
obstructions seen in a photo or video, following the **Indo-HCM 2017**
(CSIR-CRRI) urban-road framework, and shows the traffic consequence as a
macroscopic digital twin.

Live code: `road_analyzer_deploy/` · deployment: `road_analyzer_deploy/DEPLOY.md` ·
MATLAB/RoadRunner: `road_analyzer_deploy/matlab_twin/DIGITAL_TWIN_README.md`

## Method

1. **Detection** — YOLOv8s (`models/best.pt`) finds barricades, potholes,
   illegally parked vehicles, street vendors, carts and garbage. Vendor/cart
   boxes overlapping a `vehicle` box are discarded (auto-rickshaw confusion).
2. **Geometry** — the photo looks along the road with both carriageway edges at
   the frame borders, so lateral position = x-pixel × (width / image width).
   Perspective is not corrected; widths are estimates.
3. **Capacity** — two results, never mixed (full method: `road_analyzer_deploy/docs/METHODOLOGY.md`)

   ```
   Indo-HCM:   C_HCM = C0 × F_OP × F_BS × F_AC      Eq. 5.5, Tables 5.4, 5.9–5.12
   Extended:   C     = C_HCM × F_W × F_R            project extensions (validate!)
   ```

   - `C0`: Table 5.4, or Eq. 5.4 `C_lane = 20.11 V + 210.8` from the operating speed
     measured at a base section (divided roads, 40–80 km/h).
   - `F_W`: usable width for vendors, carts, garbage, barricades, potholes
     (0.25 m shy distance, overlaps merged). `F_R`: optional roughness from IRI.
   - Parked vehicles act only through Indo-HCM `F_OP`, never through `F_W`.
   - LOS (Tables 5.6/5.7) only when an observed volume is entered; DSV = 0.70 C.
4. **Digital twin** — the same demand is run through a Greenshields fundamental
   diagram calibrated to `C0` and to `C`; when demand exceeds `C` a deterministic
   queue and LWR shockwave give queue size, queue length and delay.
5. **Outputs** — department-routed PDF, OpenDRIVE `.xodr` (ideal and current),
   capacity JSON for MATLAB/RoadRunner, Excel defect log.

## Field validation

`road_analyzer/field_validation.py` turns a survey video (vehicle type + trap
entry/exit times) into field capacity by the manual's methods — operating speed
+ Eq. 5.4, Greenshields speed–flow fit (Annex 5E.4) or queue discharge — and
compares it with the dashboard (MAPE, RMSE, bias). A volume count alone is
demand, not capacity. Template: `docs/field_templates/vehicles_template.csv`.

## Tests

`cd road_analyzer_deploy && python -m pytest -q` — reproduces Indo-HCM Tables
5.4/5.5 and Examples 5.5.1–5.5.4.

## Run locally

```bash
cd road_analyzer_deploy
pip install -r requirements.txt
uvicorn road_analyzer.app:app --reload --port 8000
```
