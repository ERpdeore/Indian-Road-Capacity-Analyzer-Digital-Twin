# Retraining the obstruction detector

These scripts rebuild the training data and retrain `best.pt` so that the dashboard
detects obstructions more accurately. Run them on your own computer or in Google Colab,
where the images are.

## Why accuracy was low

| Problem | What it does to the model | Script that fixes it |
|---|---|---|
| Five Roboflow datasets give class numbers different meanings (1 = pothole in one, 1 = barricade in another) | It is taught that a pothole and a barricade are the same class | `merge_datasets.py` maps every label by **name** |
| Each dataset labels only its own class (the pothole set never boxes barricades) | Unlabelled barricades and cars are learned as background | duplicate photos share labels in `merge_datasets.py`; `fill_missing_labels.py` adds the rest |
| Roboflow saves 2–3 augmented copies of each photo, and the same photo can appear in two datasets | Copies land in both train and valid, so mAP looks better than it is | `merge_datasets.py` splits by photo group and removes duplicates |
| Shallow and small potholes are a few pixels wide at 640 px | They are never found | `train.py` trains at 1024 px; `audit_dataset.py` shows how many boxes are small |
| "Illegal parking" cannot be seen in a photo, only a parked vehicle can | Parked cars and barricades get mixed up | label rule in `class_map.yaml`; `evaluate.py` counts the mix-ups |
| One confidence threshold for all classes | Too many false alarms for some classes, misses for others | `evaluate.py` picks a threshold per class |

## Steps

**0. Download** each Roboflow dataset as **YOLOv8** format and unzip it into `training/raw/<name>/`.
Each folder must contain `data.yaml` and `train/`, `valid/` (and maybe `test/`).
Put 100 or more of **your own Nashik road photos**, labelled by you, in `raw/nashik_own/`.
They become the test set, which is the honest accuracy figure for your report.

**1. Tell the script what each dataset is.** Edit the `datasets:` list at the bottom of `class_map.yaml`.
Then run the check only:
```
pip install pyyaml pillow "numpy>=2"
python merge_datasets.py --config class_map.yaml --check
```
It prints how every class of every dataset is mapped. It **stops** when a class name is
unknown, ambiguous (`car`: parked or moving?) or only a number (`'0'`). Look at a few of
those images, write your decision under that dataset's `map:`, and run the check again.

**2. Merge:**
```
python merge_datasets.py --config class_map.yaml --out merged
```
Read `merged/merge_report.txt`: boxes per class, duplicates removed, warnings.

**3. Look at the labels:**
```
python audit_dataset.py --data merged/data.yaml --out audit
```
Open every `audit/sheet_<class>_<source>.jpg`. Wrong boxes show up quickly. Fix them in
Roboflow, or delete that dataset if it is bad, then merge again.

**4. Train** on a GPU (Colab: Runtime → Change runtime type → T4 GPU):
```
pip install ultralytics==8.3.0      # same version as the dashboard server
python train.py --data merged/data.yaml
```
This takes about 2–4 hours on a free T4 for about 9,000 photos at 1024 px.
If Colab runs out of memory, add `--batch 8`.

**5. Fill missing labels, review, retrain:**
```
python fill_missing_labels.py --model runs/detect/road_obstructions/weights/best.pt --data merged/data.yaml --out merged_filled
python audit_dataset.py --data merged_filled/data.yaml --out audit_filled
python train.py --data merged_filled/data.yaml --name road_obstructions_v2
```
Every added box is listed in `merged_filled/added_boxes_review.csv`. Delete wrong ones
before retraining.

**6. Measure and choose thresholds:**
```
python evaluate.py --model runs/detect/road_obstructions_v2/weights/best.pt --data merged_filled/data.yaml
```
`evaluation/evaluation_report.txt` gives precision, recall and mAP50 per class on your own
test photos, plus lines such as "real barricade: 12 called illegal_parking". Put these
numbers in the report.

**7. Use it in the dashboard:** copy `best.pt` and `evaluation/class_thresholds.json` into
`road_analyzer_deploy/road_analyzer/models/`. The dashboard reads the thresholds, uses
the image size the model was trained at, and when one object gets two obstruction labels
it keeps only the more confident one.

On the Render free server (512 MB), 1024 px inference may be slow or run out of memory.
Set the environment variable `ROAD_INFER_IMGSZ=640` if it does. Accuracy on small
potholes then drops.

## What retraining cannot fix

- **Pothole depth.** One ordinary photo cannot measure it. Severity stays width-based
  (IRC:82-2015), and depth needs a site measurement.
- **Legality of parking.** The model finds parked vehicles. Whether they are illegal is a
  rule about the location.
- **Photos unlike the training data** (night, rain, very different roads). Add such photos
  to your own set.
