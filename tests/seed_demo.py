"""Seed a demo database with varied days — used by the DOM smoke test.
Usage: TARZANIQ_DATA=/some/dir python3 tests/seed_demo.py
"""
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tarzaniq import config, db  # noqa: E402
from tarzaniq.engagements import analyze  # noqa: E402
from tarzaniq.stats import compute_day_stats, AGE_BUCKETS  # noqa: E402
from tarzaniq.pipeline import build_day_record  # noqa: E402
from tarzaniq.excelio import export_day  # noqa: E402

rng = random.Random(7)


def synth_day(d: date, place, emp, skill):
    """skill 0..1 drives conversion + pace. Returns committed day id."""
    t = datetime(d.year, d.month, d.day, rng.choice([9, 10, 11, 16]), 0, 0)
    photos = []
    sid = 0
    i = 0
    end_by = t + timedelta(hours=rng.uniform(4.5, 7))
    genders, ages = {}, {}
    while t < end_by:
        # hunt for the next mark
        t += timedelta(seconds=rng.uniform(40, 420) * (1.3 - skill * 0.5))
        if rng.random() < 0.07:  # a real break
            t += timedelta(minutes=rng.uniform(22, 50))
        group = 1 + (rng.random() < 0.22)
        members = list(range(sid, sid + group))
        sid += group
        for m in members:
            genders[m] = rng.choice(["M", "M", "F", "F", "unknown"])
            ages[m] = rng.choice(AGE_BUCKETS[2:7])
        # candid burst
        for _ in range(rng.randint(1, 5)):
            photos.append({"i": i, "t": t, "subjects": members}); i += 1
            t += timedelta(seconds=rng.uniform(0.4, 2.5))
        # occasional air shot
        if rng.random() < 0.18:
            t += timedelta(seconds=rng.uniform(3, 12))
            photos.append({"i": i, "t": t, "subjects": []}); i += 1
        # conversion?
        for m in members:
            if rng.random() < (0.18 + skill * 0.5):
                tw = t + timedelta(seconds=rng.uniform(8, 240))
                for _ in range(rng.randint(2, 9)):
                    photos.append({"i": i, "t": tw, "subjects": [m]}); i += 1
                    tw += timedelta(seconds=rng.uniform(0.7, 9))
                t = max(t, tw)
    photos.sort(key=lambda p: p["t"])
    for n, p in enumerate(photos):
        p["i"] = n

    params = config.engagement_params(config.load_config())
    eng = analyze(photos, params)
    subj_meta = {m: {"gender": genders.get(m), "gender_conf": 0.8,
                     "age_bucket": ages.get(m),
                     "age_est": 30.0, "photo_count":
                     sum(1 for p in photos if m in p["subjects"])}
                 for m in eng["subjects"]}
    precs = [{"filename": f"DSC{n+1:04d}.JPG", "seq": n + 1, "t": p["t"],
              "kind": eng["photo_kind"][p["i"]],
              "n_focus": len(p["subjects"]), "n_rejected": 0,
              "subjects": p["subjects"], "flags": [], "detail": {}}
             for n, p in enumerate(photos)]
    day_info = {"date": d.isoformat(), "place": place, "employee": emp,
                "weekday": d.strftime("%A")}
    stats = compute_day_stats(precs, eng, subj_meta,
                              {"suspected_deletions": rng.randint(0, 4),
                               "gaps": []}, day_info, 0, 0)
    cash = round(rng.uniform(800, 4000), 0) if rng.random() < 0.8 else None
    card = round(rng.uniform(0, 2500), 0) if rng.random() < 0.6 else None
    rec = build_day_record(d.isoformat(), d.strftime("%A"), place, emp,
                           f"/Volumes/SD/{d.strftime('%y.%m.%d')}.{place}.{emp}",
                           cash, card, stats, params, precs, eng, subj_meta)
    con = db.connect()
    day_id = db.commit_day(con, rec)
    export_day(rec, config.exports_dir() /
               f"{d.strftime('%y.%m.%d')}.{place}.{emp}.xlsx")
    con.close()
    return day_id


def main():
    apes = [("Marko", 0.8), ("Ana", 0.55), ("Petar", 0.3)]
    places = ["CityPark", "OldBazaar", "Riverside"]
    d0 = date(2026, 5, 18)
    n = 0
    for k in range(14):
        d = d0 + timedelta(days=k)
        for emp, skill in apes:
            if rng.random() < 0.6:
                pl = rng.choice(places)
                synth_day(d, pl, emp, skill + rng.uniform(-0.12, 0.12))
                n += 1
    print(f"seeded {n} days into {config.data_dir()}")


if __name__ == "__main__":
    main()
