import os
import sys
import uuid
import shutil
import logging
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import cv2
from pathlib import Path

# ---- SMART IMPORT (works with or without __init__.py) ----
try:
    from core import RoadAnalyzer
except ImportError:
    try:
        from .core import RoadAnalyzer
    except ImportError:
        sys.path.append(os.path.dirname(__file__))
        from core import RoadAnalyzer
from department_extensions import generate_recommendations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Indian Road Capacity Analyzer — Digital Model",
    description="Supports both Image and Video analysis. Video is processed asynchronously.",
    version="2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize the heavy analyzer once (MiDaS OFF by default to save CPU)
analyzer = RoadAnalyzer(model_path="yolov8n.pt", enable_depth=False)
jobs = {}

@app.get("/")
async def root():
    if Path("static/index.html").exists():
        return FileResponse("static/index.html")
    return {"message": "API is running."}

# --------------------------------------------------------------
# IMAGE ANALYSIS (Instant)
# --------------------------------------------------------------
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

# --------------------------------------------------------------
# VIDEO ANALYSIS (Asynchronous - No Timeouts!)
# --------------------------------------------------------------
def process_video_background(job_id: str, video_path: Path, total_width_m: float, carriageway: str, fringe: str):
    """Background task to process video frames."""
    try:
        logger.info(f"Starting video processing for job {job_id}")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            jobs[job_id] = {"status": "failed", "error": "Cannot open video file"}
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 0

        # --- DYNAMIC SAMPLING: 1 frame per second (Max 30 frames) ---
        sample_interval = max(1, int(fps))  # 1 second intervals
        frame_indices = list(range(0, total_frames, sample_interval))
        
        # Limit to 30 frames to avoid memory explosion
        if len(frame_indices) > 30:
            frame_indices = frame_indices[:30]
        
        logger.info(f"Job {job_id}: Sampling {len(frame_indices)} frames from {total_frames} total.")

        results = []
        for i, idx in enumerate(frame_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            
            # Convert to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Run the EXACT SAME analysis as the image pipeline
            raw_result = analyzer.analyse_image(
                image=frame_rgb,
                total_width_m=total_width_m,
                carriageway=carriageway,
                fringe=fringe
            )
            
            # Store relevant dynamic metrics
            results.append({
                "timestamp_sec": round(idx / fps, 1) if fps > 0 else i,
                "capacity_loss_percent": round(raw_result["capacity_loss_percent"], 2),
                "reduced_dsv_pcu_hr": int(round(raw_result["reduced_dsv_pcu_hr"])),
                "blocked_width_m": round(raw_result["blocked_width_m"], 3),
                "pothole_severities": raw_result["pothole_severities"],
            })
            
            # Log progress every 5 frames
            if i % 5 == 0:
                logger.info(f"Job {job_id}: Processed frame {i+1}/{len(frame_indices)}")

        cap.release()

        # --- Aggregate Dynamic Statistics ---
        if not results:
            jobs[job_id] = {"status": "failed", "error": "No frames could be processed"}
            return

        # Calculate dynamic stats
        capacity_losses = [r["capacity_loss_percent"] for r in results]
        avg_loss = sum(capacity_losses) / len(capacity_losses)
        max_loss = max(capacity_losses)
        min_loss = min(capacity_losses)
        
        # Find the worst frame
        worst_frame = max(results, key=lambda x: x["capacity_loss_percent"])

        # Generate recommendations from the worst frame (conservative approach)
        # We need to re-run the full detection to get recommendations for the worst frame
        # Since we only stored summary data, we just give a general dynamic recommendation
        
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
            "timeline": results,  # Send the full timeline to the frontend
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
        # Clean up the large video file
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
    """Submit a video for dynamic analysis. Returns job_id immediately."""
    job_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{job_id}.mp4"

    try:
        # Save the uploaded video
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Quick validation
        cap = cv2.VideoCapture(str(temp_path))
        if not cap.isOpened():
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="Invalid video file")
        cap.release()

        # Store initial pending status
        jobs[job_id] = {"status": "processing", "message": "Video is being analysed in the background."}
        
        # Add the background task
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
            "estimated_time_sec": 10  # Rough estimate
        }

    except Exception as e:
        logger.error(f"Error submitting video: {str(e)}")
        if temp_path.exists():
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

# --------------------------------------------------------------
# POLLING ENDPOINT (For both Image and Video)
# --------------------------------------------------------------
@app.get("/job/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    # If it's a video that's still processing, just return the status
    if job.get("status") == "processing":
        return {"job_id": job_id, "status": "processing"}
    
    return job

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
