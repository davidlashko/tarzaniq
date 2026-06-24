"""The engagement engine. This is the brain of TarzanIQ.

Definitions (all thresholds configurable):

  COLD SHOOT   One approach event. The first photo(s) of one or more
               brand-new subjects, plus follow-up frames of that same
               group arriving less than `warm_gap_s` apart.
               Seven rapid candid frames of one person = ONE cold shoot.
               Two people in the frame = one cold shoot, two cold persons.

  WARM SHOOT   A subject reappearing `warm_gap_s` or more after their
               cold shoot ended (they said yes to the pitch). Counted
               PER PERSON: a group cold shoot where two members pose
               afterwards = 1 cold shoot, 2 warm shoots.

  RE-APPROACH  A subject reappearing after more than `max_pitch_minutes`
               is a brand-new cold approach (nobody pitches for ten
               minutes; you ran into them again).

  WARM SESSION A subject's warm photos, split wherever consecutive
               appearances are more than `warm_session_gap_minutes` apart.

  POSE (est.)  Within a warm session, bursts separated by pauses of
               `pose_gap_s` or more. A pause = repositioning = new pose.

  BREAK        Any gap of `break_minutes` or more between two photos.
               Subtracted from the shooting clock.

The engine is incremental: `step()` classifies each photo the moment it
is processed (so the live viewer can overlay COLD/WARM in real time) and
`finalize()` wraps everything into the day's structures. Classification
of a photo depends only on photos before it, so live labels and final
labels always agree.
"""


def _secs(td):
    return td.total_seconds()


class _ColdEvent:
    __slots__ = ("idx", "start", "end", "members", "photo_idxs",
                 "reapproach", "converted")

    def __init__(self, idx, t, members, photo_idx, reapproach=False):
        self.idx = idx
        self.start = t
        self.end = t
        self.members = set(members)
        self.photo_idxs = [photo_idx]
        self.reapproach = reapproach
        self.converted = set()


class Engager:
    def __init__(self, params):
        self.p = {
            "warm_gap": float(params["warm_gap_s"]),
            "break_s": float(params["break_minutes"]) * 60.0,
            "max_pitch": float(params["max_pitch_minutes"]) * 60.0,
            "session_gap": float(params["warm_session_gap_minutes"]) * 60.0,
            "pose_gap": float(params["pose_gap_s"]),
        }
        self.params = dict(params)
        self.state = {}
        self.cold_events = []
        self.current = None
        self.photo_kind = {}
        self.breaks = []
        self.prev_t = None
        self.times_all = []

    # ------------------------------------------------------------ step
    def step(self, photo_idx, t, subjects):
        """Feed photos in chronological order. Returns live info:
        {"kind", "new_subjects", "warm_started", "reapproached"}."""
        subs = list(subjects or [])

        if self.prev_t is not None and _secs(t - self.prev_t) >= self.p["break_s"]:
            self.breaks.append((self.prev_t, t))

        if (self.current is not None
                and _secs(t - self.current.end) >= self.p["warm_gap"]):
            self.current = None

        intro, cold_cont, warm_subs, warm_started = [], [], [], []
        for s in subs:
            st = self.state.get(s)
            if st is None:
                intro.append((s, False))
            elif st["phase"] == "warm":
                warm_subs.append(s)
            else:  # cold
                if self.current is not None and st["event"] is self.current:
                    cold_cont.append(s)
                else:
                    gap = _secs(t - st["event"].end)
                    if gap <= self.p["max_pitch"]:
                        warm_subs.append(s)
                        warm_started.append(s)
                        st["phase"] = "warm"
                        st["warm_times"] = []
                        st["pitch_s"] = gap
                        st["event"].converted.add(s)
                    else:
                        intro.append((s, True))

        if intro:
            if (self.current is not None
                    and _secs(t - self.current.end) < self.p["warm_gap"]):
                self.current.members.update(s for s, _ in intro)
                if self.current.photo_idxs[-1] != photo_idx:
                    self.current.photo_idxs.append(photo_idx)
                self.current.end = t
            else:
                self.current = _ColdEvent(len(self.cold_events), t,
                                          [s for s, _ in intro], photo_idx,
                                          reapproach=all(r for _, r in intro))
                self.cold_events.append(self.current)
            for s, reapp in intro:
                prev = self.state.get(s)
                self.state[s] = {
                    "phase": "cold", "last_t": t, "event": self.current,
                    "warm_times": [], "pitch_s": None,
                    "events": (prev["events"] if prev else []) + [self.current.idx],
                    "first_t": prev["first_t"] if prev else t,
                    "reapproached": reapp or bool(prev and prev.get("reapproached")),
                }

        if cold_cont and self.current is not None:
            self.current.end = t
            if self.current.photo_idxs[-1] != photo_idx:
                self.current.photo_idxs.append(photo_idx)
            for s in cold_cont:
                self.state[s]["last_t"] = t

        for s in warm_subs:
            st = self.state[s]
            st["warm_times"].append(t)
            st["last_t"] = t

        if not subs:
            kind = "air"
        elif (intro or cold_cont) and warm_subs:
            kind = "mixed"
        elif intro or cold_cont:
            kind = "cold"
        else:
            kind = "warm"
        self.photo_kind[photo_idx] = kind
        self.prev_t = t
        self.times_all.append(t)

        return {"kind": kind,
                "new_subjects": [s for s, _ in intro],
                "warm_started": warm_started,
                "reapproached": [s for s, r in intro if r]}

    # ------------------------------------------------------------ live HUD
    def live_counts(self):
        warm = sum(1 for st in self.state.values() if st["phase"] == "warm")
        return {"cold_events": len(self.cold_events),
                "cold_persons": len(self.state),
                "warm_persons": warm}

    # ------------------------------------------------------------ finalize
    def finalize(self):
        subjects, warm_sessions = {}, []
        for sid, st in self.state.items():
            times = st["warm_times"]
            sessions = []
            if times:
                cur = [times[0]]
                for a, b in zip(times, times[1:]):
                    if _secs(b - a) > self.p["session_gap"]:
                        sessions.append(cur)
                        cur = [b]
                    else:
                        cur.append(b)
                sessions.append(cur)

            sess_rows, poses_total, warm_dur = [], 0, 0.0
            for ts in sessions:
                poses = 1
                for a, b in zip(ts, ts[1:]):
                    if _secs(b - a) >= self.p["pose_gap"]:
                        poses += 1
                dur = _secs(ts[-1] - ts[0])
                poses_total += poses
                warm_dur += dur
                row = {"subject": sid, "start": ts[0], "end": ts[-1],
                       "photos": len(ts), "poses": poses, "duration_s": dur}
                sess_rows.append(row)
                warm_sessions.append(row)

            subjects[sid] = {
                "id": sid,
                "first_seen": st["first_t"],
                "last_seen": st["last_t"],
                "did_warm": st["phase"] == "warm",
                "pitch_s": st["pitch_s"],
                "cold_events": st["events"],
                "reapproached": bool(st.get("reapproached")),
                "warm_sessions": len(sess_rows),
                "warm_photos": len(times),
                "warm_duration_s": warm_dur,
                "poses_est": poses_total if times else 0,
            }

        cold_rows = [{
            "idx": e.idx, "start": e.start, "end": e.end,
            "members": sorted(e.members), "n_members": len(e.members),
            "n_converted": len(e.converted), "photos": len(e.photo_idxs),
            "reapproach": e.reapproach,
            "duration_s": _secs(e.end - e.start),
        } for e in self.cold_events]

        hunting = []
        for e in cold_rows:
            prevs = [t for t in self.times_all if t < e["start"]]
            if not prevs:
                continue
            gap = _secs(e["start"] - prevs[-1])
            if 0 < gap < self.p["break_s"]:
                hunting.append(gap)

        return {
            "subjects": subjects,
            "cold_events": cold_rows,
            "warm_sessions": sorted(warm_sessions, key=lambda r: r["start"]),
            "photo_kind": self.photo_kind,
            "breaks": [{"start": a, "end": b, "duration_s": _secs(b - a)}
                       for a, b in self.breaks],
            "hunting_s": hunting,
            "params": self.params,
        }


def analyze(photos, params):
    """Batch convenience wrapper: photos = [{"i", "t", "subjects"}], sorted
    or not (we sort). Used for recomputing stored days after threshold
    changes — identical logic to the live path by construction."""
    eng = Engager(params)
    for p in sorted(photos, key=lambda x: x["t"]):
        eng.step(p["i"], p["t"], p.get("subjects") or [])
    return eng.finalize()
