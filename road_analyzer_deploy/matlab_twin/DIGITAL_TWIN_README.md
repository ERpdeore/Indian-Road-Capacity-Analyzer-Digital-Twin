# Digital Twin — MATLAB / RoadRunner side

The web dashboard computes the twin in Python (`road_analyzer/digital_twin_engine.py`)
and needs no MATLAB. The scripts in this folder reproduce or visualise the same
result locally.

## What the twin models

Both roads carry the **same demand** `q` (PCU/h): the observed volume if one was
entered, otherwise the LOS-C service volume of the ideal road, `0.70 × C0`.

| | Ideal road | Current road |
|---|---|---|
| Capacity | `C0` (Indo-HCM Table 5.4 or Eq. 5.4) | `C = C0 × F_OP × F_BS × F_AC` (Eq. 5.5) `× F_W × F_R` (project extensions) |
| Free-flow speed | operating speed `v_f` | `v_f × roughness speed ratio` (1 unless IRI > 3 is entered) |
| Fundamental diagram | Greenshields `v = v_f (1 − k/k_j)`, `k_j = 4 C0 / v_f` | same form, `k_j' = 4 C / v_f'` |

* `q ≤ C`: no queue; speed and density from the uncongested branch.
* `q > C`: the section is a bottleneck. Stored queue `n(t) = (q − C) t`;
  the queue tail moves upstream at the LWR shockwave speed
  `w = (C − q) / (k_Q − k_A)`, where `k_A` is the arriving density and `k_Q`
  the queued density on the congested branch at flow `C`.

A capacity loss therefore shows up as **slower traffic and a growing queue**,
not as fewer vehicles on the road.

## Files

| File | Purpose |
|---|---|
| `create_digital_twin_model.m` | Builds `road_digital_twin.slx`: two point queues `dQ/dt = (q − C)/3600`, `Q ≥ 0` |
| `run_digital_twin.m` | Runs the model for one `*_roadrunner_capacity.json` (or `*_analysis.json`) and writes `dt_output.json` |
| `roadtwin.m` | 2-D MATLAB animation, ideal vs current road, speeds and spacing from the twin |
| `auto_import_roadrunner.m` | Imports the `.xodr` into RoadRunner and places traffic |
| `build_traffic.m` | Places vehicles at the twin density: spacing = `1000 / (k_PCU / avg PCU)` m |
| `add_vehicles_ideal.m`, `add_vehicles_nonideal.m` | Thin wrappers around `build_traffic.m` |
| `add_defects_to_scene.m` | Draws each detected obstruction at its measured lateral position |
| `twin_config.m` | Vehicle mix, lengths, minimum gap, defect marker sizes |
| `twin_assets.m` | Finds the vehicle / prop assets in your RoadRunner project |
| `run_ideal_digital_twin.bat`, `run_nonideal_digital_twin.bat` | One-click launchers (set `MATLAB_EXE` if MATLAB is not in the default path) |

## Use

1. Analyse a photo on the dashboard and download the **Digital Twin Bundle (.zip)**.
2. Extract it into an **empty folder**; keep every file together.
3. Double-click **`run_2d_digital_twin.bat`** first. It needs only MATLAB and
   proves the setup works.
4. For RoadRunner: **`run_ideal_digital_twin.bat`**, then **`run_nonideal_digital_twin.bat`**.
   The first run asks for your RoadRunner project folder and saves it in
   `roadrunner_project.txt`.
5. Optional Simulink check: in MATLAB, `run_digital_twin('<photo>_roadrunner_capacity.json')`.

| Setting | How it is found |
|---|---|
| MATLAB | `MATLAB_EXE` env var → `matlab` on PATH → newest `C:\Program Files\MATLAB\R20*` |
| RoadRunner project | `RR_PROJECT_FOLDER` env var → `roadrunner_project.txt` → folder picker |
| RoadRunner install | `RR_INSTALL_FOLDER` env var → newest `C:\Program Files\RoadRunner R20*` → `roadrunnerSetup` default |

**If nothing seems to happen:** every run writes `twin_log.txt` in the same
folder and shows a popup on error. Send that file when asking for help.

## Limits

* One photo gives one cross-section. The `.xodr` road is a straight 40 m
  segment; along-road spacing of defects is cosmetic, lateral position is measured.
* Defect markers in RoadRunner are enlarged for visibility (`twin_config.m`).
* The vehicle mix in `twin_config.m` is an assumption; replace it with a
  classified count for the site.
* These `.m` files were revised without a MATLAB licence available; run
  `create_digital_twin_model` once and fix any block-parameter name your
  release reports.
