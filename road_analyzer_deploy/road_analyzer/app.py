import os
import uuid
import shutil
import logging
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import cv2
import numpy as np
from pathlib import Path
from core import RoadAnalyzer
from department_extensions import generate_recommendations

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Initialize FastAPI
app = FastAPI(
    title="Indian Road Capacity Analyzer — Digital Model",
    description=(
        "Prototype Digital Model (not a full Digital Twin). "
        "Uses YOLOv8 for object detection, estimates obstruction widths, "
        "and computes reduced Design Service Volume per IRC:106-1990. "
        "Pothole severity is estimated via bounding‑box area (proxy) – "
        "this is a known limitation. All results are estimates requiring field verification."
    ),
    version="2.0",
)

# CORS – allow all for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend (if the folder exists)
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Global analyzer instance – loads YOLO once (singleton)
analyzer = RoadAnalyzer(model_path="yolov8n.pt", enable_depth=False)

# In‑memory job store (lost on restart – acceptable for prototype)
jobs = {}

@app.get("/")
async def root():
    """Serve the frontend index.html if present, else a JSON message."""
    if Path("static/index.html").exists():
        return FileResponse("static/index.html")
    return {"message": "Indian Road Capacity Analyzer API is running. Use /analyse endpoint."}

@app.post("/analyse")
async def analyse(
    file: UploadFile = File(...),
    total_width_m: float = Form(...),
    carriageway: str = Form("4L-D"),
    fringe: str = Form("medium")
):
    """
    Analyse a road image:
    - Detects obstructions (YOLO)
    - Computes blocked width, usable width, and reduced DSV
    - Runs Greenshields simulation (Digital Model)
    - Generates recommendations
    """
    job_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{job_id}.jpg"

    try:
        # 1. Save uploaded file
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Read image with OpenCV
        img = cv2.imread(str(temp_path))
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file")

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 3. Run core analysis
        raw_result = analyzer.analyse_image(
            image=img_rgb,
            total_width_m=total_width_m,
            carriageway=carriageway,
            fringe=fringe
        )

        # 4. **CRITICAL: Sanitise numbers for engineering presentation**
        sanitised_result = {
            "base_dsv_pcu_hr": int(round(raw_result["base_dsv_pcu_hr"])),
            "reduced_dsv_pcu_hr": int(round(raw_result["reduced_dsv_pcu_hr"])),
            "capacity_loss_percent": round(raw_result["capacity_loss_percent"], 2),
            "blocked_width_m": round(raw_result["blocked_width_m"], 3),
            "usable_width_m": round(raw_result["usable_width_m"], 3),
            "width_factor": round(raw_result["width_factor"], 4),
            "pothole_severities": raw_result["pothole_severities"],
            "simulation": {
                "steady_state": {
                    "speed_kmh": round(raw_result["simulation"]["steady_state"]["speed_kmh"], 2),
                    "density_pcu_km": round(raw_result["simulation"]["steady_state"]["density_pcu_km"], 2),
                    "flow_pcu_hr": int(round(raw_result["simulation"]["steady_state"]["flow_pcu_hr"]))
                }
            }
        }

        # 5. Generate recommendations
        recommendations = generate_recommendations(
            raw_result["detections"],
            raw_result["reduced_dsv_pcu_hr"],
            raw_result["base_dsv_pcu_hr"]
        )

        # 6. Prepare final response
        response = {
            "job_id": job_id,
            "status": "completed",
            "result": sanitised_result,
            "recommendations": recommendations,
            "disclaimer": (
                "This is an estimate based on computer vision and modelling assumptions. "
                "It is not a substitute for engineering judgment or field survey."
            )
        }

        # Store in memory (optional)
        jobs[job_id] = response

        # 7. Clean up temp file
        return JSONResponse(content=response)

    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Always delete the temporary file
        if temp_path.exists():
            os.remove(temp_path)

@app.get("/job/{job_id}")
async def get_job(job_id: str):
    """Retrieve a previously analysed job (stored in memory)."""
    if job_id in jobs:
        return jobs[job_id]
    raise HTTPException(status_code=404, detail="Job not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
