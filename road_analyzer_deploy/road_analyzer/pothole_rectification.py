"""
Pothole Depth Estimation (MiDaS)

IMPORTANT: MiDaS provides RELATIVE depth only (dimensionless values).
It does NOT produce metric depth (cm/mm) without camera calibration.
This module is disabled by default (enable_depth=False) because:
- Metric calibration is not implemented
- Relative depth cannot be used for severity classification reliably

The system falls back to bounding‑box area as a proxy for severity,
which is a known limitation.
"""

import cv2
import numpy as np
import torch
import logging

logger = logging.getLogger(__name__)

class PotholeRectifier:
    def __init__(self, model_type="MiDaS_small"):
        self.model_type = model_type
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.midas = None
        self.transform = None
        try:
            self.midas = torch.hub.load("intel-isl/MiDaS", model_type)
            self.midas.to(self.device)
            self.midas.eval()
            self.transform = torch.hub.load("intel-isl/MiDaS", "transforms").default_transform
            logger.info("MiDaS loaded on %s", self.device)
        except Exception as e:
            logger.error("Failed to load MiDaS: %s", e)
            self.midas = None

    def estimate_depth(self, bbox, image):
        """
        Estimate relative depth for the region inside bbox.
        Returns a dimensionless float (relative depth value) or None if not available.
        """
        if self.midas is None:
            return None
        x1, y1, x2, y2 = bbox
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        # Prepare input
        input_batch = self.transform(crop).to(self.device)
        with torch.no_grad():
            prediction = self.midas(input_batch)
            prediction = torch.nn.functional.interpolate(
                prediction.unsqueeze(1),
                size=crop.shape[:2],
                mode="bicubic",
                align_corners=False,
            ).squeeze()
        depth_map = prediction.cpu().numpy()
        avg_depth = float(np.mean(depth_map))
        # This is a relative value – no units
        return avg_depth
