# Deploying Road Efficiency Analyzer to Render

## What's in this folder
```
road_analyzer/        the app itself (already built and tested)
Dockerfile             how to build the container
requirements.txt       Python dependencies (CPU-only torch — see note below)
render.yaml             one-click Render config
.dockerignore
```

## 1. Get this into a GitHub repo
Render deploys from GitHub (or GitLab/Bitbucket), not from a direct file
upload. If you don't already have a repo:

```bash
git init
git add .
git commit -m "Road efficiency analyzer"
```
Create a new repo on GitHub, then:
```bash
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

## 2. Deploy on Render
1. Go to https://render.com and sign up / log in (free, no card needed for
   the free web service tier).
2. Click **New +** → **Web Service**.
3. Connect your GitHub account and pick this repo.
4. Render will detect `render.yaml` automatically and pre-fill everything
   (Docker runtime, free plan, health check path). If it doesn't, set:
   - **Runtime**: Docker
   - **Dockerfile path**: `./Dockerfile`
   - **Plan**: Free
5. Click **Create Web Service**. First build takes ~5-10 minutes (it's
   downloading PyTorch + ultralytics).
6. When it's done you'll get a URL like
   `https://road-efficiency-analyzer.onrender.com` — that's your live site.

## 3. Add your trained model (best.pt)
The app **will deploy and load successfully without a model** — every page
loads, but `/api/analyze/*` calls return a clear "model not found" message
instead of crashing. Once you've trained in the Colab notebook:

**Option A — bake it into the repo (simplest):**
```bash
cp /path/to/best.pt road_analyzer/models/best.pt
git add road_analyzer/models/best.pt
git commit -m "Add trained model"
git push
```
Render auto-redeploys on every push to `main`. Note: `best.pt` for YOLOv8s
is typically 20-50MB — fine for a normal git push, but if GitHub ever
complains about large files, use Git LFS instead of committing it raw.

**Option B — Render persistent disk (if you'll swap models often):**
Add a free-tier disk under your service's **Disks** tab mounted at
`/app/road_analyzer/models`, then upload `best.pt` there via Render's shell
(**Shell** tab → `cat > best.pt < /dev/stdin` style upload, or `scp`-style
tools they provide). More flexible, slightly more setup.

## 4. Important limitations of the free tier (be upfront about these)
- **Free services spin down after 15 min of no traffic** and take ~30-60s
  to wake back up on the next request. Fine for a viva demo, mention it if
  someone clicks the link cold.
- **No GPU** — this is why `requirements.txt` pins the CPU build of
  PyTorch. Inference on CPU is slower per image (expect 0.5-2s/image
  depending on plan), batch/video jobs will take noticeably longer than
  they did on Colab's free GPU. For a handful of demo images this is
  unnoticeable; a 5-minute video sampled every 1s could take several
  minutes to process.
- **In-memory job tracking**: batch/video jobs are tracked in a Python
  dict inside `app.py` (see `JOBS = {}`). This is fine for a single demo
  session, but if the free instance restarts (it does, after idling) any
  jobs that were "running" are lost. Don't rely on this for anything
  long-running in production — swap to a database or Redis if this ever
  needs to be a real deployed service rather than a project demo.

## 5. Verifying the requirements.txt CPU-torch pin
I could not actually test-install `requirements.txt` end-to-end in my own
sandbox — `download.pytorch.org` was blocked by my environment's network
rules, so the CPU-only torch pin is written using PyTorch's documented
index syntax but unverified by me directly. Render's build servers won't
have that restriction, but if the very first deploy fails on the torch
install step, check Render's build logs for the error and:
- Try dropping the `--index-url` lines and just using
  `torch==2.4.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu`
  instead (alternate syntax PyTorch also documents), or
- Open an issue, I'm happy to debug the exact log output with you.
