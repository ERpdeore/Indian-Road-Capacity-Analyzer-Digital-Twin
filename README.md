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
3. **Capacity** — Indo-HCM 2017 Chapter 5 (all values in `road_analyzer/indo_hcm.py`)

   ```
   C = C0 × F_OP × F_BS × F_AC        Indo-HCM Eq. 5.5
         × F_W × F_P                  project extensions
   ```

   | Term | Source | Input |
   |---|---|---|
   | `C0` base capacity | Table 5.4 (2400 two-lane undivided; 2700 / 4200 / 6800 / 10000 PCU/h per direction for 4/6/8/10-lane divided); or Eq. 5.4 `C_lane = 20.11 V + 210.8` × lanes when the car operating speed `V` is measured on a divided road | road type, optional speed |
   | `F_OP` on-street parking | Table 5.9 (long-term, by length occupied) / Table 5.10 (short-term, by manoeuvres) | detected parking or user input |
   | `F_BS` bus stops, `F_AC` access points | Tables 5.11, 5.12 | user input |
   | `F_W` usable width | **extension** — usable ÷ total width, obstructions widened by the 0.25 m shyness of §5.1.2, overlaps merged | vendors, carts, garbage, barricades |
   | `F_P` potholes | **extension** — assumed speed drop per IRC:82 size class, converted to capacity with Eq. 5.4 | detected potholes |

   DSV at LOS-C = 0.70 C (Table 5.4). LOS from V/C per Tables 5.6 / 5.7, only
   when an observed volume (PCU/h, Table 5.2/5.3 PCUs or Se Eq. 5.2/5.3) is entered.
   Indo-HCM has no one-way road class; a one-way street is analysed as one
   direction of the divided road with the same number of lanes (assumption).
4. **Digital twin** — the same demand is run through a Greenshields fundamental
   diagram calibrated to `C0` and to `C`; when demand exceeds `C` a deterministic
   queue and LWR shockwave give queue size, queue length and delay.
5. **Outputs** — department-routed PDF, OpenDRIVE `.xodr` (ideal and current),
   capacity JSON for MATLAB/RoadRunner, Excel defect log.

## What still needs field data

Indo-HCM values are empirical averages from 32 base and 36 non-base
sections in 10 metro cities (Table 5.1), and the manual lets the analyst
either adopt them or establish site values from field studies (§5.4).
For this project:
- measure the operating speed of ≥ 100 cars per site (§5.4.6) so C0 comes
  from Eq. 5.4 instead of the national table;
- validate F_W and F_P (not in Indo-HCM) with counts and speeds at
  obstructed vs clear sections; the pothole speed drops (5 / 10 / 20 %) and
  the vehicle mix are placeholders until then.

## Run locally

```bash
cd road_analyzer_deploy
pip install -r requirements.txt
uvicorn road_analyzer.app:app --reload --port 8000
```
