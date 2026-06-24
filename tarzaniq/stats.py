"""Turn raw engagement structures into the full day stat sheet.

Everything the dashboard or Excel ever shows comes out of here, so old
days can be recomputed if thresholds change (the per-photo subject
assignments are kept in the DB; only timing logic re-runs).
"""

from collections import Counter
from datetime import datetime

AGE_BUCKETS = ["0-2", "4-6", "8-12", "15-20", "25-32", "38-43", "48-53", "60+"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _merge_intervals(rows):
    ivs = sorted((r["start"], r["end"]) for r in rows)
    out = []
    for s, e in ivs:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def compute_day_stats(photos, eng, subjects_meta, deletions, day_info,
                      skipped_files=0, missing_exif=0):
    """photos: pipeline photo records (dicts with t, kind, n_focus, ...)
       eng: engagements.analyze() output
       subjects_meta: {sid: {"gender","age_bucket","age_est","photo_count"}}
       day_info: {"date","place","employee","weekday"}
    """
    subs = eng["subjects"]
    colds = eng["cold_events"]
    sessions = eng["warm_sessions"]
    breaks = eng["breaks"]

    n_photos = len(photos)
    times = sorted(p["t"] for p in photos) if photos else []
    first_t, last_t = (times[0], times[-1]) if times else (None, None)
    span_s = (last_t - first_t).total_seconds() if times else 0.0
    break_s = sum(b["duration_s"] for b in breaks)
    shoot_s = max(span_s - break_s, 0.0)
    shoot_h = shoot_s / 3600.0 if shoot_s > 0 else 0.0

    cold_persons = len(subs)
    warm_persons = sum(1 for s in subs.values() if s["did_warm"])
    n_cold_events = len(colds)
    conv = (warm_persons / cold_persons) if cold_persons else None

    solo = [e for e in colds if e["n_members"] == 1]
    group = [e for e in colds if e["n_members"] >= 2]
    solo_members = sum(e["n_members"] for e in solo)
    solo_conv_n = sum(e["n_converted"] for e in solo)
    group_members = sum(e["n_members"] for e in group)
    group_conv_n = sum(e["n_converted"] for e in group)

    pitches = [s["pitch_s"] for s in subs.values() if s["pitch_s"] is not None]
    warm_durs = [s["warm_duration_s"] for s in subs.values() if s["did_warm"]]
    warm_photo_counts = [s["warm_photos"] for s in subs.values() if s["did_warm"]]
    poses = [s["poses_est"] for s in subs.values() if s["did_warm"]]
    warm_time_union = sum((e - s).total_seconds()
                          for s, e in _merge_intervals(sessions)) if sessions else 0.0

    # dry spell: longest stretch between consecutive cold-event starts,
    # with break time inside that window subtracted
    dry = 0.0
    starts = [e["start"] for e in colds]
    for a, b in zip(starts, starts[1:]):
        window = (b - a).total_seconds()
        inside = sum(min(b, br["end"]).timestamp() - max(a, br["start"]).timestamp()
                     for br in breaks
                     if br["end"] > a and br["start"] < b)
        dry = max(dry, window - max(inside, 0.0))

    # hot streak: consecutive cold events with at least one conversion
    streak = best_streak = 0
    for e in colds:
        streak = streak + 1 if e["n_converted"] > 0 else 0
        best_streak = max(best_streak, streak)

    # hourly buckets (hour of day -> activity)
    hourly = {}
    if times:
        # shooting minutes attributed per hour bucket via photo timeline
        prev = None
        for t in times:
            if prev is not None:
                gap = (t - prev).total_seconds()
                if gap < eng["params"]["break_minutes"] * 60:
                    # walk the gap across hour boundaries
                    cur = prev
                    while cur < t:
                        hour_end = cur.replace(minute=59, second=59, microsecond=999999)
                        seg_end = min(t, hour_end)
                        h = cur.hour
                        hourly.setdefault(h, {"shoot_s": 0.0, "cold_p": 0, "warm_p": 0})
                        hourly[h]["shoot_s"] += (seg_end - cur).total_seconds()
                        cur = seg_end
                        if cur == hour_end:
                            cur = hour_end.replace(minute=0, second=0, microsecond=0)
                            cur = cur.replace(hour=(h + 1) % 24)
                            if h == 23:
                                break
            prev = t
    for e in colds:
        h = e["start"].hour
        hourly.setdefault(h, {"shoot_s": 0.0, "cold_p": 0, "warm_p": 0})
        hourly[h]["cold_p"] += e["n_members"]
    for s in subs.values():
        if s["did_warm"]:
            # attribute to the hour their warm shoot began
            first_warm = None
            for sess in sessions:
                if sess["subject"] == s["id"]:
                    first_warm = sess["start"]
                    break
            if first_warm is not None:
                h = first_warm.hour
                hourly.setdefault(h, {"shoot_s": 0.0, "cold_p": 0, "warm_p": 0})
                hourly[h]["warm_p"] += 1
    hourly_rows = [{"hour": h, **v} for h, v in sorted(hourly.items())]

    # demographics
    gender_count = Counter()
    age_count = Counter()
    gender_warm = Counter()
    age_warm = Counter()
    for sid, s in subs.items():
        meta = subjects_meta.get(sid, {})
        g = meta.get("gender") or "unknown"
        a = meta.get("age_bucket") or "unknown"
        gender_count[g] += 1
        age_count[a] += 1
        if s["did_warm"]:
            gender_warm[g] += 1
            age_warm[a] += 1

    focus_counts = Counter(p.get("n_focus", 0) for p in photos)
    photos_with_focus = sum(c for n, c in focus_counts.items() if n > 0)
    faces_total = sum(n * c for n, c in focus_counts.items())

    kinds = Counter(p.get("kind", "?") for p in photos)

    stats = {
        "stats_version": 2,
        # day
        "date": day_info["date"], "weekday": day_info["weekday"],
        "place": day_info["place"], "employee": day_info["employee"],
        "photos_total": n_photos,
        "photos_focus": photos_with_focus,
        "photos_air": kinds.get("air", 0),
        "photos_cold": kinds.get("cold", 0) + kinds.get("mixed", 0),
        "photos_warm": kinds.get("warm", 0) + kinds.get("mixed", 0),
        "skipped_files": skipped_files,
        "missing_exif": missing_exif,
        "suspected_deletions": deletions.get("suspected_deletions", 0),
        "deletion_gaps": deletions.get("gaps", []),
        "first_shot": first_t.isoformat() if first_t else None,
        "last_shot": last_t.isoformat() if last_t else None,
        "span_s": span_s, "shoot_s": shoot_s, "break_s": break_s,
        "breaks_n": len(breaks),
        "breaks": [{"start": b["start"].isoformat(),
                    "end": b["end"].isoformat(),
                    "duration_s": b["duration_s"]} for b in breaks],
        # hunt
        "cold_events": n_cold_events,
        "cold_persons": cold_persons,
        "cold_per_hr": (cold_persons / shoot_h) if shoot_h else None,
        "cold_events_per_hr": (n_cold_events / shoot_h) if shoot_h else None,
        "avg_group_size": (sum(e["n_members"] for e in colds) / n_cold_events)
                          if n_cold_events else None,
        "pct_group_approaches": (len(group) / n_cold_events) if n_cold_events else None,
        "hunting_avg_s": _mean(eng["hunting_s"]),
        "dry_spell_s": dry,
        # close
        "warm_persons": warm_persons,
        "warm_per_hr": (warm_persons / shoot_h) if shoot_h else None,
        "conversion": conv,
        "pitch_avg_s": _mean(pitches),
        "solo_conv": (solo_conv_n / solo_members) if solo_members else None,
        "group_conv": (group_conv_n / group_members) if group_members else None,
        "hot_streak": best_streak,
        # hold
        "warm_sessions_n": len(sessions),
        "warm_dur_avg_s": _mean(warm_durs),
        "warm_photos_avg": _mean(warm_photo_counts),
        "poses_avg": _mean(poses),
        "warm_time_total_s": warm_time_union,
        # rates
        "photos_per_hr": (n_photos / shoot_h) if shoot_h else None,
        # people
        "gender_count": dict(gender_count),
        "gender_warm": dict(gender_warm),
        "age_count": dict(age_count),
        "age_warm": dict(age_warm),
        "avg_faces_in_frame": (faces_total / photos_with_focus)
                              if photos_with_focus else None,
        "focus_count_dist": {str(k): v for k, v in sorted(focus_counts.items())},
        "hourly": hourly_rows,
        "reapproaches": sum(1 for s in subs.values() if s["reapproached"]),
    }
    return stats


def fmt_dur(seconds):
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"
