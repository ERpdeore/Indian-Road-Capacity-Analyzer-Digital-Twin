# ================================================================
# Road Efficiency Analyzer — deployment image
# Builds a container that runs the FastAPI app + serves the
# static dashboard. Works on Render, Railway, Fly.io, or any
# Docker host.
# ================================================================
FROM python:3.11-slim

# OpenCV needs these system libs even with opencv-python-headless
RUN apt-get update && apt-get install -y --no-install-recommends \
libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY road_analyzer/ ./road_analyzer/

# Render (and most hosts) inject $PORT at runtime; default to 8000 for
# local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Where to look for the trained model. If best.pt isn't present at this
# path, the app still starts — every /api/analyze/* call will return a
# clear 503 telling you to add the model, instead of crashing on boot.
ENV ROAD_MODEL_PATH=/app/road_analyzer/models/best.pt

CMD ["sh", "-c", "uvicorn road_analyzer.app:app --host 0.0.0.0 --port ${PORT}"]
