"""
train.py — train the road-obstruction detector on the merged dataset.

Settings chosen for this problem:
  imgsz 1024      small and shallow potholes vanish at 640
  yolo11s         small enough for Colab's free GPU and the Render CPU server
  patience 30     stop when validation mAP has not improved for 30 epochs
  degrees 0       roads are photographed level; rotation adds nothing
  fliplr 0.5      left/right mirror is realistic (kerb on either side)
  flipud 0        an upside-down road is not

Run on a GPU (Google Colab: Runtime -> Change runtime type -> T4 GPU):
  pip install ultralytics==8.3.0          # same version as the dashboard server
  python train.py --data merged/data.yaml

The result is runs/detect/<name>/weights/best.pt. Next:
  python evaluate.py --model runs/detect/<name>/weights/best.pt --data merged/data.yaml
"""
from __future__ import annotations

import argparse


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="merged/data.yaml")
    ap.add_argument("--model", default="yolo11s.pt",
                    help="start weights: yolo11s.pt (default), yolo11m.pt (more accurate, slower), "
                         "or your old best.pt to continue from it")
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch", type=float, default=-1, help="-1 = as large as the GPU allows")
    ap.add_argument("--patience", type=int, default=30)
    ap.add_argument("--name", default="road_obstructions")
    ap.add_argument("--device", default=None, help="0 for the first GPU, cpu for CPU")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(a.model)
    batch = int(a.batch) if a.batch >= 1 or a.batch == -1 else a.batch
    model.train(
        data=a.data, imgsz=a.imgsz, epochs=a.epochs, batch=batch, patience=a.patience,
        name=a.name, device=a.device, workers=a.workers, seed=0, deterministic=True,
        cos_lr=True, close_mosaic=15,
        degrees=0.0, fliplr=0.5, flipud=0.0, mosaic=1.0, mixup=0.0,
        hsv_h=0.015, hsv_s=0.6, hsv_v=0.4,           # day/evening light, dust, shade
        scale=0.5, translate=0.1,
        plots=True,
    )
    best = getattr(model.trainer, "best", None)
    print(f"\nBest weights: {best}")
    print(f"Next: python evaluate.py --model {best} --data {a.data} --imgsz {a.imgsz}")


if __name__ == "__main__":
    main()
