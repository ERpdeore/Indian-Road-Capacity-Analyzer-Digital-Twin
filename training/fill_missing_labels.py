"""
fill_missing_labels.py — add the boxes each source dataset never drew.

The problem (partial labels): the pothole dataset labels only potholes. If
one of its photos also shows a barricade or a parked car, that object has no
box, and training teaches the model "this is background". Merging five
single-purpose datasets makes this happen thousands of times; it is a main
reason for missed barricades and for barricade/parking mix-ups.

The fix: after a first training run, let that model propose boxes for the
classes a source does NOT label, keep only confident ones that do not
overlap an existing box, and write a NEW copy of the dataset. Then look at
the review sheets, delete wrong boxes, and retrain on the new copy.

  * classes a source already labels are never touched (its human boxes win)
  * the TEST split is never touched (it must stay human-labelled)

Usage
  python fill_missing_labels.py --model runs/detect/road_obstructions/weights/best.pt \
      --data merged/data.yaml --out merged_filled --conf 0.6
  python audit_dataset.py --data merged_filled/data.yaml --out audit_filled
"""
from __future__ import annotations

import argparse
import csv
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import yaml

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def read(p: Path):
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            v = line.split()
            if len(v) == 5:
                out.append((int(v[0]), *map(float, v[1:])))
    return out


def iou(a, b):
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-12)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="merged/data.yaml")
    ap.add_argument("--out", default="merged_filled")
    ap.add_argument("--conf", type=float, default=0.6, help="only add boxes at least this confident")
    ap.add_argument("--imgsz", type=int, default=None)
    a = ap.parse_args()

    from ultralytics import YOLO

    src_yaml = Path(a.data)
    d = yaml.safe_load(src_yaml.read_text())
    root = Path(d.get("path") or src_yaml.parent)
    names = d["names"]
    names = [names[k] for k in sorted(names, key=int)] if isinstance(names, dict) else list(names)
    man = root / "manifest.csv"
    if not man.exists():
        raise SystemExit("manifest.csv not found: run merge_datasets.py first.")
    with man.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    source_of = {Path(r["file"]).stem: r["source"] for r in rows}

    # which classes each source labels (from its human labels)
    labelled = defaultdict(set)
    for split in ("train", "valid"):
        for lp in (root / split / "labels").glob("*.txt"):
            for b in read(lp):
                labelled[source_of.get(lp.stem, "?")].add(b[0])

    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root, out)
    d2 = dict(d)
    d2["path"] = str(out.resolve())
    (out / "data.yaml").write_text(yaml.safe_dump(d2, sort_keys=False))

    model = YOLO(a.model)
    imgsz = a.imgsz or int((getattr(model, "overrides", {}) or {}).get("imgsz") or 640)
    if [model.names[i] for i in sorted(model.names)] != names:
        raise SystemExit(f"Model classes {model.names} differ from data.yaml {names}.")

    added = Counter()
    review = []
    for split in ("train", "valid"):                     # never test
        imgs = sorted(p for p in (out / split / "images").iterdir() if p.suffix.lower() in IMG_EXT)
        for i in range(0, len(imgs), 16):
            batch = imgs[i:i + 16]
            for p, r in zip(batch, model.predict([str(x) for x in batch], conf=a.conf, imgsz=imgsz,
                                                 verbose=False)):
                src = source_of.get(p.stem, "?")
                lp = out / split / "labels" / (p.stem + ".txt")
                boxes = read(lp)
                new = []
                for c, s, xywhn in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(),
                                       r.boxes.xywhn.cpu().numpy().tolist()):
                    c = int(c)
                    if c in labelled[src]:
                        continue                         # this source's people labelled it already
                    if any(iou(xywhn, b[1:]) > 0.3 for b in boxes + new):
                        continue
                    new.append((c, *xywhn))
                    added[(src, names[c])] += 1
                    review.append([split, p.name, src, names[c], round(s, 3)])
                if new:
                    with lp.open("a") as f:
                        for c, x, y, w, h in new:
                            f.write(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n")

    with (out / "added_boxes_review.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["split", "file", "source", "class", "confidence"])
        w.writerows(review)
    print("Boxes added (source -> class: count):")
    for (src, c), k in sorted(added.items()):
        print(f"  {src} -> {c}: {k}")
    print(f"\nNew dataset: {out.resolve()}/data.yaml")
    print(f"Every added box is listed in {out}/added_boxes_review.csv.")
    print("Review them (audit_dataset.py sheets, or upload to Roboflow/CVAT), fix wrong ones, then retrain.")


if __name__ == "__main__":
    main()
