"""Face engine: detection (YuNet), same-day identity (SFace embeddings),
age & gender estimation (GoogleNet ONNX), plus the live-preview annotator.

Privacy by design: embeddings live in RAM for the duration of one
folder's processing and are thrown away. Only derived attributes
(subject number, age bucket, gender, timing) are ever written to disk.
"""

import colorsys
import math
from pathlib import Path

import cv2
import numpy as np

MODEL_FILES = {
    "yunet": "face_detection_yunet_2023mar.onnx",
    "sface": "face_recognition_sface_2021dec.onnx",
    "age": "age_googlenet.onnx",
    "gender": "gender_googlenet.onnx",
}

AGE_BUCKETS = ["0-2", "4-6", "8-12", "15-20", "25-32", "38-43", "48-53", "60+"]
AGE_MIDPOINTS = [1, 5, 10, 18, 28, 40, 50, 68]
GENDER_LABELS = ["M", "F"]  # Levi-Hassner / Adience convention: index 0 = male


class FaceObs:
    """One detected face in one photo."""
    __slots__ = ("box", "score", "blur", "frac", "embedding",
                 "age_probs", "gender_probs", "accepted", "reject_reason",
                 "sid", "mock_sid")

    def __init__(self):
        self.box = (0, 0, 0, 0)
        self.score = 0.0
        self.blur = 0.0
        self.frac = 0.0
        self.embedding = None
        self.age_probs = None
        self.gender_probs = None
        self.accepted = False
        self.reject_reason = None
        self.sid = None
        self.mock_sid = None


def _softmax(x):
    x = np.asarray(x, dtype=np.float64).ravel()
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


class FaceEngine:
    """Real engine. Requires yunet + sface models; age/gender are optional
    (if missing, demographics simply come back unknown)."""

    def __init__(self, models_dir: Path, cfg: dict):
        self.cfg = cfg
        models_dir = Path(models_dir)
        yunet = models_dir / MODEL_FILES["yunet"]
        sface = models_dir / MODEL_FILES["sface"]
        if not yunet.exists():
            raise FileNotFoundError(
                f"Face detection model missing: {yunet}\n"
                "Run install.sh again or download models manually (see README).")
        if not sface.exists():
            raise FileNotFoundError(
                f"Face identity model missing: {sface}\n"
                "Run install.sh again or download models manually (see README).")
        self.detector = cv2.FaceDetectorYN.create(
            str(yunet), "", (320, 320),
            float(cfg["det_score_threshold"]), 0.3, 200)
        self.recognizer = cv2.FaceRecognizerSF.create(str(sface), "")

        self.age_net = self.gender_net = None
        age_p, gender_p = models_dir / MODEL_FILES["age"], models_dir / MODEL_FILES["gender"]
        try:
            if age_p.exists():
                self.age_net = cv2.dnn.readNetFromONNX(str(age_p))
            if gender_p.exists():
                self.gender_net = cv2.dnn.readNetFromONNX(str(gender_p))
        except Exception:
            self.age_net = self.gender_net = None

    # -------------------------------------------------------- analyze
    def analyze(self, bgr, meta=None):
        """Returns list[FaceObs] for one decoded image (BGR)."""
        h, w = bgr.shape[:2]
        # detection works best <= ~1600px wide; faces are cropped from `bgr`
        scale = 1.0
        det_img = bgr
        if w > 1600:
            scale = 1600.0 / w
            det_img = cv2.resize(bgr, (1600, int(h * scale)),
                                 interpolation=cv2.INTER_AREA)
        dh, dw = det_img.shape[:2]
        self.detector.setInputSize((dw, dh))
        _, faces = self.detector.detect(det_img)
        out = []
        if faces is None:
            return out

        min_frac = float(self.cfg["min_face_frac"])
        min_blur = float(self.cfg["min_face_blur"])

        for row in faces:
            obs = FaceObs()
            x, y, fw, fh = row[0], row[1], row[2], row[3]
            obs.score = float(row[14])
            # back to full-res coords
            inv = 1.0 / scale
            X, Y, FW, FH = (int(x * inv), int(y * inv),
                            int(fw * inv), int(fh * inv))
            X, Y = max(X, 0), max(Y, 0)
            FW, FH = min(FW, w - X), min(FH, h - Y)
            if FW <= 4 or FH <= 4:
                continue
            obs.box = (X, Y, FW, FH)
            obs.frac = FW / float(w)

            crop = bgr[Y:Y + FH, X:X + FW]
            g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if g.shape[0] > 96:
                g = cv2.resize(g, (int(g.shape[1] * 96 / g.shape[0]), 96),
                               interpolation=cv2.INTER_AREA)
            obs.blur = float(cv2.Laplacian(g, cv2.CV_64F).var())

            if obs.frac < min_frac:
                obs.reject_reason = "small"
            elif obs.blur < min_blur:
                obs.reject_reason = "soft"
            else:
                obs.accepted = True
                # align using YuNet landmarks scaled back to full-res
                row_full = row.copy()
                row_full[:14] = row[:14] * inv
                try:
                    aligned = self.recognizer.alignCrop(bgr, row_full)
                except Exception:
                    aligned = cv2.resize(crop, (112, 112))
                feat = self.recognizer.feature(aligned)
                v = np.asarray(feat, dtype=np.float32).ravel()
                n = np.linalg.norm(v)
                obs.embedding = v / n if n > 0 else v
                self._age_gender(aligned, obs)
            out.append(obs)
        return out

    def _age_gender(self, aligned112, obs):
        if self.age_net is None and self.gender_net is None:
            return
        blob = cv2.dnn.blobFromImage(
            cv2.resize(aligned112, (224, 224)), 1.0, (224, 224),
            (104.0, 117.0, 123.0), swapRB=False)
        try:
            if self.age_net is not None:
                self.age_net.setInput(blob)
                obs.age_probs = _softmax(self.age_net.forward())
            if self.gender_net is not None:
                self.gender_net.setInput(blob)
                obs.gender_probs = _softmax(self.gender_net.forward())
        except Exception:
            pass


class MockEngine:
    """Test engine: a manifest dict maps filename -> {"subjects": [ids],
    "extra": n_rejected_faces}. Lets the whole pipeline run end-to-end
    with no models and no real faces."""

    def __init__(self, manifest):
        self.manifest = manifest

    def analyze(self, bgr, meta=None):
        fname = (meta or {}).get("filename")
        spec = self.manifest.get(fname, {})
        out = []
        h, w = bgr.shape[:2]
        for i, sid in enumerate(spec.get("subjects", [])):
            obs = FaceObs()
            obs.box = (10 + i * 60, 10, 50, 50)
            obs.score, obs.blur, obs.frac = 0.95, 200.0, 0.2
            obs.accepted = True
            obs.mock_sid = sid
            g = spec.get("gender", {}).get(sid)
            a = spec.get("age", {}).get(sid)
            if g is not None:
                obs.gender_probs = np.array([0.9, 0.1]) if g == "M" else np.array([0.1, 0.9])
            if a is not None:
                p = np.full(8, 0.01)
                p[a] = 0.93
                obs.age_probs = p
            out.append(obs)
        for i in range(spec.get("extra", 0)):
            obs = FaceObs()
            obs.box = (w - 60 - i * 30, h - 60, 24, 24)
            obs.score, obs.blur, obs.frac = 0.85, 20.0, 0.02
            obs.reject_reason = "small"
            out.append(obs)
        return out


# ================================================================ tracker

class SubjectTracker:
    """Clusters face embeddings into same-day subject identities and
    accumulates weighted age/gender votes. Embeddings never leave RAM."""

    def __init__(self, match_threshold=0.36):
        self.thr = float(match_threshold)
        self.centroids = []   # list[np.array]
        self.counts = []
        self.age_votes = []   # accumulated weighted age prob vectors
        self.gender_votes = []
        self.photo_counts = []
        self.weights = []

    def assign(self, obs: FaceObs):
        if obs.mock_sid is not None:                      # test path
            sid = obs.mock_sid
            while len(self.counts) <= sid:
                self._new_slot()
            self._vote(sid, obs)
            obs.sid = sid
            return sid
        if obs.embedding is None:
            return None
        best, best_sim = None, -1.0
        for i, c in enumerate(self.centroids):
            if c is None:
                continue
            sim = float(np.dot(c, obs.embedding))
            if sim > best_sim:
                best, best_sim = i, sim
        if best is not None and best_sim >= self.thr:
            sid = best
            c = self.centroids[sid] * self.counts[sid] + obs.embedding
            n = np.linalg.norm(c)
            self.centroids[sid] = c / n if n > 0 else c
            self.counts[sid] += 1
        else:
            sid = len(self.centroids)
            self._new_slot()
            self.centroids[sid] = obs.embedding.copy()
            self.counts[sid] = 1
        self._vote(sid, obs)
        obs.sid = sid
        return sid

    def _new_slot(self):
        self.centroids.append(None)
        self.counts.append(0)
        self.age_votes.append(np.zeros(8))
        self.gender_votes.append(np.zeros(2))
        self.photo_counts.append(0)
        self.weights.append(0.0)

    def _vote(self, sid, obs):
        w = obs.frac * math.sqrt(max(obs.blur, 1.0))
        self.photo_counts[sid] += 1
        self.weights[sid] += w
        if obs.age_probs is not None:
            self.age_votes[sid] += w * obs.age_probs
        if obs.gender_probs is not None:
            self.gender_votes[sid] += w * obs.gender_probs

    def finalize(self):
        """sid -> {"gender","gender_conf","age_bucket","age_est","photo_count"}"""
        out = {}
        for sid in range(len(self.counts)):
            if self.photo_counts[sid] == 0:
                continue
            meta = {"photo_count": self.photo_counts[sid],
                    "gender": None, "gender_conf": None,
                    "age_bucket": None, "age_est": None}
            gv = self.gender_votes[sid]
            if gv.sum() > 0:
                p = gv / gv.sum()
                conf = float(p.max())
                meta["gender_conf"] = round(conf, 3)
                meta["gender"] = GENDER_LABELS[int(p.argmax())] if conf >= 0.58 else "unknown"
            av = self.age_votes[sid]
            if av.sum() > 0:
                p = av / av.sum()
                meta["age_bucket"] = AGE_BUCKETS[int(p.argmax())]
                meta["age_est"] = round(float(np.dot(p, AGE_MIDPOINTS)), 1)
            out[sid] = meta
        return out


# ================================================================ preview

def subject_color(sid):
    """Stable, distinct BGR color per subject id."""
    h = (sid * 0.6180339887) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return (int(b * 255), int(g * 255), int(r * 255))


def annotate_preview(bgr, observations, subject_meta, banner, kind,
                     max_width=760):
    """Draw boxes + labels on a downscaled copy for the live viewer.
    Returns JPEG bytes."""
    h, w = bgr.shape[:2]
    scale = min(max_width / float(w), 1.0)
    img = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                     interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr.copy()

    for obs in observations:
        x, y, fw, fh = [int(v * scale) for v in obs.box]
        if obs.accepted and obs.sid is not None:
            color = subject_color(obs.sid)
            cv2.rectangle(img, (x, y), (x + fw, y + fh), color, 2)
            meta = subject_meta.get(obs.sid, {})
            bits = [f"S{obs.sid + 1}"]
            if meta.get("gender"):
                bits.append(meta["gender"])
            if meta.get("age_bucket"):
                bits.append(meta["age_bucket"])
            label = " ".join(bits)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            ly = y - 6 if y - th - 10 > 0 else y + fh + th + 6
            cv2.rectangle(img, (x, ly - th - 4), (x + tw + 6, ly + 4), color, -1)
            cv2.putText(img, label, (x + 3, ly), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (10, 10, 10), 2, cv2.LINE_AA)
        else:
            cv2.rectangle(img, (x, y), (x + fw, y + fh), (120, 120, 120), 1)
            if obs.reject_reason:
                cv2.putText(img, obs.reject_reason, (x, max(y - 4, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160), 1,
                            cv2.LINE_AA)

    kind_colors = {"cold": (235, 206, 135), "warm": (80, 200, 255),
                   "mixed": (180, 220, 120), "air": (140, 140, 140)}
    tag = {"cold": "COLD SHOOT", "warm": "WARM SHOOT",
           "mixed": "COLD+WARM", "air": "NO SUBJECT"}.get(kind, kind.upper())
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (20, 28, 20), -1)
    cv2.putText(img, banner, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (230, 230, 230), 1, cv2.LINE_AA)
    (tw, _), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(img, (img.shape[1] - tw - 18, 0), (img.shape[1], 30),
                  kind_colors.get(kind, (90, 90, 90)), -1)
    cv2.putText(img, tag, (img.shape[1] - tw - 10, 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (15, 15, 15), 2, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return buf.tobytes() if ok else b""
