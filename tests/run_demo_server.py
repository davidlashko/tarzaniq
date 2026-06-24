"""Launch TarzanIQ with the MockEngine against a seeded DB — for the DOM smoke test.

No ONNX models needed: MockEngine lets the whole app serve and every page render.
Seed first, then launch against the same data dir:

    rm -rf /tmp/tq_demo
    TARZANIQ_DATA=/tmp/tq_demo python tests/seed_demo.py
    TARZANIQ_DATA=/tmp/tq_demo python tests/run_demo_server.py --port 43991 &
    node tests/dom_smoke.mjs http://127.0.0.1:43991
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tarzaniq import server  # noqa: E402
from tarzaniq.engine import MockEngine  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=43991)
    args = ap.parse_args()
    app = server.create(engine_factory=lambda: MockEngine({}))
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
