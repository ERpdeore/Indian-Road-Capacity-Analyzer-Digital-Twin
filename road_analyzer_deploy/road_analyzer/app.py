import os
import sys
import uuid
import shutil
import logging
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import cv2
from pathlib import Path

# ----- Ensure current directory is in Python path -----
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ----- Imports (absolute) -----
from core import RoadAnalyzer
from department_extensions import generate_recommendations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Indian Road Capacity Analyzer — Digital Model",
    description="Supports both Image and Video analysis.",
    version="2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================================
# ULTIMATE STATIC FOLDER FINDER (Searches up and down the directory tree)
# ======================================================================
def find_static_folder():
    """Searches for a folder named 'static' that contains 'index.html'."""
    # Start from the current file's directory
    start_dir = Path(__file__).parent.absolute()
    
    # Walk up the directory tree (up to 5 levels up)
    for _ in range(5):
        candidate = start_dir / "static"
        if candidate.exists() and (candidate / "index.html").exists():
            logger.info(f"✅ Found static folder at: {candidate}")
            return candidate
        # Also check if static is inside a subdirectory
        for sub in start_dir.iterdir():
            if sub.is_dir():
                candidate_sub = sub / "static"
                if candidate_sub.exists() and (candidate_sub / "index.html").exists():
                    logger.info(f"✅ Found static folder at: {candidate_sub}")
                    return candidate_sub
        start_dir = start_dir.parent  # Go one level up

    # If not found, do a full walk (slow but exhaustive)
    for root, dirs, files in os.walk("."):
        if "static" in dirs:
            candidate = Path(root) / "static"
            if (candidate / "index.html").exists():
                logger.info(f"✅ Found static folder via walk: {candidate}")
                return candidate

    logger.warning("❌ Static folder NOT found! Frontend will not load.")
    return None

STATIC_PATH = find_static_folder()

# Mount static folder if found
if STATIC_PATH:
    app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")
    logger.info(f"✅ Static folder mounted from: {STATIC_PATH}")
else:
    # Create a dummy static folder with a fallback HTML page
    fallback_dir = Path("/tmp/static_fallback")
    fallback_dir.mkdir(exist_ok=True, parents=True)
    index_fallback = fallback_dir / "index.html"
    with open(index_fallback, "w") as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head><title>Fallback</title></head>
        <body>
            <h1>⚠️ Frontend files not found</h1>
            <p>Please ensure your GitHub repository contains a <code>static</code> folder with <code>index.html</code>.</p>
            <p>Current directory: <pre>{}</pre></p>
        </body>
        </html>
        """.format(os.getcwd()))
    STATIC_PATH = fallback_dir
    app.mount("/static", StaticFiles(directory=str(fallback_dir)), name="static")
    logger.warning("⚠️ Using fallback static folder.")

# ======================================================================
# ROOT ENDPOINT (Always serves index.html)
# ======================================================================
@app.get("/")
async def root():
    index_path = STATIC_PATH / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    # If still not found, serve a simple HTML response
    return HTMLResponse(content="""
    <html>
        <head><title>Road Analyzer</title></head>
        <body>
            <h1>🛣️ Road Capacity Analyzer</h1>
            <p>Static files not found. Please check your repository.</p>
        </body>
    </html>
    """)

# ======================================================================
# Initialize the analyzer (MiDaS OFF)
# ======================================================================
analyzer = RoadAnalyzer(model_path="yolov8n.pt", enable_depth=False)
jobs = {}

# ---------- Image Analysis ----------
@app.post("/analyse")
async def analyse(
    file: UploadFile = File(...),
    total_width_m: float = Form(...),
    carriageway: str = Form("4L-D"),
    fringe: str = Form("medium")
):
    job_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{job_id}.jpg"

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        img = cv2.imread(str(temp_path))
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image")

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        raw_result = analyzer.analyse_image(
            image=img_rgb,
            total_width_m=total_width_m,
            carriageway=carriageway,
            fringe=fringe
        )

        sanitised_result = {
            "base_dsv_pcu_hr": int(round(raw_result["base_dsv_pcu_hr"])),
            "reduced_dsv_pcu_hr": int(round(raw_result["reduced_dsv_pcu_hr"])),
            "capacity_loss_percent": round(raw_result["capacity_loss_percent"], 2),
            "blocked_width_m": round(raw_result["blocked_width_m"], 3),
            "usable_width_m": round(raw_result["usable_width_m"], 3),
            "width_factor": round(raw_result["width_factor"], 4),
            "pothole_severities": raw_result["pothole_severities"],
            "simulation": raw_result["simulation"],
        }

        recommendations = generate_recommendations(
            raw_result["detections"],
            raw_result["reduced_dsv_pcu_hr"],
            raw_result["base_dsv_pcu_hr"]
        )

        response = {
            "job_id": job_id,
            "status": "completed",
            "result": sanitised_result,
            "recommendations": recommendations,
            "disclaimer": "Estimate based on computer vision. Requires field verification."
        }

        jobs[job_id] = response
        return JSONResponse(content=response)

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path.exists():
            os.remove(temp_path)

# ---------- Video Analysis ----------
def process_video_background(job_id: str, video_path: Path, total_width_m: float, carriageway: str, fringe: str):
    try:
        logger.info(f"Starting video processing for job {job_id}")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            jobs[job_id] = {"status": "failed", "error": "Cannot open video file"}
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 0

        sample_interval = max(1, int(fps))
        frame_indices = list(range(0, total_frames, sample_interval))
        if len(frame_indices) > 30:
            frame_indices = frame_indices[:30]

        results = []
        for i, idx in enumerate(frame_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            raw_result = analyzer.analyse_image(
                image=frame_rgb,
                total_width_m=total_width_m,
                carriageway=carriageway,
                fringe=fringe
            )
            results.append({
                "timestamp_sec": round(idx / fps, 1) if fps > 0 else i,
                "capacity_loss_percent": round(raw_result["capacity_loss_percent"], 2),
                "reduced_dsv_pcu_hr": int(round(raw_result["reduced_dsv_pcu_hr"])),
                "blocked_width_m": round(raw_result["blocked_width_m"], 3),
                "pothole_severities": raw_result["pothole_severities"],
            })
            if i % 5 == 0:
                logger.info(f"Job {job_id}: Processed frame {i+1}/{len(frame_indices)}")

        cap.release()

        if not results:
            jobs[job_id] = {"status": "failed", "error": "No frames could be processed"}
            return

        capacity_losses = [r["capacity_loss_percent"] for r in results]
        avg_loss = sum(capacity_losses) / len(capacity_losses)
        max_loss = max(capacity_losses)
        min_loss = min(capacity_losses)
        worst_frame = max(results, key=lambda x: x["capacity_loss_percent"])

        dynamic_response = {
            "status": "completed",
            "job_id": job_id,
            "analysis_type": "video_dynamic",
            "total_duration_sec": round(duration_sec, 1),
            "frames_analysed": len(results),
            "summary": {
                "average_capacity_loss_percent": round(avg_loss, 2),
                "max_capacity_loss_percent": round(max_loss, 2),
                "min_capacity_loss_percent": round(min_loss, 2),
                "peak_reduced_dsv_pcu_hr": worst_frame["reduced_dsv_pcu_hr"],
                "peak_blocked_width_m": worst_frame["blocked_width_m"],
            },
            "timeline": results,
            "recommendations": [
                {
                    "severity": "High" if max_loss > 15 else "Medium" if max_loss > 5 else "Low",
                    "action": "Recommended for engineering review: Dynamic video analysis shows fluctuating capacity loss. Consider time-of-day based maintenance scheduling."
                }
            ],
            "disclaimer": "Video analysis is dynamic. Results represent the worst observed condition."
        }

        jobs[job_id] = dynamic_response
        logger.info(f"Job {job_id}: Video processing complete.")

    except Exception as e:
        logger.error(f"Video processing failed for {job_id}: {str(e)}", exc_info=True)
        jobs[job_id] = {"status": "failed", "error": str(e)}
    finally:
        if video_path.exists():
            os.remove(video_path)

@app.post("/analyse_video")
async def analyse_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    total_width_m: float = Form(...),
    carriageway: str = Form("4L-D"),
    fringe: str = Form("medium")
):
    job_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{job_id}.mp4"

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        cap = cv2.VideoCapture(str(temp_path))
        if not cap.isOpened():
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="Invalid video file")
        cap.release()

        jobs[job_id] = {"status": "processing", "message": "Video is being analysed in the background."}

        background_tasks.add_task(
            process_video_background,
            job_id,
            temp_path,
            total_width_m,
            carriageway,
            fringe
        )

        return {
            "job_id": job_id,
            "status": "processing",
            "message": "Video accepted. Poll /job/{job_id} for results.",
            "estimated_time_sec": 10
        }

    except Exception as e:
        logger.error(f"Error submitting video: {str(e)}")
        if temp_path.exists():
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/job/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job.get("status") == "processing":
        return {"job_id": job_id, "status": "processing"}
    return job

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
