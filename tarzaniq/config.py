"""Configuration + data-directory management.

Everything that affects how a day is interpreted (warm-shoot gap,
break threshold, face filters...) lives here, is user-editable from
the dashboard Settings page, and is snapshotted into every day record
so old days remember the rules they were computed with.
"""

import json
import os
from pathlib import Path

# ---------------------------------------------------------------- defaults

DEFAULTS = {
    # --- engagement timing (seconds unless noted) ---
    "warm_gap_s": 5.0,          # delay >= this between shots of same subject => warm shoot
    "break_minutes": 20.0,      # gap >= this between any two photos => off the clock
    "max_pitch_minutes": 10.0,  # subject reappearing after longer than this = re-approach (new cold), not warm
    "warm_session_gap_minutes": 10.0,  # gap that splits a subject's warm shooting into separate sessions
    "pose_gap_s": 8.0,          # within a warm session, a pause >= this separates pose clusters

    # --- what counts as an in-focus subject ---
    "min_face_frac": 0.055,     # face box width as fraction of image width
    "min_face_blur": 40.0,      # Laplacian variance on the face crop (sharpness floor)
    "det_score_threshold": 0.78,  # YuNet confidence floor
    "face_match_threshold": 0.36,  # SFace cosine similarity to merge into existing subject

    # --- runtime ---
    "preview_enabled": True,
    "preview_max_width": 760,
    "decode_reduced": True,     # decode JPEGs at half resolution (fast, plenty for faces)
    "sounds_enabled": True,
}

CONFIG_VERSION = 1


# ---------------------------------------------------------------- paths

def data_dir() -> Path:
    """Data lives OUTSIDE the app so reinstalls never touch it."""
    override = os.environ.get("TARZANIQ_DATA")
    if override:
        p = Path(override).expanduser()
    else:
        p = Path.home() / "Documents" / "TarzanIQ Data"
    p.mkdir(parents=True, exist_ok=True)
    for sub in ("exports", "models", "logs", "backups"):
        (p / sub).mkdir(exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "tarzaniq.db"


def exports_dir() -> Path:
    return data_dir() / "exports"


def models_dir() -> Path:
    return data_dir() / "models"


def config_path() -> Path:
    return data_dir() / "config.json"


# ---------------------------------------------------------------- load/save

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text())
            for k, v in saved.items():
                if k in DEFAULTS:
                    cfg[k] = v
        except Exception:
            pass  # corrupted config -> fall back to defaults, never crash
    return cfg


def save_config(cfg: dict) -> dict:
    clean = {k: cfg[k] for k in DEFAULTS if k in cfg}
    merged = dict(DEFAULTS)
    merged.update(clean)
    merged["_version"] = CONFIG_VERSION
    config_path().write_text(json.dumps(merged, indent=2))
    return merged


def engagement_params(cfg: dict) -> dict:
    """The subset of config that drives cold/warm math (snapshotted per day)."""
    keys = ("warm_gap_s", "break_minutes", "max_pitch_minutes",
            "warm_session_gap_minutes", "pose_gap_s",
            "min_face_frac", "min_face_blur", "det_score_threshold",
            "face_match_threshold")
    return {k: cfg[k] for k in keys}
