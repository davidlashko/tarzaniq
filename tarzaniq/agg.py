"""Aggregations for the dashboard. Everything reads days.stats_json —
no photo re-scans, so even years of history render instantly.
"""

import json
from collections import defaultdict

from . import db

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]

RADAR_AXES = [
    ("hunting", "Hunting", "cold persons / shooting hr"),
    ("closing", "Closing", "cold -> warm conversion"),
    ("holding", "Holding", "avg warm shoot length"),
    ("hustle", "Hustle", "shooting time vs time on street"),
    ("volume", "Volume", "photos / shooting hr"),
]


def _stats(day):
    return json.loads(day["stats_json"])


def _safe(x, d=0.0):
    return d if x is None else x


def day_axes(st):
    shoot_h = st["shoot_s"] / 3600 if st["shoot_s"] else 0
    return {
        "hunting": (st["cold_persons"] / shoot_h) if shoot_h else None,
        "closing": st["conversion"],
        "holding": st["warm_dur_avg_s"],
        "hustle": (st["shoot_s"] / st["span_s"]) if st["span_s"] else None,
        "volume": (st["photos_total"] / shoot_h) if shoot_h else None,
    }


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _percentile_of(value, population):
    pop = sorted(x for x in population if x is not None)
    if value is None or not pop:
        return None
    below = sum(1 for x in pop if x <= value)
    return below / len(pop)


def employee_summaries(days):
    """Aggregate per-employee across a list of day rows."""
    by_emp = defaultdict(list)
    for d in days:
        by_emp[d["employee"]].append(d)
    out = {}
    for emp, rows in by_emp.items():
        sts = [_stats(d) for d in rows]
        cold_p = sum(s["cold_persons"] for s in sts)
        warm_p = sum(s["warm_persons"] for s in sts)
        shoot_s = sum(s["shoot_s"] for s in sts)
        span_s = sum(s["span_s"] for s in sts)
        photos = sum(s["photos_total"] for s in sts)
        shoot_h = shoot_s / 3600 if shoot_s else 0
        money = sum((_safe(d["money_cash"]) + _safe(d["money_card"]))
                    for d in rows)
        money_days = sum(1 for d in rows
                         if d["money_cash"] is not None
                         or d["money_card"] is not None)
        axes_daily = [day_axes(s) for s in sts]
        out[emp] = {
            "employee": emp, "days": len(rows),
            "photos": photos, "cold_persons": cold_p,
            "cold_events": sum(s["cold_events"] for s in sts),
            "warm_persons": warm_p,
            "conversion": (warm_p / cold_p) if cold_p else None,
            "cold_per_hr": (cold_p / shoot_h) if shoot_h else None,
            "warm_per_hr": (warm_p / shoot_h) if shoot_h else None,
            "photos_per_hr": (photos / shoot_h) if shoot_h else None,
            "shoot_h": shoot_h, "span_h": span_s / 3600,
            "hustle": (shoot_s / span_s) if span_s else None,
            "warm_dur_avg_s": _mean([s["warm_dur_avg_s"] for s in sts]),
            "pitch_avg_s": _mean([s["pitch_avg_s"] for s in sts]),
            "poses_avg": _mean([s["poses_avg"] for s in sts]),
            "hot_streak_best": max((s["hot_streak"] for s in sts), default=0),
            "suspected_deletions": sum(s["suspected_deletions"] for s in sts),
            "money": money if money_days else None,
            "money_days": money_days,
            "axes": {k: _mean([a[k] for a in axes_daily])
                     for k, _, _ in RADAR_AXES},
            "best_conv_day": max(
                ((s["conversion"], d["date"]) for s, d in zip(sts, rows)
                 if s["conversion"] is not None), default=(None, None)),
            "last_date": max(d["date"] for d in rows),
        }
    return out


def radar_percentiles(summaries):
    """Per employee: percentile of each axis vs the team."""
    pops = {k: [s["axes"][k] for s in summaries.values()]
            for k, _, _ in RADAR_AXES}
    out = {}
    for emp, s in summaries.items():
        out[emp] = {k: _percentile_of(s["axes"][k], pops[k])
                    for k, _, _ in RADAR_AXES}
    return out


def overview(con):
    days = db.all_days(con)
    sums = employee_summaries(days)
    pct = radar_percentiles(sums)
    sts = [_stats(d) for d in days]
    total = {
        "days": len(days),
        "employees": len(sums),
        "places": len({d["place"] for d in days}),
        "photos": sum(s["photos_total"] for s in sts),
        "cold_persons": sum(s["cold_persons"] for s in sts),
        "warm_persons": sum(s["warm_persons"] for s in sts),
        "shoot_h": sum(s["shoot_s"] for s in sts) / 3600,
        "money": sum(_safe(d["money_cash"]) + _safe(d["money_card"])
                     for d in days),
    }
    total["conversion"] = (total["warm_persons"] / total["cold_persons"]
                           if total["cold_persons"] else None)
    recent = []
    for d in sorted(days, key=lambda r: (r["date"], r["id"]), reverse=True)[:12]:
        s = _stats(d)
        recent.append({"id": d["id"], "date": d["date"], "place": d["place"],
                       "employee": d["employee"],
                       "conversion": s["conversion"],
                       "warm": s["warm_persons"], "cold": s["cold_persons"],
                       "photos": s["photos_total"]})
    records = _fun_records(days, sts)
    return {"total": total,
            "leaderboard": sorted(sums.values(),
                                  key=lambda s: _safe(s["conversion"], -1),
                                  reverse=True),
            "percentiles": pct, "recent": recent, "records": records}


def _fun_records(days, sts):
    if not days:
        return []
    recs = []
    pairs = list(zip(days, sts))

    def best(label, key, fmt, higher=True):
        vals = [(s.get(key), d) for d, s in pairs if s.get(key) is not None]
        if not vals:
            return
        v, d = (max if higher else min)(vals, key=lambda x: x[0])
        recs.append({"label": label, "value": fmt(v),
                     "who": d["employee"], "date": d["date"]})

    best("Best conversion day", "conversion", lambda v: f"{v*100:.0f}%")
    best("Hottest streak", "hot_streak", lambda v: f"{v} in a row")
    best("Most warm shoots in a day", "warm_persons", lambda v: str(v))
    best("Most subjects met in a day", "cold_persons", lambda v: str(v))
    best("Biggest day (photos)", "photos_total", lambda v: f"{v:,}")
    return recs[:5]


def employee_detail(con, name):
    days = db.all_days(con)
    mine = [d for d in days if d["employee"] == name]
    if not mine:
        return None
    sums = employee_summaries(days)
    pct = radar_percentiles(sums)
    me = sums[name]
    team = {k: _mean([s["axes"][k] for e, s in sums.items() if e != name])
            for k, _, _ in RADAR_AXES}

    series = []
    for d in sorted(mine, key=lambda r: r["date"]):
        s = _stats(d)
        series.append({"id": d["id"], "date": d["date"], "place": d["place"],
                       "conversion": s["conversion"],
                       "warm_per_hr": (s["warm_persons"] / (s["shoot_s"] / 3600))
                       if s["shoot_s"] else None,
                       "cold_per_hr": (s["cold_persons"] / (s["shoot_s"] / 3600))
                       if s["shoot_s"] else None,
                       "photos": s["photos_total"],
                       "warm": s["warm_persons"], "cold": s["cold_persons"],
                       "money": (_safe(d["money_cash"]) + _safe(d["money_card"]))
                       if (d["money_cash"] is not None
                           or d["money_card"] is not None) else None})

    dow, hours, demo = _patterns_for(mine)
    bests = _personal_bests(mine)
    return {"summary": me, "percentiles": pct.get(name, {}),
            "team_axes": team, "series": series, "dow": dow, "hours": hours,
            "demographics": demo, "bests": bests}


def _personal_bests(days):
    pairs = [(d, _stats(d)) for d in days]
    out = []

    def push(label, key, fmt):
        vals = [(s.get(key), d) for d, s in pairs if s.get(key) is not None]
        if vals:
            v, d = max(vals, key=lambda x: x[0])
            out.append({"label": label, "value": fmt(v), "date": d["date"]})

    push("Best conversion", "conversion", lambda v: f"{v*100:.0f}%")
    push("Most warm shoots", "warm_persons", str)
    push("Most subjects met", "cold_persons", str)
    push("Longest hot streak", "hot_streak", str)
    push("Most photos", "photos_total", lambda v: f"{v:,}")
    return out


def _patterns_for(days):
    """(day-of-week rows, hour rows, demographics) for a set of days."""
    dow_acc = {w: {"shoot_s": 0.0, "cold": 0, "warm": 0, "days": 0}
               for w in WEEKDAYS}
    hour_acc = defaultdict(lambda: {"shoot_s": 0.0, "cold": 0, "warm": 0})
    heat = defaultdict(lambda: {"shoot_s": 0.0, "warm": 0})
    gender = defaultdict(int)
    gender_w = defaultdict(int)
    age = defaultdict(int)
    age_w = defaultdict(int)
    for d in days:
        s = _stats(d)
        wd = s["weekday"]
        if wd in dow_acc:
            dow_acc[wd]["shoot_s"] += s["shoot_s"]
            dow_acc[wd]["cold"] += s["cold_persons"]
            dow_acc[wd]["warm"] += s["warm_persons"]
            dow_acc[wd]["days"] += 1
        for h in s.get("hourly", []):
            hour_acc[h["hour"]]["shoot_s"] += h["shoot_s"]
            hour_acc[h["hour"]]["cold"] += h["cold_p"]
            hour_acc[h["hour"]]["warm"] += h["warm_p"]
            heat[(wd, h["hour"])]["shoot_s"] += h["shoot_s"]
            heat[(wd, h["hour"])]["warm"] += h["warm_p"]
        for k, v in s.get("gender_count", {}).items():
            gender[k] += v
        for k, v in s.get("gender_warm", {}).items():
            gender_w[k] += v
        for k, v in s.get("age_count", {}).items():
            age[k] += v
        for k, v in s.get("age_warm", {}).items():
            age_w[k] += v

    dow = []
    for w in WEEKDAYS:
        a = dow_acc[w]
        h = a["shoot_s"] / 3600
        dow.append({"weekday": w, "days": a["days"],
                    "warm_per_hr": (a["warm"] / h) if h else None,
                    "cold_per_hr": (a["cold"] / h) if h else None,
                    "conversion": (a["warm"] / a["cold"]) if a["cold"] else None})
    hours = []
    for hr in sorted(hour_acc):
        a = hour_acc[hr]
        h = a["shoot_s"] / 3600
        hours.append({"hour": hr,
                      "warm_per_hr": (a["warm"] / h) if h else None,
                      "cold_per_hr": (a["cold"] / h) if h else None,
                      "conversion": (a["warm"] / a["cold"]) if a["cold"] else None,
                      "shoot_h": h})
    heat_rows = [{"weekday": w, "hour": hr,
                  "warm_per_hr": (v["warm"] / (v["shoot_s"] / 3600))
                  if v["shoot_s"] else None,
                  "shoot_h": v["shoot_s"] / 3600}
                 for (w, hr), v in heat.items()]
    demo = {"gender": dict(gender), "gender_warm": dict(gender_w),
            "age": dict(age), "age_warm": dict(age_w)}
    return dow, hours, {"demo": demo, "heat": heat_rows}


def patterns(con, employee=None, place=None):
    days = db.all_days(con, employee=employee or None, place=place or None)
    dow, hours, demo = _patterns_for(days)
    return {"dow": dow, "hours": hours, "heat": demo["heat"],
            "demographics": demo["demo"], "n_days": len(days)}


def places(con):
    days = db.all_days(con)
    by_place = defaultdict(list)
    for d in days:
        by_place[d["place"]].append(d)
    rows = []
    matrix = defaultdict(dict)
    for pl, rowsd in by_place.items():
        sts = [_stats(d) for d in rowsd]
        cold = sum(s["cold_persons"] for s in sts)
        warm = sum(s["warm_persons"] for s in sts)
        shoot_h = sum(s["shoot_s"] for s in sts) / 3600
        hours_best = _best_hour(sts)
        rows.append({"place": pl, "days": len(rowsd),
                     "employees": len({d['employee'] for d in rowsd}),
                     "cold_persons": cold, "warm_persons": warm,
                     "conversion": (warm / cold) if cold else None,
                     "warm_per_hr": (warm / shoot_h) if shoot_h else None,
                     "cold_per_hr": (cold / shoot_h) if shoot_h else None,
                     "best_hour": hours_best})
        by_emp = defaultdict(lambda: [0, 0])
        for d, s in zip(rowsd, sts):
            by_emp[d["employee"]][0] += s["cold_persons"]
            by_emp[d["employee"]][1] += s["warm_persons"]
        for emp, (c, w) in by_emp.items():
            matrix[emp][pl] = (w / c) if c else None
    rows.sort(key=lambda r: _safe(r["conversion"], -1), reverse=True)
    return {"places": rows, "matrix": {e: m for e, m in matrix.items()}}


def _best_hour(sts):
    acc = defaultdict(lambda: [0, 0.0])
    for s in sts:
        for h in s.get("hourly", []):
            acc[h["hour"]][0] += h["warm_p"]
            acc[h["hour"]][1] += h["shoot_s"]
    best, best_rate = None, -1
    for hr, (w, sec) in acc.items():
        if sec < 1800:  # need at least 30 min of data in that hour
            continue
        rate = w / (sec / 3600)
        if rate > best_rate:
            best, best_rate = hr, rate
    return {"hour": best, "warm_per_hr": best_rate if best is not None else None}


def day_detail(con, day_id):
    d = db.day_row(con, day_id)
    if not d:
        return None
    st = json.loads(d["stats_json"])
    engs = db.day_engagements(con, day_id)
    subs = db.day_subjects(con, day_id)
    blocks = []
    for e in engs:
        blocks.append({"kind": e["kind"], "start": e["start"],
                       "end": e["end"], "members": json.loads(e["members"])
                       if e["members"] else None,
                       "n_members": e["n_members"],
                       "n_converted": e["n_converted"],
                       "photos": e["photos"], "poses": e["poses"]})
    for b in st.get("deletion_gaps", [])[:50]:
        pass  # gaps shown in stats panel, not on timeline
    return {"day": {k: d[k] for k in ("id", "date", "weekday", "place",
                                      "employee", "money_cash", "money_card",
                                      "source_folder", "committed_at",
                                      "app_version")},
            "stats": st, "blocks": blocks,
            "subjects": subs,
            "params": json.loads(d["params_json"])}
