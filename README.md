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
3. **Capacity** (all values in `road_analyzer/indo_hcm.py`)

   ```
   C = C0 × F_W × F_P × F_OP × F_BS × F_AC × F_PD
   ```

   | Term | Source | Input |
   |---|---|---|
   | `C0` base capacity | Indo-HCM Table 5 values; or `C_lane = 20.11 V + 210.8` × lanes when operating speed `V` is measured (divided roads) | road type, optional speed |
   | `F_OP` on-street parking | Indo-HCM factor (0.70 / 0.65 / 0.40) | detected parking or user input |
   | `F_BS` bus stop, `F_AC` access points, `F_PD` pedestrian crossings | Indo-HCM factors | user input |
   | `F_W` usable width | **project extension** — usable width ÷ total width; obstructions widened by the 0.25 m Indo-HCM shy distance; overlaps merged | vendors, carts, garbage, barricades |
   | `F_P` potholes | **project extension** — assumed speed drop per IRC:82 size class, converted to capacity with the Indo-HCM speed model | detected potholes |

   Service volume at LOS-C = 0.70 C. **LOS is reported only when an observed
   volume is entered** (Indo-HCM LOS is V/C-based).
4. **Digital twin** — the same demand is run through a Greenshields fundamental
   diagram calibrated to `C0` and to `C`; when demand exceeds `C` a deterministic
   queue and LWR shockwave give queue size, queue length and delay.
5. **Outputs** — department-routed PDF, OpenDRIVE `.xodr` (ideal and current),
   capacity JSON for MATLAB/RoadRunner, Excel defect log.

## Values to verify before citing

The Indo-HCM numbers were transcribed from the IRC:106 (2022) draft, which
carries the Indo-HCM urban method. Check every table in `indo_hcm.py` against
Indo-HCM 2017 Chapter 5 (§5.4.4–5.4.7). The pothole speed reductions
(5 / 10 / 20 %) and the vehicle mix are assumptions to be replaced with field data.

## Run locally

```bash
cd road_analyzer_deploy
pip install -r requirements.txt
uvicorn road_analyzer.app:app --reload --port 8000
```
