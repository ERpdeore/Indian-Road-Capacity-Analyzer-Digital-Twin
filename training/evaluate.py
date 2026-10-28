"""
evaluate.py — measure the trained model per class, find which classes it
confuses, and choose a confidence threshold per class for the dashboard.

What it does
  1. Runs the model on the TEST split (your own photos) if data.yaml has one,
     else on VALID, and prints per class: boxes, precision, recall, mAP50,
     mAP50-95. These are the numbers for your report.
  2. Counts confusions on the same split: how many real barricades the
     model called illegal_parking, and so on (IoU >= 0.5, at the chosen
     thresholds).
  3. Chooses each class's confidence threshold on VALID (never on test) as
     the one with the highest F1, and writes class_thresholds.json.
     Copy that file next to best.pt in road_analyzer/models/; the
     dashboard reads it automatically.

Usage
  python evaluate.py --model runs/detect/road_obstructions/weights/best.pt --data merged/data.yaml
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
THRESHOLDS = [round(float(t), 2) for t in np.arange(0.10, 0.91, 0.05)]
IOU_MATCH = 0.5


def load_names(d):
    n = d["names"]
    return [n[k] for k in sorted(n, key=int)] if isinstance(n, dict) else list(n)


def split_dir(d, root, split):
    key = {"valid": "val"}.get(split, split)
    rel = d.get(key)
    return (root / rel) if rel else None


def gt_boxes(label_path: Path, W, H):
    out = []
    if label_path.exists():
        for line in label_path.read_text().splitlines():
            v = line.split()
            if len(v) == 5:
                c, x, y, w, h = int(v[0]), *map(float, v[1:])
                out.append((c, np.array([(x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H])))
    return out


def iou(a, b):
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def predict_split(model, img_dir: Path, imgsz):
    """[(gt list, pred list)] per image; preds at conf 0.01."""
    out = []
    imgs = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT)
    lab_dir = img_dir.parent / "labels"
    for i in range(0, len(imgs), 16):
        batch = imgs[i:i + 16]
        for p, r in zip(batch, model.predict([str(x) for x in batch], conf=0.01, imgsz=imgsz,
                                             verbose=False)):
            H, W = r.orig_shape
            preds = [(int(c), float(s), b) for c, s, b in
                     zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.cpu().numpy())]
            out.append((gt_boxes(lab_dir / (p.stem + ".txt"), W, H), preds))
    return out


def match_class(data, c, thr):
    """TP, FP, FN for class c at confidence thr (greedy by confidence)."""
    tp = fp = fn = 0
    for gts, preds in data:
        g = [b for k, b in gts if k == c]
        ps = sorted([(s, b) for k, s, b in preds if k == c and s >= thr], key=lambda x: -x[0])
        used = set()
        for s, b in ps:
            best, bi = 0.0, -1
            for j, gb in enumerate(g):
                if j not in used:
                    v = iou(b, gb)
                    if v > best:
                        best, bi = v, j
            if best >= IOU_MATCH:
                used.add(bi)
                tp += 1
            else:
                fp += 1
        fn += len(g) - len(used)
    return tp, fp, fn


def tune_thresholds(data, names):
    """Per class, the confidence with the highest F1. If several thresholds
    tie, the middle one is taken (less sensitive to the exact validation set)."""
    out = {}
    rows = []
    for c, n in enumerate(names):
        scores = []
        for t in THRESHOLDS:
            tp, fp, fn = match_class(data, c, t)
            if tp + fn == 0:
                break
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn)
            scores.append((2 * p * r / (p + r) if p + r else 0.0, t, p, r))
        if not scores:
            continue                                  # class absent from valid
        best = max(f for f, *_ in scores)
        if best == 0:
            rows.append((n, float("nan"), 0.0, 0.0, 0.0))   # never found: keep the app default
            continue
        tied = [s for s in scores if s[0] >= best - 1e-9]
        f1, t, p, r = tied[len(tied) // 2]
        out[n] = t
        rows.append((n, t, p, r, f1))
    return out, rows


def confusions(data, names, thr):
    """Real box of class A covered (IoU >= 0.5) by a prediction of class B
    and by no prediction of class A."""
    conf = Counter()
    for gts, preds in data:
        for c, gb in gts:
            ok = any(k == c and s >= thr.get(names[k], 0.25) and iou(b, gb) >= IOU_MATCH
                     for k, s, b in preds)
            if ok:
                continue
            others = [(s, k) for k, s, b in preds
                      if k != c and s >= thr.get(names[k], 0.25) and iou(b, gb) >= IOU_MATCH]
            if others:
                conf[(names[c], names[max(others)[1]])] += 1
            else:
                conf[(names[c], "missed")] += 1
    return conf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="merged/data.yaml")
    ap.add_argument("--imgsz", type=int, default=None, help="default: the size the model was trained at")
    ap.add_argument("--out", default="evaluation")
    a = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(a.model)
    imgsz = a.imgsz or int((getattr(model, "overrides", {}) or {}).get("imgsz") or 640)
    d = yaml.safe_load(Path(a.data).read_text())
    root = Path(d.get("path") or Path(a.data).parent)
    names = load_names(d)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    test_dir = split_dir(d, root, "test")
    has_test = bool(test_dir and test_dir.is_dir() and any(test_dir.iterdir()))
    report_split = "test" if has_test else "val"

    # 1. official metrics
    m = model.val(data=a.data, split=report_split, imgsz=imgsz, plots=True, verbose=False,
                  project=str(out.resolve()), name="val", exist_ok=True)
    box = m.box
    per = {int(c): i for i, c in enumerate(box.ap_class_index)}
    L = [f"MODEL EVALUATION on {report_split.upper()} split  (imgsz {imgsz})", "=" * 60,
         f"{'class':16s} {'P':>6s} {'R':>6s} {'mAP50':>7s} {'mAP50-95':>9s}"]
    rows = []
    for c, n in enumerate(names):
        if c in per:
            i = per[c]
            p, r, a50, a = float(box.p[i]), float(box.r[i]), float(box.ap50[i]), float(box.ap[i])
            L.append(f"{n:16s} {p:6.3f} {r:6.3f} {a50:7.3f} {a:9.3f}")
            rows.append([n, p, r, a50, a])
        else:
            L.append(f"{n:16s}   no boxes of this class in the {report_split} split")
    L.append(f"{'ALL':16s} {box.mp:6.3f} {box.mr:6.3f} {box.map50:7.3f} {box.map:9.3f}")
    with (out / "per_class_metrics.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["class", "precision", "recall", "mAP50", "mAP50-95"])
        w.writerows(rows)
    if report_split == "val":
        L.append("NOTE: no test split, so these numbers are on VALID, which also picked the best "
                 "epoch. Add your own photos as a test set for honest numbers.")

    # 2. thresholds on valid
    val_dir = split_dir(d, root, "valid")
    val_data = predict_split(model, val_dir, imgsz)
    thr, trows = tune_thresholds(val_data, names)
    L += ["", "Per-class confidence threshold (best F1 on VALID):",
          f"{'class':16s} {'thr':>5s} {'P':>6s} {'R':>6s} {'F1':>6s}"]
    for n, t, p, r, f1 in trows:
        if f1 == 0:
            L.append(f"{n:16s}   the model finds none of these at any threshold: needs more/better data")
        else:
            L.append(f"{n:16s} {t:5.2f} {p:6.3f} {r:6.3f} {f1:6.3f}")
    (out / "class_thresholds.json").write_text(json.dumps(thr, indent=2))

    # 3. confusions on the report split
    rep_data = predict_split(model, test_dir, imgsz) if has_test else val_data
    conf = confusions(rep_data, names, thr)
    L += ["", f"Where real boxes went ({report_split}, at the thresholds above):"]
    by_true = defaultdict(list)
    for (t, p), k in conf.items():
        by_true[t].append((k, p))
    if not by_true:
        L.append("  every real box was found with the right class")
    for t in names:
        if by_true[t]:
            L.append(f"  real {t}: " + ", ".join(f"{k} called {p}" if p != "missed" else f"{k} missed"
                                                 for k, p in sorted(by_true[t], reverse=True)))
    L += ["", f"Confusion matrix picture: {out.resolve()}/val/confusion_matrix.png",
          f"Thresholds for the dashboard: {out.resolve()}/class_thresholds.json",
          "Copy best.pt and class_thresholds.json into road_analyzer_deploy/road_analyzer/models/."]
    rep = "\n".join(L)
    (out / "evaluation_report.txt").write_text(rep, encoding="utf-8")
    print(rep)


if __name__ == "__main__":
    main()
