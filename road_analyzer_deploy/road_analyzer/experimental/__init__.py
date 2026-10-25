"""
Modules that are NOT wired into the web app. They are kept for future work
and are not imported by app.py.

  speed_challan.py       line-crossing speed estimate; needs per-camera
                         calibration lines and a tracker (not collected yet)
  plate_recognition.py   ANPR evidence crops; needs easyocr (not in requirements.txt)
  footpath_pedestrian.py needs a pedestrian model, shapely, and operator-drawn
                         footpath / carriageway polygons per camera
  report_generator.py    CSV department reports; superseded by the PDF report
  digital_twin_bridge.py launches local MATLAB; superseded by digital_twin_engine.py

Each must be wired into app.py, given its inputs and validated before any
of its output is presented as a project result.
"""
