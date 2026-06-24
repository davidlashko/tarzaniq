"""Per-day processing fingerprint (Feature B).

Pure functions: given config + the model/algo version constants, compute the
four fingerprint components, and route a stale day to the cheapest valid path.
No I/O — see pipeline.bring_current for the orchestration.
"""

import hashlib
import json

from . import MODEL_VERSION, ALGO_VERSION, config

TIMING_KEYS = ("warm_gap_s", "break_minutes", "max_pitch_minutes",
               "warm_session_gap_minutes", "pose_gap_s")
FACE_KEYS = ("min_face_frac", "min_face_blur", "det_score_threshold",
             "face_match_threshold")


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def components(cfg: dict) -> dict:
    return {
        "engagement_fp": _hash({k: cfg[k] for k in TIMING_KEYS}),
        "detection_fp": _hash({k: cfg[k] for k in FACE_KEYS}),
        "model_version": MODEL_VERSION,
        "algo_version": ALGO_VERSION,
    }


def current() -> dict:
    return components(config.load_config())


def fingerprint(comp: dict) -> str:
    return (f"e{comp['engagement_fp']}-d{comp['detection_fp']}"
            f"-m{comp['model_version']}-a{comp['algo_version']}")


def route(stored: dict | None, current_comp: dict, has_archive: bool) -> str:
    """current | recompute | reprocess | legacy."""
    keys = ("engagement_fp", "detection_fp", "model_version", "algo_version")
    if not stored or any(k not in stored for k in keys):
        return "recompute"          # no/partial stored fp: cheap re-derive + stamp
    if stored == current_comp:
        return "current"
    if (stored["detection_fp"] != current_comp["detection_fp"]
            or stored["model_version"] != current_comp["model_version"]
            or stored["algo_version"] != current_comp["algo_version"]):
        return "reprocess" if has_archive else "legacy"
    return "recompute"              # only engagement_fp differs


def is_comparable(stored: dict | None, current_comp: dict, has_archive: bool) -> bool:
    """A day is excluded from comparisons only when it is legacy."""
    return route(stored, current_comp, has_archive) != "legacy"
