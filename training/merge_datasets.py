"""
merge_datasets.py — join several Roboflow YOLO exports into ONE clean dataset.

Why: a YOLO label stores only a class NUMBER. Each Roboflow dataset gives
the numbers its own meaning (1 = pothole in one, 1 = barricade in another).
Copying the folders together therefore teaches the model that a pothole and
a barricade are the same class. This script:

  1. reads each dataset's own data.yaml and turns every number back into its NAME
  2. maps the name to the master class list in class_map.yaml
     (per-dataset decisions first, then synonyms, then drop list;
     anything undecided -> the script stops and tells you what to add)
  3. converts polygon labels to boxes, clips them to the image, drops empty boxes
  4. finds the same photo in different datasets (and Roboflow's augmented
     copies of one photo) and keeps ONE copy
  5. splits by PHOTO GROUP, so a photo and its augmented copies never end up
     in both train and valid (that leak makes mAP look better than it is)
  6. writes out/ {train,valid,test}/{images,labels}, data.yaml, manifest.csv,
     merge_report.txt

Usage
-----
  python merge_datasets.py --config class_map.yaml --out merged
  python merge_datasets.py --config class_map.yaml --out merged --check   # mapping only, no copying

Needs: pyyaml, pillow, numpy (>= 2.0 for fast duplicate search).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_DIRS = {"train": "train", "valid": "valid", "val": "valid", "test": "test"}
DUP_HAMMING = 4          # dHash bits that may differ for "same photo"
MIN_BOX = 1e-3           # boxes thinner than 0.1 % of the image are dropped


def norm(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(name).strip().lower())


# ------------------------------------------------------------------
# Class mapping
# ------------------------------------------------------------------
def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["_dir"] = path.parent
    master = cfg["master"]
    if len(set(master)) != len(master):
        sys.exit("class_map.yaml: master list has duplicates.")
    syn = {}
    for cls, names in (cfg.get("synonyms") or {}).items():
        if cls not in master:
            sys.exit(f"class_map.yaml: synonym target '{cls}' is not in master.")
        for n in names:
            syn[norm(n)] = cls
    cfg["_syn"] = syn
    cfg["_drop"] = {norm(n) for n in cfg.get("drop") or []}
    cfg["_ambiguous"] = {norm(n) for n in cfg.get("ambiguous") or []}
    return cfg


def read_names(data_yaml: Path) -> list[str]:
    d = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    names = d.get("names")
    if isinstance(names, dict):                      # {0: a, 1: b}
        names = [names[k] for k in sorted(names, key=int)]
    if not names:
        sys.exit(f"{data_yaml}: no 'names' list.")
    return [str(n) for n in names]


def build_map(ds: dict, names: list[str], cfg: dict) -> tuple[dict, list[str]]:
    """source class id -> master id, or None (drop). Returns (map, problems)."""
    master = cfg["master"]
    local = {norm(k): v for k, v in (ds.get("map") or {}).items()}
    out, problems = {}, []
    for i, raw in enumerate(names):
        n = norm(raw)
        if n in local:
            target = local[n]
        elif n.isdigit():
            problems.append(f"  class {i} is named only '{raw}': look at its images and add "
                            f"map: {{'{raw}': <class or drop>}}")
            continue
        elif n in cfg["_ambiguous"]:
            problems.append(f"  class {i} '{raw}' is ambiguous (parked or moving?): add "
                            f"map: {{{raw}: illegal_parking | vehicle | drop}}")
            continue
        elif n in cfg["_syn"]:
            target = cfg["_syn"][n]
        elif n in cfg["_drop"]:
            target = "drop"
        elif n in master:
            target = n
        else:
            problems.append(f"  class {i} '{raw}' is unknown: add it to synonyms, drop, or "
                            f"this dataset's map")
            continue
        if target == "drop":
            out[i] = None
        elif target in master:
            out[i] = master.index(target)
        else:
            problems.append(f"  class {i} '{raw}' maps to '{target}', which is not a master class")
    return out, problems


# ------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------
def parse_label_file(path: Path) -> tuple[list[tuple[int, float, float, float, float]], int]:
    """YOLO box or polygon lines -> boxes (cls, xc, yc, w, h), clipped.
    Returns (boxes, number of bad lines)."""
    boxes, bad = [], 0
    if not path.exists():
        return boxes, 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        p = line.split()
        if not p:
            continue
        try:
            c = int(float(p[0]))
            v = [float(x) for x in p[1:]]
        except ValueError:
            bad += 1
            continue
        if len(v) == 4:
            xc, yc, w, h = v
            x1, y1, x2, y2 = xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2
        elif len(v) >= 6 and len(v) % 2 == 0:       # polygon (segmentation export)
            xs, ys = v[0::2], v[1::2]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        else:
            bad += 1
            continue
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(1.0, x2), min(1.0, y2)
        if x2 - x1 < MIN_BOX or y2 - y1 < MIN_BOX:
            bad += 1
            continue
        boxes.append((c, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
    return boxes, bad


# ------------------------------------------------------------------
# Duplicates and groups
# ------------------------------------------------------------------
def dhash(path: Path) -> int:
    """64-bit difference hash: survives resizing, compression and small
    brightness changes (Roboflow exports); not flips or crops."""
    with Image.open(path) as im:
        g = np.asarray(im.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def roboflow_stem(path: Path) -> str:
    """'IMG_0042_jpg.rf.3f9c...jpg' -> 'IMG_0042': Roboflow's augmented
    copies of one photo share this stem."""
    s = path.name
    return s.split(".rf.")[0] if ".rf." in s else path.stem


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def near_duplicate_pairs(hashes: list[int], max_bits: int) -> list[tuple[int, int]]:
    h = np.array(hashes, dtype=np.uint64)
    pairs = []
    for i in range(len(h) - 1):
        d = np.bitwise_count(h[i + 1:] ^ h[i])
        for j in np.nonzero(d <= max_bits)[0]:
            pairs.append((i, i + 1 + int(j)))
    return pairs


def iou_xywh(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-12)


def split_of_group(key: str, valid_frac: float, seed: str) -> str:
    x = int(hashlib.sha1((seed + key).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "valid" if x < valid_frac else "train"


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def collect(cfg: dict) -> tuple[list[dict], list[str]]:
    items, problems = [], []
    for ds in cfg["datasets"]:
        root = Path(ds["path"])
        if not root.is_absolute():
            root = (cfg["_dir"] / root).resolve()
        data_yaml = root / "data.yaml"
        if not data_yaml.exists():
            problems.append(f"[{ds['name']}] no data.yaml in {root}")
            continue
        names = read_names(data_yaml)
        cmap, probs = build_map(ds, names, cfg)
        if probs:
            problems.append(f"[{ds['name']}] classes {names}:\n" + "\n".join(probs))
            continue
        ds["_names"], ds["_map"] = names, cmap
        n_before = len(items)
        for sub in sorted(root.iterdir()):
            if not sub.is_dir() or sub.name.lower() not in SPLIT_DIRS:
                continue
            img_dir = sub / "images"
            if not img_dir.is_dir():
                continue
            for img in sorted(img_dir.rglob("*")):
                if img.suffix.lower() in IMG_EXT:
                    items.append({"source": ds["name"], "role": ds.get("role", "train"),
                                  "img": img, "label": sub / "labels" / (img.stem + ".txt"),
                                  "src_split": SPLIT_DIRS[sub.name.lower()]})
        if len(items) == n_before:
            problems.append(f"[{ds['name']}] no images found under {root}/{{train,valid,test}}/images")
    return items, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="class_map.yaml")
    ap.add_argument("--out", default="merged")
    ap.add_argument("--valid-frac", type=float, default=0.15)
    ap.add_argument("--seed", default="road-analyzer")
    ap.add_argument("--dup-bits", type=int, default=DUP_HAMMING)
    ap.add_argument("--check", action="store_true", help="only check the class mapping")
    a = ap.parse_args()

    cfg = load_config(Path(a.config))
    items, problems = collect(cfg)
    print("Class mapping:")
    for ds in cfg["datasets"]:
        if "_map" in ds:
            m = ", ".join(f"{ds['_names'][i]}->{cfg['master'][t] if t is not None else 'DROP'}"
                          for i, t in ds["_map"].items())
            print(f"  [{ds['name']}] {m}")
    if problems:
        print("\nFix class_map.yaml first:\n" + "\n".join(problems))
        sys.exit(1)
    if a.check:
        print(f"\nMapping OK. {len(items)} images found.")
        return

    by_name = {d["name"]: d for d in cfg["datasets"]}
    order = {d["name"]: i for i, d in enumerate(cfg["datasets"])}

    # read and remap labels
    stats = defaultdict(Counter)
    for it in items:
        boxes, bad = parse_label_file(it["label"])
        cmap = by_name[it["source"]]["_map"]
        out, unknown_ids = [], 0
        for c, *xywh in boxes:
            if c not in cmap:
                unknown_ids += 1
                continue
            if cmap[c] is None:
                stats[it["source"]]["boxes_dropped_by_class"] += 1
                continue
            out.append((cmap[c], *xywh))
        it["boxes"] = out
        st = stats[it["source"]]
        st["images"] += 1
        st["bad_lines"] += bad
        st["ids_not_in_data_yaml"] += unknown_ids
        if boxes and not out:
            st["images_emptied_by_drop"] += 1
        if not boxes:
            st["images_without_labels"] += 1
        for b in out:
            st[f"box:{cfg['master'][b[0]]}"] += 1

    # duplicates: Roboflow augment groups + near-identical photos across datasets
    print(f"Hashing {len(items)} images for duplicates ...")
    for it in items:
        it["hash"] = dhash(it["img"])
    uf = UnionFind(len(items))
    first = {}
    for i, it in enumerate(items):
        k = (it["source"], roboflow_stem(it["img"]))
        if k in first:
            uf.union(first[k], i)
        else:
            first[k] = i
    for i, j in near_duplicate_pairs([it["hash"] for it in items], a.dup_bits):
        uf.union(i, j)
    groups = defaultdict(list)
    for i in range(len(items)):
        groups[uf.find(i)].append(i)

    # One copy per photo. A near-identical copy from ANOTHER dataset is not
    # thrown away blind: its boxes are added to the kept copy (each source
    # labels different classes, so this fills missing labels for free).
    keep, removed = [], Counter()
    for members in groups.values():
        role = "test" if any(items[i]["role"] == "test" for i in members) else "train"
        gkey = min(f"{items[i]['source']}/{roboflow_stem(items[i]['img'])}" for i in members)
        split = "test" if role == "test" else split_of_group(gkey, a.valid_frac, a.seed)
        kept_here = []
        for i in sorted(members, key=lambda k: (order[items[k]["source"]], str(items[k]["img"]))):
            it = items[i]
            twin = next((k for k in kept_here
                         if bin(k["hash"] ^ it["hash"]).count("1") <= a.dup_bits), None)
            if twin is None:
                it["split"], it["group"] = split, gkey
                kept_here.append(it)
                continue
            if twin["source"] == it["source"]:
                removed[f"{it['source']} (near-identical copy)"] += 1
                continue
            added = 0
            for b in it["boxes"]:
                if not any(o[0] == b[0] and iou_xywh(o[1:], b[1:]) > 0.5 for o in twin["boxes"]):
                    twin["boxes"].append(b)
                    added += 1
            removed[f"{it['source']} (same photo as {twin['source']})"] += 1
            removed[f"  boxes added from {it['source']} to {twin['source']} copies"] += added
        keep.extend(kept_here)

    # write
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    for s in ("train", "valid", "test"):
        (out / s / "images").mkdir(parents=True)
        (out / s / "labels").mkdir(parents=True)
    split_counts = defaultdict(Counter)
    with (out / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "split", "source", "group", "original", "classes"])
        for n, it in enumerate(keep):
            name = f"{it['source']}_{n:06d}{it['img'].suffix.lower()}"
            shutil.copy2(it["img"], out / it["split"] / "images" / name)
            (out / it["split"] / "labels" / (Path(name).stem + ".txt")).write_text(
                "".join(f"{c} {x:.6f} {y:.6f} {bw:.6f} {bh:.6f}\n" for c, x, y, bw, bh in it["boxes"]),
                encoding="utf-8")
            cls = sorted({cfg["master"][b[0]] for b in it["boxes"]})
            w.writerow([name, it["split"], it["source"], it["group"], str(it["img"]), ";".join(cls)])
            split_counts[it["split"]]["images"] += 1
            for b in it["boxes"]:
                split_counts[it["split"]][cfg["master"][b[0]]] += 1

    has_test = split_counts["test"]["images"] > 0
    data = {"path": str(out.resolve()), "train": "train/images", "val": "valid/images",
            "names": {i: n for i, n in enumerate(cfg["master"])}}
    if has_test:
        data["test"] = "test/images"
    (out / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    # report
    lines = ["MERGE REPORT", "=" * 60, "", "Per source (before duplicate removal):"]
    for src, st in stats.items():
        lines.append(f"  [{src}] " + ", ".join(f"{k} {v}" for k, v in sorted(st.items())))
    lines += ["", "Removed as duplicates:"] + ([f"  {k}: {v}" for k, v in removed.items()] or ["  none"])
    lines += ["", "Final dataset:"]
    for s in ("train", "valid", "test"):
        c = split_counts[s]
        lines.append(f"  {s:5s}: {c['images']} images | " +
                     ", ".join(f"{n} {c[n]}" for n in cfg["master"]))
    warn = []
    for n in cfg["master"]:
        if split_counts["train"][n] < 300:
            warn.append(f"  '{n}' has only {split_counts['train'][n]} training boxes; aim for 1000+.")
        if split_counts["valid"][n] < 50:
            warn.append(f"  '{n}' has only {split_counts['valid'][n]} validation boxes; its mAP will be noisy.")
    for src, st in stats.items():
        if st["ids_not_in_data_yaml"]:
            warn.append(f"  [{src}] {st['ids_not_in_data_yaml']} boxes used class ids missing from its "
                        f"data.yaml (deleted). The export may be broken.")
        if st["images_emptied_by_drop"]:
            warn.append(f"  [{src}] {st['images_emptied_by_drop']} images lost ALL boxes to the drop list; "
                        f"they now teach 'nothing here'. Check that is true.")
    if not has_test:
        warn.append("  No test split. Add your own road photos as a dataset with role: test.")
    lines += ["", "Warnings:"] + (warn or ["  none"])
    lines += ["", "Partial labels: each source labels only its own classes. A pothole photo with an",
              "unlabelled barricade teaches 'barricade = background'. Run fill_missing_labels.py after",
              "a first training run, review the added boxes, then retrain."]
    report = "\n".join(lines)
    (out / "merge_report.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWritten: {out.resolve()}/data.yaml")


if __name__ == "__main__":
    main()
