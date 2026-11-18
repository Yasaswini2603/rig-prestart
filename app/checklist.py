"""The prestart checklist for a drill rig.

Each item has a severity that decides what happens when it fails:
- critical: the rig must not operate until it's fixed
- high:     the rig can run, but maintenance must fix it soon
- low:      log it and fix when convenient
"""

CHECKLIST = [
    {"key": "estops", "label": "Emergency stops tested and working", "severity": "critical"},
    {"key": "guards", "label": "Rod handler and rotation guards in place", "severity": "critical"},
    {"key": "fire_ext", "label": "Fire extinguisher present, charged and tagged", "severity": "critical"},
    {"key": "hoses", "label": "Hydraulic hoses: no leaks, cuts or rubbing", "severity": "high"},
    {"key": "engine_oil", "label": "Engine oil level OK", "severity": "high"},
    {"key": "coolant", "label": "Coolant level OK", "severity": "high"},
    {"key": "compressor", "label": "Compressor pressure and temperature normal", "severity": "high"},
    {"key": "mast", "label": "Mast and drill string visual inspection", "severity": "high"},
    {"key": "lights", "label": "Lights, beacon and reversing alarm working", "severity": "low"},
    {"key": "housekeeping", "label": "Deck clear of trip hazards", "severity": "low"},
    {"key": "seatbelt", "label": "Seatbelt and cab door working", "severity": "high"},
]

ITEMS_BY_KEY = {item["key"]: item for item in CHECKLIST}
