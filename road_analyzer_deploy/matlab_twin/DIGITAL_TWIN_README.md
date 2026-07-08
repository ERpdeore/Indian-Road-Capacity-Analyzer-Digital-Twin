# Digital Twin Integration Guide
## Indian Road Capacity Analyzer → MATLAB Simulink Digital Twin

---

## What you're getting

| File | Purpose |
|---|---|
| `create_digital_twin_model.m` | Run once to generate `road_digital_twin.slx` |
| `run_digital_twin.m` | Runs the Simulink simulation after every analysis |
| `digital_twin_bridge.py` | Python ↔ MATLAB bridge (triggers MATLAB, serves results) |
| `app.py` | Updated FastAPI app with `/api/digital-twin/*` endpoints |
| `dt_panel.html` | HTML panel to paste into `index.html` |
| `dt_styles.css` | CSS for the digital twin panel |
| `dt_app_addition.js` | JavaScript to paste into `app.js` |

---

## Step 1 — Copy files into your repo

```
your-repo/
├── road_analyzer_deploy/
│   └── road_analyzer/
│       ├── app.py                    ← Replace with the new app.py
│       ├── digital_twin_bridge.py    ← NEW — copy here
│       └── static/
│           ├── index.html            ← Add dt_panel.html content inside it
│           ├── style.css             ← Add dt_styles.css content at the bottom
│           └── app.js                ← Add dt_app_addition.js content at the bottom
│
└── matlab_twin/                      ← NEW folder — create this
    ├── create_digital_twin_model.m   ← Copy here
    └── run_digital_twin.m            ← Copy here
```

---

## Step 2 — Set up the matlab_twin folder

```bash
# From your repo root:
mkdir matlab_twin
# Copy the two .m files into matlab_twin/
```

---

## Step 3 — Update index.html

Open `road_analyzer/static/index.html`.

1. In the `<head>`, the CSS is already linked. Add this before `</head>`:
```html
<link rel="stylesheet" href="/static/style.css">
```
(already there — just add the dt_styles.css content **at the bottom** of `style.css`)

2. Find the line `</div>  <!-- end .wrap -->` and paste the entire
   contents of `dt_panel.html` just **before** that closing tag.

---

## Step 4 — Update app.js

Paste the entire contents of `dt_app_addition.js` at the **bottom** of `app.js`.

Then find your existing function that handles a successful analysis result
(look for where `result` is passed to the display function) and add:

```javascript
// RIGHT after you display the normal analysis result:
if (result.digital_twin_status === 'running') {
    dtShowPanel();
    dtStartPolling();
}
```

---

## Step 5 — Generate the Simulink model (do this once in MATLAB)

```matlab
% In MATLAB command window:
cd('path/to/your-repo/matlab_twin')
create_digital_twin_model
```

This creates `road_digital_twin.slx` in the `matlab_twin/` folder.

---

## Step 6 — Set MATLAB path (so Python can call it)

### Linux/Mac:
```bash
export MATLAB_EXE="/usr/local/MATLAB/R2026a/bin/matlab"
```

### Windows:
```cmd
set MATLAB_EXE=C:\Program Files\MATLAB\R2026a\bin\matlab.exe
```

Add this to your `.env` file or Render environment variables.

---

## Step 7 — Run your app

```bash
cd road_analyzer_deploy
uvicorn road_analyzer.app:app --reload --port 8000
```

Upload a road image → the analysis runs as before →
MATLAB launches automatically in the background →
the Digital Twin panel appears on the dashboard with:

- ✅ Ideal road vs Defect road side-by-side
- ✅ Capacity timeline chart (Simulink output)
- ✅ Vehicle speed degradation (Greenshields calibration)
- ✅ LOS meter (A → F animated)
- ✅ Animated vehicle flow (more vehicles = higher volume)
- ✅ Pothole depth speed impact indicator

---

## How the simulation works (for your viva)

```
Python analysis result (JSON)
        ↓
  digital_twin_bridge.py
        ↓ (subprocess)
  MATLAB R2026a
        ↓
  run_digital_twin.m
     - Reads ideal_cap, defect_cap, cap_loss_pct, LOS, pothole_speed_impact
     - Creates timeseries inputs → Simulink workspace
     - Runs road_digital_twin.slx (60-second simulation)
        ↓
     Simulink model:
       [Ideal DSV] → [Transfer Fcn τ=5s]  → Ideal flow curve
       [Defect DSV] → [Transfer Fcn τ=30s] → Defect flow curve (sluggish = congestion)
       [Pothole impact] → [Greenshields speed model] → Vehicle speed
       [LOS numeric] → [Lookup Table] → LOS signal
        ↓
     MATLAB writes dt_output.json
        ↓
  FastAPI serves /api/digital-twin/latest
        ↓
  Dashboard JS polls → renders twin panel
```

### Why Transfer Functions?
- The first-order lag (τ) models **traffic flow inertia** — ideal roads respond quickly to capacity,
  defect roads respond slowly (congestion takes time to build and dissipate).
- This is a standard traffic engineering simplification (analogous to the LWR model).

### Calibration model
- IRC:106-1990 design load factor = **0.7** (roads designed for 70% of DSV)
- Greenshields model: `v = v_free × (1 - V/C)`
- Pothole speed penalty: `speed_pct_lost = cap_loss_pct × 0.6` (conservative proxy)

---

## Deployment on Render

MATLAB is NOT available on Render's free tier.

Options:
1. **Run MATLAB locally** — run `run_digital_twin.m` manually, copy `dt_output.json` to the server
2. **Use MATLAB Online + REST API** — MATLAB Online has a REST API (R2024a+)
3. **Pre-compute** — for a demo, pre-generate dt_output.json for a few test cases

For a final-year project demo, option 1 or 3 is perfectly fine.
State clearly in your viva: "MATLAB runs locally, Python reads the output".
