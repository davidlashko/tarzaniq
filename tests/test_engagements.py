"""Engagement engine spec tests. Run: python3 tests/test_engagements.py"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tarzaniq.engagements import analyze  # noqa: E402

P = {"warm_gap_s": 5, "break_minutes": 20, "max_pitch_minutes": 10,
     "warm_session_gap_minutes": 10, "pose_gap_s": 8}

T0 = datetime(2026, 6, 7, 10, 0, 0)


def ph(i, secs, subs):
    return {"i": i, "t": T0 + timedelta(seconds=secs), "subjects": subs}


def run(photos):
    return analyze(photos, P)


def test_basic_cold_then_warm():
    r = run([ph(0, 0, [1]), ph(1, 30, [1]), ph(2, 33, [1])])
    assert len(r["cold_events"]) == 1
    s = r["subjects"][1]
    assert s["did_warm"] and abs(s["pitch_s"] - 30) < 0.01
    assert r["photo_kind"] == {0: "cold", 1: "warm", 2: "warm"}
    sess = r["warm_sessions"]
    assert len(sess) == 1 and sess[0]["photos"] == 2 and sess[0]["poses"] == 1


def test_seven_rapid_pics_one_cold_no_warm():
    photos = [ph(i, i * 2, [1]) for i in range(7)]  # gaps of 2s < warm_gap
    r = run(photos)
    assert len(r["cold_events"]) == 1
    assert r["cold_events"][0]["photos"] == 7
    assert not r["subjects"][1]["did_warm"]
    assert all(k == "cold" for k in r["photo_kind"].values())


def test_group_two_cold_two_warm():
    # spec: 2 people in cold frame, both pose later = 1 cold, 2 warm
    r = run([ph(0, 0, [1, 2]), ph(1, 2, [1, 2]),
             ph(2, 40, [1, 2]), ph(3, 44, [1, 2])])
    assert len(r["cold_events"]) == 1
    e = r["cold_events"][0]
    assert e["n_members"] == 2 and e["n_converted"] == 2
    assert r["subjects"][1]["did_warm"] and r["subjects"][2]["did_warm"]


def test_group_partial_conversion():
    # 3 approached together, only #2 poses
    r = run([ph(0, 0, [1, 2, 3]), ph(1, 25, [2]), ph(2, 28, [2])])
    e = r["cold_events"][0]
    assert e["n_members"] == 3 and e["n_converted"] == 1
    warm = [s for s in r["subjects"].values() if s["did_warm"]]
    assert len(warm) == 1 and warm[0]["id"] == 2


def test_group_grows_within_gap():
    # second person enters the candid 3s in -> same cold event
    r = run([ph(0, 0, [1]), ph(1, 3, [1, 2])])
    assert len(r["cold_events"]) == 1
    assert r["cold_events"][0]["n_members"] == 2


def test_separate_cold_events():
    r = run([ph(0, 0, [1]), ph(1, 10, [2])])
    assert len(r["cold_events"]) == 2


def test_reapproach_after_max_pitch():
    # subject returns 11 min later -> NEW cold approach, not warm
    r = run([ph(0, 0, [1]), ph(1, 11 * 60, [1]), ph(2, 11 * 60 + 30, [1])])
    assert len(r["cold_events"]) == 2
    s = r["subjects"][1]
    assert s["reapproached"]
    assert s["did_warm"] and abs(s["pitch_s"] - 30) < 0.01
    # conversion belongs to the SECOND event
    assert r["cold_events"][0]["n_converted"] == 0
    assert r["cold_events"][1]["n_converted"] == 1


def test_warm_sessions_split_and_poses():
    # warm at 30s..50s with a 9s pause (2 poses), then again 20 min later
    photos = [ph(0, 0, [1]),
              ph(1, 30, [1]), ph(2, 33, [1]), ph(3, 42, [1]), ph(4, 45, [1]),
              ph(5, 30 + 20 * 60, [1]), ph(6, 33 + 20 * 60, [1])]
    r = run(photos)
    s = r["subjects"][1]
    assert s["warm_sessions"] == 2
    sess = [x for x in r["warm_sessions"] if x["subject"] == 1]
    assert sess[0]["poses"] == 2          # 9s gap >= pose_gap of 8
    assert s["poses_est"] == 3            # 2 + 1
    assert s["warm_photos"] == 6


def test_break_detection():
    photos = [ph(0, 0, [1]), ph(1, 25 * 60, [2])]
    r = run(photos)
    assert len(r["breaks"]) == 1
    assert abs(r["breaks"][0]["duration_s"] - 25 * 60) < 0.01


def test_hunting_excludes_breaks():
    # event2 right after a 25-min break -> no hunting sample for it
    photos = [ph(0, 0, [1]), ph(1, 60, [2]), ph(2, 60 + 25 * 60, [3])]
    r = run(photos)
    assert len(r["hunting_s"]) == 1
    assert abs(r["hunting_s"][0] - 60) < 0.01


def test_air_shots_dont_extend_cold():
    # air frame at 2s, subject returns at 8s (>=5s from cold end) -> warm
    r = run([ph(0, 0, [1]), ph(1, 2, []), ph(2, 8, [1])])
    assert r["photo_kind"][1] == "air"
    assert r["subjects"][1]["did_warm"]
    assert abs(r["subjects"][1]["pitch_s"] - 8) < 0.01


def test_mixed_frame():
    # subject 1 warm while subject 2 is introduced in the same frame
    r = run([ph(0, 0, [1]), ph(1, 30, [1, 2])])
    assert r["photo_kind"][1] == "mixed"
    assert len(r["cold_events"]) == 2
    assert r["subjects"][1]["did_warm"]
    assert not r["subjects"][2]["did_warm"]


def test_incremental_matches_batch():
    from tarzaniq.engagements import Engager
    photos = [ph(0, 0, [1, 2]), ph(1, 2, [1, 2]), ph(2, 9, [1]),
              ph(3, 14, [1, 2]), ph(4, 200, [3]), ph(5, 230, [3]),
              ph(6, 26 * 60, [1])]
    batch = analyze(photos, P)
    eng = Engager(P)
    for p in photos:
        eng.step(p["i"], p["t"], p["subjects"])
    inc = eng.finalize()
    assert batch["photo_kind"] == inc["photo_kind"]
    assert len(batch["cold_events"]) == len(inc["cold_events"])
    assert {k: v["did_warm"] for k, v in batch["subjects"].items()} == \
           {k: v["did_warm"] for k, v in inc["subjects"].items()}


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
            except Exception as e:
                fails += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print("ALL GREEN" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
