# Deploying to Render

## Contents
```
road_analyzer/     FastAPI app + static dashboard
matlab_twin/       MATLAB/RoadRunner scripts (packed into each job's bundle.zip)
Dockerfile         container build
requirements.txt   Python dependencies (CPU-only PyTorch)
render.yaml        Render service definition
```

## Steps
1. Push the repository to GitHub.
2. On render.com: **New + → Web Service**, select the repository. Render reads
   `render.yaml` (Docker runtime, free plan, health check `/api/health`).
3. First build takes 5–10 min (PyTorch + ultralytics).

## Model weights
`road_analyzer/models/best.pt` (YOLOv8s, 7 classes: barricade, pothole,
illegal_parking, street_vendor, cart, garbage, vehicle) is committed. Without
it the site loads and `/api/analyze/*` returns 503. Use Git LFS if the file
grows past GitHub's limits, or mount a Render disk at `/app/road_analyzer/models`.

## Free-tier constraints
- The service sleeps after 15 min idle; the first request takes 30–60 s.
- CPU only: about 0.5–2 s per image; long videos take minutes.
- Batch/video job status is held in memory (`JOBS` in `app.py`) and is lost
  on restart. Use Redis or a database before relying on it beyond a demo.

## Environment variables
| Variable | Purpose |
|---|---|
| `ROAD_MODEL_PATH` | path to `best.pt` (set in `render.yaml`) |
| `ALLOWED_ORIGINS` | comma-separated origins allowed to call the API cross-site; unset = same-origin only |

## PyTorch CPU wheel
`requirements.txt` installs torch from `https://download.pytorch.org/whl/cpu`.
If that index fails on the build server, replace the two index lines with
`--extra-index-url https://download.pytorch.org/whl/cpu` and pin `torch==2.4.1+cpu`.
