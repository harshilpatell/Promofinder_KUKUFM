"""Command line entry point.

  python -m promofinder.cli run --zip scripts.zip --out runs/my_run --provider heuristic
  python -m promofinder.cli run --zip scripts.zip --out runs/my_run --provider anthropic
  python -m promofinder.cli run --zip scripts.zip --out runs/my_run --provider file --responses saved/llm_responses
  python -m promofinder.cli validate --zip scripts.zip          # dataset report only
  python -m promofinder.cli inspect --zip scripts.zip --episode 3 --start 00:58 --end 01:30
"""
from __future__ import annotations

import argparse
import json
import sys

from .parser import load_zip, dataset_report, parse_ts
from .timeline import event_line


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass


def main(argv=None):
    _load_env()
    ap = argparse.ArgumentParser(prog="promofinder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--zip", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--provider", default=None, help="anthropic | openai | file | heuristic")
    r.add_argument("--responses", default=None, help="directory of saved LLM responses (cache / replay)")
    r.add_argument("--title", default=None)
    r.add_argument("--no-repair", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--zip", required=True)
    i = sub.add_parser("inspect")
    i.add_argument("--zip", required=True)
    i.add_argument("--episode", type=int, required=True)
    i.add_argument("--start", default="00:00.00")
    i.add_argument("--end", default="99:59.99")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        eps, fr = load_zip(a.zip)
        print(json.dumps(dataset_report(eps, fr), indent=1))
        return 0
    if a.cmd == "inspect":
        eps, _ = load_zip(a.zip)
        ep = next((e for e in eps if e.number == a.episode), None)
        if not ep:
            print("episode not found"); return 1
        lo = parse_ts(a.start if "." in a.start else a.start + ".00")
        hi = parse_ts(a.end if "." in a.end else a.end + ".00")
        for e in ep.events:
            if lo <= e.start_s <= hi:
                print(event_line(e, 200))
        return 0
    from .pipeline import Run
    run = Run(a.out, a.provider, a.responses, a.title, repair=not a.no_repair)
    res = run.execute(a.zip)
    if res.get("status") != "complete":
        print(json.dumps({k: res[k] for k in ("status", "stage")}, indent=1))
        print(f"{len(res['missing'])} responses missing, e.g. {res['missing'][:3]}")
        return 2
    print(f"Qualified promos: {len(res['ranked_promos'])}")
    for p in res["ranked_promos"][:10]:
        segs = " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in p["segments"])
        print(f"#{p['rank']:>2} {p['total_score']:>3} {p['id']:<6} {p['total_duration_s']:>5}s  {p['title']}  [{segs}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
