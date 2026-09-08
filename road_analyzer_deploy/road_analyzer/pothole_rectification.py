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

    def estimate_depth_ratio(self, bbox, image):
        if self.midas is None:
            return None

        h, w = image.shape[:2]
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None

        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        margin = int(min(30, (x2 - x1) * 0.2, (y2 - y1) * 0.2))
        margin = max(margin, 5)

        x1_surr = max(0, x1 - margin)
        y1_surr = max(0, y1 - margin)
        x2_surr = min(w, x2 + margin)
        y2_surr = min(h, y2 + margin)

        surround_mask = np.ones((y2_surr - y1_surr, x2_surr - x1_surr), dtype=bool)
        px1, py1 = x1 - x1_surr, y1 - y1_surr
        px2, py2 = x2 - x1_surr, y2 - y1_surr
        surround_mask[py1:py2, px1:px2] = False

        surround_crop = image[y1_surr:y2_surr, x1_surr:x2_surr]
        if surround_crop.size == 0:
            return None

        try:
            input_batch = self.transform(crop).to(self.device)
            with torch.no_grad():
                pred = self.midas(input_batch)
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1),
                    size=crop.shape[:2],
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()
            depth_pothole = pred.cpu().numpy()
        except Exception as e:
            logger.error("MiDaS failed on pothole crop: %s", e)
            return None

        try:
            input_batch_surr = self.transform(surround_crop).to(self.device)
            with torch.no_grad():
                pred_surr = self.midas(input_batch_surr)
                pred_surr = torch.nn.functional.interpolate(
                    pred_surr.unsqueeze(1),
                    size=surround_crop.shape[:2],
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()
            depth_surround = pred_surr.cpu().numpy()
        except Exception as e:
            logger.error("MiDaS failed on surround crop: %s", e)
            return None

        mean_pothole = float(np.mean(depth_pothole))
        masked_surround = depth_surround[surround_mask]
        if len(masked_surround) == 0:
            return None
        mean_road = float(np.mean(masked_surround))
        if mean_road <= 0:
            return None

        ratio = mean_pothole / mean_road
        ratio = max(0.5, min(2.5, ratio))
        logger.info("Pothole Depth Ratio: %.3f", ratio)
        return ratio
