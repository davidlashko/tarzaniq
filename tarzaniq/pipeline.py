"""Processing pipeline + application state.

A background worker thread takes folders off a queue and runs each
through two phases:

  Phase 1 (seconds): folder-name validation, JPEG scan, EXIF time read
  for every file (header-only, fast), chronological sort, deletion scan.

  Phase 2 (the long part): decode each photo -> detect faces -> assign
  same-day identity -> step the engagement engine -> stream an annotated
  preview frame to any open dashboards.

Prompts (new name/place, duplicate day, money, commit) pause the worker
until the dashboard answers. Pause/resume from the live viewer halts
the loop between photos.
"""

import base64
import json
import queue as queue_mod
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, date
from pathlib import Path

import cv2
import numpy as np

from . import APP_VERSION, config, db, naming, exifutil, archive, fingerprint
from .engagements import Engager, analyze
from .engine import FaceEngine, SubjectTracker, annotate_preview
from .excelio import export_day
from .stats import compute_day_stats


class Job:
    def __init__(self, folder, kind="ingest", day_id=None):
        self.id = uuid.uuid4().hex[:10]
        self.folder = Path(folder)
        self.name = self.folder.name
        self.kind = kind            # "ingest" | "reprocess"
        self.day_id = day_id        # set for reprocess jobs
        self.status = "queued"      # queued/scanning/processing/waiting/
                                    # committing/done/error/discarded/skipped
        self.message = ""
        self.progress = 0
        self.total = 0
        self.date = None
        self.place = None
        self.employee = None
        self.cancel = False
        self.result_day_id = None
        self.export_path = None

    def brief(self):
        return {"id": self.id, "folder": str(self.folder), "name": self.name,
                "kind": self.kind,
                "status": self.status, "message": self.message,
                "progress": self.progress, "total": self.total,
                "date": str(self.date) if self.date else None,
                "place": self.place, "employee": self.employee,
                "day_id": self.result_day_id}


class AppState:
    def __init__(self, engine_factory=None):
        self.cfg = config.load_config()
        self.jobs = []
        self.q = queue_mod.Queue()
        self.subscribers = []            # list[queue.Queue] for SSE
        self.lock = threading.Lock()
        self.run_flag = threading.Event()
        self.run_flag.set()              # cleared = paused
        self.pending_prompt = None       # {"id","type","payload","job_id"}
        self._answers = {}               # prompt_id -> data
        self._answer_evt = threading.Event()
        self.engine_factory = engine_factory or self._real_engine
        self._engine = None
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    # ------------------------------------------------------------ engine
    def _real_engine(self):
        return FaceEngine(config.models_dir(), self.cfg)

    def engine(self):
        if self._engine is None:
            self._engine = self.engine_factory()
        return self._engine

    def reload_config(self):
        self.cfg = config.load_config()
        self._engine = None  # thresholds may have changed

    # ------------------------------------------------------------ SSE
    def subscribe(self):
        q = queue_mod.Queue(maxsize=400)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def broadcast(self, event, data):
        msg = (event, data)
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue_mod.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    def has_subscribers(self):
        with self.lock:
            return len(self.subscribers) > 0

    # ------------------------------------------------------------ queue
    def enqueue(self, folders):
        added, errors = [], []
        for f in folders:
            p = Path(f).expanduser()
            j = Job(p)
            if not p.is_dir():
                j.status, j.message = "error", "Not a folder"
                errors.append(j.brief())
            else:
                try:
                    d, place, emp = naming.parse_folder_name(p.name)
                    j.date, j.place, j.employee = d, place, emp
                    self.jobs.append(j)
                    self.q.put(j)
                    added.append(j.brief())
                    continue
                except naming.FolderNameError as e:
                    j.status, j.message = "error", str(e)
                    errors.append(j.brief())
            self.jobs.append(j)
        self.broadcast("queue", self.queue_brief())
        return added, errors

    def enqueue_reprocess(self, day_ids):
        added = []
        con = db.connect()
        try:
            for did in day_ids:
                drow = db.day_row(con, did)
                if not drow:
                    continue
                folder_name = Path(drow["source_folder"]).name \
                    if drow["source_folder"] \
                    else f"{drow['date']}.{drow['place']}.{drow['employee']}"
                j = Job(folder_name, kind="reprocess", day_id=did)
                j.date, j.place, j.employee = \
                    drow["date"], drow["place"], drow["employee"]
                self.jobs.append(j)
                self.q.put(j)
                added.append(j.brief())
        finally:
            con.close()
        self.broadcast("queue", self.queue_brief())
        return added

    def queue_brief(self):
        return [j.brief() for j in self.jobs[-30:]]

    # ------------------------------------------------------------ prompts
    def ask(self, job, ptype, payload):
        pid = uuid.uuid4().hex[:8]
        with self.lock:
            self.pending_prompt = {"id": pid, "type": ptype,
                                   "payload": payload, "job_id": job.id,
                                   "job_name": job.name}
        job.status = "waiting"
        self.broadcast("prompt", self.pending_prompt)
        self.broadcast("queue", self.queue_brief())
        while pid not in self._answers:
            if job.cancel:
                with self.lock:
                    self.pending_prompt = None
                return {"_cancelled": True}
            self._answer_evt.wait(0.25)
            self._answer_evt.clear()
        with self.lock:
            self.pending_prompt = None
            data = self._answers.pop(pid)
        self.broadcast("prompt", None)
        return data

    def answer(self, prompt_id, data):
        self._answers[prompt_id] = data or {}
        self._answer_evt.set()

    # ------------------------------------------------------------ worker
    def _worker(self):
        while True:
            job = self.q.get()
            try:
                self._run_job(job)
            except Exception as e:
                job.status = "error"
                job.message = f"{type(e).__name__}: {e}"
            self.broadcast("job_done", job.brief())
            self.broadcast("queue", self.queue_brief())

    # ------------------------------------------------------------ the run
    def _run_job(self, job):
        cfg = self.cfg
        con = db.connect()
        db.backup_if_due()
        caf = None
        if shutil.which("caffeinate"):
            try:
                caf = subprocess.Popen(["caffeinate", "-i"])
            except Exception:
                caf = None
        try:
            if job.kind == "reprocess":
                self._run_reprocess(job, con, cfg)
            else:
                self._run_job_inner(job, con, cfg)
        finally:
            if caf:
                caf.terminate()
            con.close()

    def _run_job_inner(self, job, con, cfg):
        job.status = "scanning"
        self.broadcast("queue", self.queue_brief())

        # ---- registry checks (new ape / new place prompts)
        names = db.known_names(con)
        places = db.known_places(con)
        if names and job.employee not in names:
            ans = self.ask(job, "new_name",
                           {"value": job.employee, "known": names})
            if ans.get("_cancelled") or ans.get("action") == "cancel":
                job.status, job.message = "skipped", "Cancelled at name check"
                return
            if ans.get("action") == "map" and ans.get("map_to"):
                job.employee = ans["map_to"]
        if places and job.place not in places:
            ans = self.ask(job, "new_place",
                           {"value": job.place, "known": places})
            if ans.get("_cancelled") or ans.get("action") == "cancel":
                job.status, job.message = "skipped", "Cancelled at place check"
                return
            if ans.get("action") == "map" and ans.get("map_to"):
                job.place = ans["map_to"]

        date_iso = job.date.isoformat()
        existing = db.find_day(con, date_iso, job.place, job.employee)
        if existing:
            ans = self.ask(job, "duplicate_day",
                           {"date": date_iso, "place": job.place,
                            "employee": job.employee})
            if ans.get("_cancelled") or ans.get("action") != "replace":
                job.status, job.message = "skipped", "Day already in dataset"
                return

        # ---- phase 1: scan files + EXIF times
        files, skipped = [], 0
        for p in sorted(job.folder.iterdir()):
            if p.is_file() and p.suffix.lower() in naming.JPEG_EXTS:
                files.append(p)
            elif p.is_file() and not p.name.startswith("."):
                skipped += 1
        if not files:
            job.status, job.message = "error", "No JPEG files in folder"
            return

        scan = []
        missing_exif = 0
        for i, p in enumerate(files):
            tod, subsec, src = exifutil.read_time_of_day(p)
            if src in ("mtime", "none"):
                missing_exif += 1
            t = exifutil.combine(job.date, tod, subsec)
            _, seq = naming.filename_seq(p.name)
            scan.append({"path": p, "filename": p.name, "t": t, "seq": seq,
                         "src": src})
            if i % 100 == 0:
                job.message = f"Reading photo times {i + 1}/{len(files)}"
        scan.sort(key=lambda r: (r["t"], r["filename"]))
        deletions = naming.detect_deletions(
            [(r["filename"], r["t"]) for r in scan])

        # ---- phase 2: the heavy loop
        job.status = "processing"
        job.total = len(scan)
        job.message = ""
        engine = self.engine()
        tracker = SubjectTracker(cfg["face_match_threshold"])
        engager = Engager(config.engagement_params(cfg))
        photo_records = []
        t_start = time.time()

        decode_flag = (cv2.IMREAD_REDUCED_COLOR_2 if cfg.get("decode_reduced")
                       else cv2.IMREAD_COLOR)

        do_archive = bool(cfg.get("archive_enabled", True))
        arch_long = int(cfg.get("archive_long_edge", 1600))
        arch_q = int(cfg.get("archive_quality", 80))
        archive_entries = []

        for idx, rec in enumerate(scan):
            if job.cancel:
                job.status, job.message = "discarded", "Cancelled"
                return
            self.run_flag.wait()  # pause point

            raw = None
            try:
                raw = rec["path"].read_bytes()
            except Exception:
                raw = None
            img = (cv2.imdecode(np.frombuffer(raw, np.uint8), decode_flag)
                   if raw is not None else None)
            flags = []
            if rec["src"] in ("mtime", "none"):
                flags.append("no_exif_time")

            if do_archive and img is not None and raw is not None:
                try:
                    jxl = archive.encode_jxl(img, arch_long, arch_q)
                    jxl_name = Path(rec["filename"]).stem + ".jxl"
                    adir = archive.day_archive_dir(job.name)
                    adir.mkdir(parents=True, exist_ok=True)
                    (adir / jxl_name).write_bytes(jxl)
                    archive_entries.append({
                        "original_filename": rec["filename"], "seq": rec["seq"],
                        "exif_time": rec["t"].strftime("%H:%M:%S.%f"),
                        "exif_source": rec["src"], "sha256": archive.sha256_bytes(raw),
                        "jxl_filename": jxl_name, "jxl_bytes": len(jxl)})
                except Exception:
                    flags.append("archive_failed")

            if img is None:
                flags.append("decode_failed")
            record, observations, live = analyze_frame(
                engine, tracker, engager, idx, rec, img, flags)
            kind = record["kind"]
            photo_records.append(record)

            job.progress = idx + 1
            if (img is not None and cfg.get("preview_enabled")
                    and self.has_subscribers()):
                meta_now = tracker.finalize()
                banner = f"{rec['filename']}  {rec['t'].strftime('%H:%M:%S')}"
                jpg = annotate_preview(img, observations, meta_now, banner,
                                       kind, cfg.get("preview_max_width", 760))
                counts = engager.live_counts()
                rate = (idx + 1) / max(time.time() - t_start, 0.01)
                eta = (len(scan) - idx - 1) / max(rate, 0.01)
                self.broadcast("frame", {
                    "job_id": job.id, "i": idx + 1, "n": len(scan),
                    "img": base64.b64encode(jpg).decode("ascii"),
                    "filename": rec["filename"],
                    "time": rec["t"].strftime("%H:%M:%S"),
                    "kind": kind, "counts": counts,
                    "new": live["new_subjects"],
                    "warm_started": live["warm_started"],
                    "eta_s": int(eta), "rate": round(rate, 2)})
            elif idx % 25 == 0:
                self.broadcast("status", {"job": job.brief(),
                                          "counts": engager.live_counts()})

        # ---- wrap up analysis
        eng_final = engager.finalize()
        subj_meta = tracker.finalize()
        day_info = {"date": date_iso, "place": job.place,
                    "employee": job.employee,
                    "weekday": job.date.strftime("%A")}
        stats = compute_day_stats(photo_records, eng_final, subj_meta,
                                  deletions, day_info, skipped, missing_exif)

        # ---- money prompt (skippable) then commit Y/N
        ans = self.ask(job, "money", {"summary": _summary_card(stats)})
        if ans.get("_cancelled"):
            job.status, job.message = "discarded", "Cancelled"
            return
        money_cash = _to_float(ans.get("cash"))
        money_card = _to_float(ans.get("card"))

        ans = self.ask(job, "commit", {"summary": _summary_card(stats),
                                       "cash": money_cash,
                                       "card": money_card})
        if ans.get("_cancelled") or not ans.get("commit"):
            job.status, job.message = "discarded", "Not added to dataset"
            return

        job.status = "committing"
        day_record = build_day_record(
            date_iso, job.date.strftime("%A"), job.place, job.employee,
            str(job.folder), money_cash, money_card, stats,
            config.engagement_params(cfg), photo_records, eng_final,
            subj_meta, has_archive=bool(do_archive and archive_entries))
        day_id = db.commit_day(con, day_record)
        job.result_day_id = day_id

        if do_archive and archive_entries:
            try:
                archive.write_manifest(job.name, {
                    "folder": job.name, "date": date_iso, "place": job.place,
                    "employee": job.employee, "archive_long_edge": arch_long,
                    "archive_target_kb": int(cfg.get("archive_target_kb", 150)),
                    "archive_quality": arch_q, "app_version": APP_VERSION,
                    "count": len(archive_entries),
                    "archived_at": datetime.now().isoformat()},
                    archive_entries)
            except Exception:
                pass

        out = config.exports_dir() / f"{job.name}.xlsx"
        export_day(day_record, out)
        job.export_path = str(out)
        job.status = "done"
        job.message = f"Saved. Excel: {out.name}"
        self.broadcast("committed", {"job": job.brief(),
                                     "stats": _summary_card(stats)})

    def _run_reprocess(self, job, con, cfg):
        job.status = "processing"
        self.broadcast("queue", self.queue_brief())

        def prog(i, n):
            job.progress, job.total = i, n
            if i % 25 == 0 or i == n:
                self.broadcast("status", {"job": job.brief()})

        try:
            result = reprocess_day(con, job.day_id, self.engine(), cfg, progress=prog,
                                   cancel_check=lambda: job.cancel,
                                   pause_wait=self.run_flag.wait)
        except FileNotFoundError as e:
            job.status, job.message = "error", str(e)
            return
        if result is None:
            if job.cancel:
                job.status, job.message = "discarded", "Cancelled"
            else:
                job.status, job.message = "error", "Day not found"
            return
        stats, new_id = result
        job.result_day_id = new_id
        job.status = "done"
        job.message = "Reprocessed from archive"
        self.broadcast("committed", {"job": job.brief(),
                                     "stats": _summary_card(stats)})


# ------------------------------------------------------------------ helpers

def _to_float(v):
    try:
        if v in (None, ""):
            return None
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def _summary_card(st):
    return {"photos": st["photos_total"],
            "cold_events": st["cold_events"],
            "cold_persons": st["cold_persons"],
            "warm_persons": st["warm_persons"],
            "conversion": st["conversion"],
            "shoot_s": st["shoot_s"],
            "warm_dur_avg_s": st["warm_dur_avg_s"],
            "suspected_deletions": st["suspected_deletions"],
            "hot_streak": st["hot_streak"]}


def analyze_frame(engine, tracker, engager, idx, rec, img, flags):
    """Detection -> identity -> engagement for ONE decoded frame, shared by
    ingest and reprocess. `flags` is the caller's pre-collected flag list and
    is stored on the record as-is. Returns (photo_record, observations, live)."""
    observations = (engine.analyze(img, {"filename": rec["filename"]})
                    if img is not None else [])
    sids = []
    for obs in observations:
        if obs.accepted:
            sid = tracker.assign(obs)
            if sid is not None and sid not in sids:
                sids.append(sid)
    live = engager.step(idx, rec["t"], sids)
    detail = {"faces": [{
        "box": list(obs.box), "score": round(obs.score, 3),
        "blur": round(obs.blur, 1), "frac": round(obs.frac, 4),
        "sid": obs.sid, "reject": obs.reject_reason}
        for obs in observations], "exif_src": rec["src"]}
    record = {"filename": rec["filename"], "seq": rec["seq"], "t": rec["t"],
              "kind": live["kind"], "n_focus": len(sids),
              "n_rejected": sum(1 for o in observations if not o.accepted),
              "subjects": sids, "flags": flags, "detail": detail}
    return record, observations, live


def build_day_record(date_iso, weekday, place, employee, source_folder,
                     cash, card, stats, params, photo_records, eng_final,
                     subj_meta, has_archive=False):
    photos_out = [{**p, "t": p["t"].isoformat()} for p in photo_records]
    subjects_out = []
    for sid, s in sorted(eng_final["subjects"].items()):
        meta = subj_meta.get(sid, {})
        subjects_out.append({
            "local_id": sid,
            "gender": meta.get("gender"),
            "gender_conf": meta.get("gender_conf"),
            "age_bucket": meta.get("age_bucket"),
            "age_est": meta.get("age_est"),
            "photo_count": meta.get("photo_count"),
            "did_warm": s["did_warm"], "pitch_s": s["pitch_s"],
            "warm_sessions": s["warm_sessions"],
            "warm_photos": s["warm_photos"],
            "warm_duration_s": s["warm_duration_s"],
            "poses_est": s["poses_est"],
            "reapproached": s["reapproached"],
            "first_seen": s["first_seen"].isoformat(),
            "last_seen": s["last_seen"].isoformat()})
    engagements_out = []
    for e in eng_final["cold_events"]:
        engagements_out.append({
            "kind": "cold", "start": e["start"].isoformat(),
            "end": e["end"].isoformat(), "duration_s": e["duration_s"],
            "members": e["members"], "n_members": e["n_members"],
            "n_converted": e["n_converted"], "photos": e["photos"],
            "poses": None, "reapproach": e["reapproach"]})
    for w in eng_final["warm_sessions"]:
        engagements_out.append({
            "kind": "warm", "start": w["start"].isoformat(),
            "end": w["end"].isoformat(), "duration_s": w["duration_s"],
            "members": w["subject"], "n_members": 1, "n_converted": None,
            "photos": w["photos"], "poses": w["poses"], "reapproach": False})
    comp = fingerprint.current()
    return {"date": date_iso, "weekday": weekday, "place": place,
            "employee": employee, "source_folder": source_folder,
            "money_cash": cash, "money_card": card, "stats": stats,
            "params": params, "photos": photos_out,
            "subjects": subjects_out, "engagements": engagements_out,
            "app_version": APP_VERSION,
            "processing_fingerprint": fingerprint.fingerprint(comp),
            "fp_components": comp, "has_archive": bool(has_archive)}


# ------------------------------------------------------------------ recompute

def recompute_day(con, day_id, params):
    """Re-run engagement + stats over the stored per-photo data with new
    thresholds. No images needed; identities can't change (embeddings
    are gone by design) but all timing logic re-runs."""
    drow = db.day_row(con, day_id)
    if not drow:
        return None
    photos = db.day_photos(con, day_id)
    subs_meta_rows = db.day_subjects(con, day_id)
    subj_meta = {s["local_id"]: {"gender": s["gender"],
                                 "gender_conf": s["gender_conf"],
                                 "age_bucket": s["age_bucket"],
                                 "age_est": s["age_est"],
                                 "photo_count": s["photo_count"]}
                 for s in subs_meta_rows}

    plist = []
    for p in photos:
        plist.append({"i": p["id"], "t": datetime.fromisoformat(p["t"]),
                      "subjects": json.loads(p["subjects"] or "[]")})
    eng_final = analyze(plist, params)

    photo_records = []
    kinds_by_pid = []
    for p in photos:
        kind = eng_final["photo_kind"].get(p["id"], p["kind"])
        kinds_by_pid.append((p["id"], kind))
        photo_records.append({"filename": p["filename"], "seq": p["seq"],
                              "t": datetime.fromisoformat(p["t"]),
                              "kind": kind, "n_focus": p["n_focus"],
                              "n_rejected": p["n_rejected"],
                              "subjects": json.loads(p["subjects"] or "[]"),
                              "flags": json.loads(p["flags"] or "[]"),
                              "detail": json.loads(p["detail"] or "{}")})

    old_stats = json.loads(drow["stats_json"])
    deletions = {"suspected_deletions": old_stats.get("suspected_deletions", 0),
                 "gaps": old_stats.get("deletion_gaps", [])}
    day_info = {"date": drow["date"], "place": drow["place"],
                "employee": drow["employee"], "weekday": drow["weekday"]}
    stats = compute_day_stats(photo_records, eng_final, subj_meta, deletions,
                              day_info, old_stats.get("skipped_files", 0),
                              old_stats.get("missing_exif", 0))

    rec = build_day_record(drow["date"], drow["weekday"], drow["place"],
                           drow["employee"], drow["source_folder"],
                           drow["money_cash"], drow["money_card"], stats,
                           params, photo_records, eng_final, subj_meta,
                           has_archive=bool(drow["has_archive"]))
    db.replace_day_analysis(con, day_id, stats, params, kinds_by_pid,
                            rec["subjects"], rec["engagements"],
                            processing_fingerprint=rec["processing_fingerprint"],
                            fp_components=rec["fp_components"])

    # refresh the Excel export so the archive matches the dataset
    folder_name = Path(drow["source_folder"]).name if drow["source_folder"] \
        else f"{drow['date']}.{drow['place']}.{drow['employee']}"
    try:
        export_day(rec, config.exports_dir() / f"{folder_name}.xlsx")
    except Exception:
        pass
    return stats


# ------------------------------------------------------------------ comparability

def bring_current(state, con, enqueue_reprocess=True):
    """Route every stale day to the cheapest valid path so the dataset
    converges to one current fingerprint. Cheap recomputes always run inline
    (and re-stamp). Reprocess-class days are queued on the worker only when
    enqueue_reprocess is True (the settings-save preview passes False so it can
    prompt before launching hours of work). Photo-less model/detection-behind
    days are left legacy (excluded by agg)."""
    cur = fingerprint.current()
    cur_fp = fingerprint.fingerprint(cur)
    params = config.engagement_params(config.load_config())
    out = {"recomputed": 0, "reprocess_queued": 0, "reprocess_pending": 0,
           "legacy": 0, "current": 0}
    reprocess_ids = []
    for d in db.stale_days(con, cur_fp):
        stored = json.loads(d["fp_components"]) if d["fp_components"] else None
        decision = fingerprint.route(stored, cur, bool(d["has_archive"]))
        if decision == "recompute":
            try:
                recompute_day(con, d["id"], params)
                out["recomputed"] += 1
            except Exception:
                pass
        elif decision == "reprocess":
            reprocess_ids.append(d["id"])
        elif decision == "legacy":
            out["legacy"] += 1
        else:
            out["current"] += 1
    if reprocess_ids and enqueue_reprocess:
        state.enqueue_reprocess(reprocess_ids)
        out["reprocess_queued"] = len(reprocess_ids)
    else:
        out["reprocess_pending"] = len(reprocess_ids)
    return out


# ------------------------------------------------------------------ reprocess

def reprocess_day(con, day_id, engine, cfg, progress=None, cancel_check=None,
                  pause_wait=None):
    """Re-run the FULL face pipeline from the archived JXLs for one day.

    Unlike recompute_day (imageless, keeps identities), this re-decodes the
    archive and re-detects faces, so it produces fresh subject ids. Returns
    (stats, new_day_id); None if the day is missing. Raises FileNotFoundError
    if the day has no archive/manifest.
    cancel_check()/pause_wait() are optional callables for cooperative
    pause/cancel; on cancel the function returns None before committing."""
    drow = db.day_row(con, day_id)
    if not drow:
        return None
    folder_name = Path(drow["source_folder"]).name if drow["source_folder"] \
        else f"{drow['date']}.{drow['place']}.{drow['employee']}"
    man = archive.read_manifest(folder_name)
    if not man:
        raise FileNotFoundError(
            f"No archive/manifest for day {day_id} ({folder_name})")

    day = date.fromisoformat(drow["date"])
    scan = []
    for jxl_path, entry in archive.iter_archived(folder_name):
        tt = datetime.strptime(entry["exif_time"], "%H:%M:%S.%f").time()
        scan.append({"path": jxl_path, "filename": entry["original_filename"],
                     "t": datetime.combine(day, tt), "seq": entry["seq"],
                     "src": entry.get("exif_source", "exif")})
    scan.sort(key=lambda r: (r["t"], r["filename"]))
    deletions = naming.detect_deletions([(r["filename"], r["t"]) for r in scan])

    tracker = SubjectTracker(cfg["face_match_threshold"])
    engager = Engager(config.engagement_params(cfg))
    photo_records = []
    n = len(scan)
    for idx, rec in enumerate(scan):
        if pause_wait is not None:
            pause_wait()
        if cancel_check is not None and cancel_check():
            return None
        try:
            img = archive.decode_jxl(rec["path"])
        except Exception:
            img = None
        flags = [] if img is not None else ["decode_failed"]
        if rec["src"] in ("mtime", "none"):
            flags.append("no_exif_time")
        record, _obs, _live = analyze_frame(
            engine, tracker, engager, idx, rec, img, flags)
        photo_records.append(record)
        if progress:
            progress(idx + 1, n)

    eng_final = engager.finalize()
    subj_meta = tracker.finalize()
    day_info = {"date": drow["date"], "place": drow["place"],
                "employee": drow["employee"], "weekday": drow["weekday"]}
    old_stats = json.loads(drow["stats_json"])
    stats = compute_day_stats(photo_records, eng_final, subj_meta, deletions,
                              day_info, old_stats.get("skipped_files", 0), 0)
    rec_out = build_day_record(
        drow["date"], drow["weekday"], drow["place"], drow["employee"],
        drow["source_folder"], drow["money_cash"], drow["money_card"], stats,
        config.engagement_params(cfg), photo_records, eng_final, subj_meta,
        has_archive=True)
    new_id = db.commit_day(con, rec_out)
    try:
        export_day(rec_out, config.exports_dir() / f"{folder_name}.xlsx")
    except Exception:
        pass
    return stats, new_id
