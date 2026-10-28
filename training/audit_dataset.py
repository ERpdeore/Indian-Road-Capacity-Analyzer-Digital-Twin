"""
audit_dataset.py — look at the merged dataset before training on it.

Prints and saves (audit/report.txt):
  * boxes per class per split and per source dataset
  * which classes each source labels at all (partial labels)
  * box sizes: share of SMALL boxes (< 32 px on a 640 px image) per class —
    small, shallow potholes need imgsz 1024+
  * images with no boxes (background) per source

Saves picture sheets audit/sheet_<class>_<source>.jpg: up to 24 random
photos with the boxes drawn and named. Look at every sheet. Wrong boxes
(a parked car called barricade, a patch called pothole) show up in minutes.

Usage:  python audit_dataset.py --data merged/data.yaml --out audit
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

COLORS = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
          (70, 240, 240), (240, 50, 230), (210, 245, 60), (128, 128, 0), (0, 128, 128)]
SMALL_PX = 32


def read_labels(p: Path):
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            v = line.split()
            if len(v) == 5:
                out.append((int(v[0]), *map(float, v[1:])))
    return out


def draw(img_path: Path, boxes, names, tile=320):
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    lw = max(2, W // 200)
    fs = max(12, W // 30)
    try:
        font = ImageFont.load_default(size=fs)
    except TypeError:                      # Pillow < 10.1
        font = ImageFont.load_default()
    for c, x, y, w, h in boxes:
        col = COLORS[c % len(COLORS)]
        x1, y1, x2, y2 = (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H
        d.rectangle([x1, y1, x2, y2], outline=col, width=lw)
        tw = d.textlength(names[c], font=font)
        d.rectangle([x1, max(0, y1 - fs - 4), x1 + tw + 6, y1], fill=col)
        d.text((x1 + 3, max(0, y1 - fs - 3)), names[c], fill=(255, 255, 255), font=font)
    im.thumbnail((tile, tile))
    canvas = Image.new("RGB", (tile, tile), (20, 20, 20))
    canvas.paste(im, ((tile - im.width) // 2, (tile - im.height) // 2))
    ImageDraw.Draw(canvas).text((4, tile - 14), img_path.name[:40], fill=(255, 255, 0))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="merged/data.yaml")
    ap.add_argument("--out", default="audit")
    ap.add_argument("--per-sheet", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    data_yaml = Path(a.data)
    d = yaml.safe_load(data_yaml.read_text())
    root = Path(d.get("path") or data_yaml.parent)
    names = d["names"]
    names = [names[k] for k in sorted(names, key=int)] if isinstance(names, dict) else list(names)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    source_of = {}
    man = root / "manifest.csv"
    if man.exists():
        with man.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                source_of[Path(r["file"]).stem] = r["source"]

    per_split = defaultdict(Counter)
    per_source = defaultdict(Counter)
    small = Counter()
    total = Counter()
    empty = Counter()
    by_class_source = defaultdict(list)
    for split in ("train", "valid", "test"):
        img_dir = root / split / "images"
        if not img_dir.is_dir():
            continue
        for img in sorted(img_dir.iterdir()):
            src = source_of.get(img.stem, "unknown")
            boxes = read_labels(root / split / "labels" / (img.stem + ".txt"))
            per_split[split]["images"] += 1
            if not boxes:
                empty[src] += 1
            for c, x, y, w, h in boxes:
                per_split[split][names[c]] += 1
                per_source[src][names[c]] += 1
                total[names[c]] += 1
                if min(w, h) * 640 < SMALL_PX:
                    small[names[c]] += 1
            for c in {b[0] for b in boxes}:
                by_class_source[(names[c], src)].append((img, boxes))

    L = ["DATASET AUDIT", "=" * 60, "", "Boxes per split:"]
    for s, c in per_split.items():
        L.append(f"  {s:5s} {c['images']:6d} images | " + ", ".join(f"{n} {c[n]}" for n in names))
    L += ["", "Boxes per source (0 = that source never labels the class -> partial labels):"]
    for src, c in sorted(per_source.items()):
        L.append(f"  {src:15s} " + ", ".join(f"{n} {c[n]}" for n in names) + f" | background images {empty[src]}")
    L += ["", f"Small boxes (shorter side < {SMALL_PX} px at 640):"]
    for n in names:
        if total[n]:
            L.append(f"  {n:16s} {small[n]:6d} of {total[n]:6d} ({small[n] / total[n] * 100:4.1f} %)")
    if total["pothole"] and small["pothole"] / total["pothole"] > 0.2:
        L.append("  -> many small potholes: train with imgsz 1024 or 1280.")
    biggest = max(total.values() or [1])
    L += ["", "Class balance (vs largest class):"]
    for n in names:
        r = total[n] / biggest if biggest else 0
        L.append(f"  {n:16s} {r * 100:5.1f} %" + ("   <- under-represented" if 0 < r < 0.2 else
                                                     "   <- NO DATA" if r == 0 else ""))

    rnd = random.Random(a.seed)
    sheets = 0
    for (cls, src), lst in sorted(by_class_source.items()):
        pick = rnd.sample(lst, min(a.per_sheet, len(lst)))
        tiles = [draw(img, boxes, names) for img, boxes in pick]
        cols = 6
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 320, rows * 320), (0, 0, 0))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * 320, (i // cols) * 320))
        sheet.save(out / f"sheet_{cls}_{src}.jpg", quality=85)
        sheets += 1
    L += ["", f"{sheets} picture sheets written to {out.resolve()}. Open every one and note wrong boxes."]
    rep = "\n".join(L)
    (out / "report.txt").write_text(rep, encoding="utf-8")
    print(rep)


if __name__ == "__main__":
    main()
