"""Local web server. Binds 127.0.0.1 only — nothing leaves the laptop.

Run:  python -m tarzaniq.server
"""

import json
import platform
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)

from . import APP_NAME, APP_VERSION, APP_CODENAME, DEFAULT_PORT, config, db
from . import agg
from .pipeline import AppState, recompute_day

STATIC = Path(__file__).parent / "static"

app = Flask(APP_NAME, static_folder=str(STATIC), static_url_path="/static")
state = None  # set in main() / create()


def create(engine_factory=None):
    global state
    if state is None:
        state = AppState(engine_factory=engine_factory)
    return app


# ------------------------------------------------------------------ pages

@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/favicon.ico")
def favicon():
    p = STATIC / "img" / "favicon.png"
    if p.exists():
        return send_from_directory(STATIC / "img", "favicon.png")
    return ("", 404)


@app.route("/api/ping")
def ping():
    return jsonify({"app": APP_NAME, "version": APP_VERSION,
                    "codename": APP_CODENAME})


# ------------------------------------------------------------------ process

@app.route("/api/enqueue", methods=["POST"])
def enqueue():
    data = request.get_json(force=True, silent=True) or {}
    folders = data.get("folders") or []
    added, errors = state.enqueue(folders)
    return jsonify({"added": added, "errors": errors})


@app.route("/api/state")
def api_state():
    return jsonify({"queue": state.queue_brief(),
                    "prompt": state.pending_prompt,
                    "paused": not state.run_flag.is_set(),
                    "config": state.cfg,
                    "version": APP_VERSION})


@app.route("/api/process/pause", methods=["POST"])
def pause():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("paused"):
        state.run_flag.clear()
    else:
        state.run_flag.set()
    state.broadcast("paused", {"paused": not state.run_flag.is_set()})
    return jsonify({"paused": not state.run_flag.is_set()})


@app.route("/api/process/cancel", methods=["POST"])
def cancel():
    data = request.get_json(force=True, silent=True) or {}
    jid = data.get("job_id")
    for j in state.jobs:
        if j.id == jid and j.status in ("queued", "scanning", "processing",
                                        "waiting"):
            j.cancel = True
    state.run_flag.set()
    return jsonify({"ok": True})


@app.route("/api/prompt/answer", methods=["POST"])
def prompt_answer():
    data = request.get_json(force=True, silent=True) or {}
    pid = data.pop("id", None)
    if not pid:
        return jsonify({"ok": False}), 400
    state.answer(pid, data)
    return jsonify({"ok": True})


@app.route("/api/process/stream")
def stream():
    q = state.subscribe()

    def gen():
        hello = {"queue": state.queue_brief(), "prompt": state.pending_prompt,
                 "paused": not state.run_flag.is_set()}
        yield f"event: hello\ndata: {json.dumps(hello)}\n\n"
        try:
            while True:
                try:
                    event, data = q.get(timeout=20)
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except Exception:
                    yield "event: ka\ndata: {}\n\n"  # keep-alive
        finally:
            state.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/pickfolder", methods=["POST"])
def pickfolder():
    """Native macOS folder picker (multi-select) via osascript."""
    if platform.system() != "Darwin":
        return jsonify({"folders": [], "error": "Picker is macOS-only"})
    script = ('set fs to choose folder with prompt '
              '"Pick day folder(s) — YY.MM.DD.Place.Name" '
              'with multiple selections allowed\n'
              'set out to ""\n'
              'repeat with f in fs\n'
              'set out to out & POSIX path of f & "\\n"\n'
              'end repeat\n'
              'return out')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=300)
        folders = [ln.strip().rstrip("/") for ln in r.stdout.splitlines()
                   if ln.strip()]
        return jsonify({"folders": folders})
    except Exception as e:
        return jsonify({"folders": [], "error": str(e)})


# ------------------------------------------------------------------ data

@app.route("/api/overview")
def api_overview():
    con = db.connect()
    try:
        return jsonify(agg.overview(con))
    finally:
        con.close()


@app.route("/api/employee/<name>")
def api_employee(name):
    con = db.connect()
    try:
        out = agg.employee_detail(con, name)
        if out is None:
            return jsonify({"error": "no such ape"}), 404
        return jsonify(out)
    finally:
        con.close()


@app.route("/api/places")
def api_places():
    con = db.connect()
    try:
        return jsonify(agg.places(con))
    finally:
        con.close()


@app.route("/api/patterns")
def api_patterns():
    con = db.connect()
    try:
        return jsonify(agg.patterns(con,
                                    employee=request.args.get("employee"),
                                    place=request.args.get("place")))
    finally:
        con.close()


@app.route("/api/day/<int:day_id>")
def api_day(day_id):
    con = db.connect()
    try:
        out = agg.day_detail(con, day_id)
        if out is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(out)
    finally:
        con.close()


@app.route("/api/day/<int:day_id>", methods=["DELETE"])
def api_day_delete(day_id):
    con = db.connect()
    try:
        db.delete_day(con, day_id)
        return jsonify({"ok": True})
    finally:
        con.close()


@app.route("/api/day/<int:day_id>/money", methods=["POST"])
def api_day_money(day_id):
    data = request.get_json(force=True, silent=True) or {}

    def f(v):
        try:
            return None if v in (None, "") else float(str(v).replace(",", "."))
        except Exception:
            return None
    con = db.connect()
    try:
        db.update_money(con, day_id, f(data.get("cash")), f(data.get("card")))
        return jsonify({"ok": True})
    finally:
        con.close()


@app.route("/api/export/<int:day_id>")
def api_export(day_id):
    con = db.connect()
    try:
        d = db.day_row(con, day_id)
        if not d:
            return jsonify({"error": "not found"}), 404
        folder = Path(d["source_folder"]).name if d["source_folder"] else \
            f"{d['date']}.{d['place']}.{d['employee']}"
        p = config.exports_dir() / f"{folder}.xlsx"
        if not p.exists():
            from .pipeline import recompute_day as _r
            _r(con, day_id, json.loads(d["params_json"]))
        if not p.exists():
            return jsonify({"error": "export missing"}), 404
        return send_file(p, as_attachment=True, download_name=p.name)
    finally:
        con.close()


@app.route("/api/import", methods=["POST"])
def api_import():
    from .excelio import import_day
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path")
    results = []
    paths = []
    if path:
        p = Path(path).expanduser()
        paths = sorted(p.glob("*.xlsx")) if p.is_dir() else [p]
    con = db.connect()
    try:
        for p in paths:
            try:
                rec = import_day(p)
                day_id = db.commit_day(con, rec)
                results.append({"file": p.name, "ok": True, "day_id": day_id})
            except Exception as e:
                results.append({"file": p.name, "ok": False, "error": str(e)})
        return jsonify({"results": results})
    finally:
        con.close()


# ------------------------------------------------------------------ settings

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        cfg = config.load_config()
        for k, v in data.items():
            if k in config.DEFAULTS:
                want = type(config.DEFAULTS[k])
                try:
                    cfg[k] = bool(v) if want is bool else want(v)
                except Exception:
                    pass
        config.save_config(cfg)
        state.reload_config()
    out = dict(config.load_config())
    out["_data_dir"] = str(config.data_dir())
    return jsonify(out)


@app.route("/api/registry")
def api_registry():
    con = db.connect()
    try:
        return jsonify({"names": db.known_names(con),
                        "places": db.known_places(con)})
    finally:
        con.close()


@app.route("/api/registry/rename", methods=["POST"])
def api_registry_rename():
    data = request.get_json(force=True, silent=True) or {}
    kind, old, new = data.get("kind"), data.get("old"), data.get("new")
    if not (kind and old and new):
        return jsonify({"ok": False}), 400
    con = db.connect()
    try:
        if kind == "name":
            db.rename_employee(con, old, new)
        else:
            db.rename_place(con, old, new)
        return jsonify({"ok": True})
    finally:
        con.close()


@app.route("/api/recompute", methods=["POST"])
def api_recompute():
    data = request.get_json(force=True, silent=True) or {}
    params = config.engagement_params(config.load_config())
    con = db.connect()
    try:
        if data.get("day_id"):
            ids = [int(data["day_id"])]
        else:
            ids = [d["id"] for d in db.all_days(con)]
        done = 0
        for did in ids:
            try:
                recompute_day(con, did, params)
                done += 1
            except Exception:
                pass
        return jsonify({"ok": True, "recomputed": done})
    finally:
        con.close()


@app.route("/api/reprocess", methods=["POST"])
def api_reprocess():
    data = request.get_json(force=True, silent=True) or {}
    con = db.connect()
    try:
        if data.get("day_id"):
            ids = [int(data["day_id"])]
        else:
            ids = [d["id"] for d in db.all_days(con)]
    finally:
        con.close()
    added = state.enqueue_reprocess(ids)
    return jsonify({"ok": True, "queued": len(added), "jobs": added})


@app.route("/api/days")
def api_days():
    con = db.connect()
    try:
        days = db.all_days(con, employee=request.args.get("employee"),
                           place=request.args.get("place"))
        out = []
        for d in days:
            s = json.loads(d["stats_json"])
            out.append({"id": d["id"], "date": d["date"],
                        "weekday": d["weekday"], "place": d["place"],
                        "employee": d["employee"],
                        "conversion": s["conversion"],
                        "cold": s["cold_persons"], "warm": s["warm_persons"],
                        "photos": s["photos_total"],
                        "money": ((d["money_cash"] or 0) + (d["money_card"] or 0))
                        if (d["money_cash"] is not None
                            or d["money_card"] is not None) else None})
        return jsonify({"days": out})
    finally:
        con.close()


# ------------------------------------------------------------------ main

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("folders", nargs="*")
    args = ap.parse_args()
    create()
    if args.folders:
        threading.Timer(1.0, lambda: state.enqueue(args.folders)).start()
    log = config.data_dir() / "logs" / "server.log"
    with open(log, "a") as f:
        f.write(f"\n[{datetime.now().isoformat()}] {APP_NAME} {APP_VERSION} "
                f"on 127.0.0.1:{args.port}\n")
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
