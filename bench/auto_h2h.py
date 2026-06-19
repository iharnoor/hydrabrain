"""Auto-runner — poll HydraDB and fire the head-to-head the moment it recovers.

The accuracy head-to-head needs the HydraDB API up. When it's mid-outage, run this
in the background; it polls health and, on recovery, runs `bench.headtohead` once
(rebuilding the gbrain brain if needed) and exits. No babysitting.

  python3 -m bench.auto_h2h [--interval 120] [--max-checks 45]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def healthy() -> bool:
    try:
        from hydrabrain.client import HydraDBClient
        from hydrabrain import config
        c = HydraDBClient(api_key=config.require("HYDRADB_API_KEY")).use_tenant(config.DEFAULT_TENANT)
        c.add_memory("healthcheck", infer=False)  # cheap write; 500s while backend is down
        return True
    except Exception:
        return False


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=120, help="seconds between health checks")
    ap.add_argument("--max-checks", type=int, default=45, help="give up after this many checks")
    args = ap.parse_args(argv or [])

    for i in range(1, args.max_checks + 1):
        if healthy():
            print(f"[{i}] HydraDB healthy — running head-to-head", flush=True)
            r = subprocess.run([sys.executable, "-u", "-m", "bench.headtohead"])
            sys.exit(r.returncode)
        print(f"[{i}/{args.max_checks}] HydraDB still down — retry in {args.interval}s", flush=True)
        time.sleep(args.interval)

    print("gave up: HydraDB did not recover within the watch window. Re-launch when it's back.", flush=True)
    sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
