"""JSON / CSV export."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

FIELDS = ["rank", "editorial_priority", "id", "status", "priority", "confidence", "total_score", "title", "angle", "episodes",
          "total_duration_s", "n_segments"] + [f"seg{i}_{k}" for i in (1, 2, 3) for k in ("episode", "start", "end", "duration_s")] + \
         ["hook_offset_s", "hook", "hook_quote", "cliffhanger", "why_it_works", "standalone_context",
          "score_hook", "score_cliffhanger", "score_standalone", "score_emotion", "score_visual", "score_distinct",
          "concerns", "warnings", "duplicate_of", "rejection_reasons", "editor_decision", "editor_notes"]


def flat_row(r):
    row = {k: r.get(k, "") for k in ("rank", "editorial_priority", "id", "status", "priority", "confidence", "total_score", "title", "angle",
                                      "total_duration_s", "hook", "hook_quote", "cliffhanger", "why_it_works",
                                      "standalone_context", "concerns", "duplicate_of", "editor_decision", "editor_notes")}
    row["episodes"] = ",".join(str(e) for e in r.get("episodes", []))
    row["n_segments"] = len(r.get("segments", []))
    for i, s in enumerate(r.get("segments", [])[:3], 1):
        row[f"seg{i}_episode"] = s["episode"]
        row[f"seg{i}_start"] = s["start"]
        row[f"seg{i}_end"] = s["end"]
        row[f"seg{i}_duration_s"] = s["duration_s"]
    row["hook_offset_s"] = (r.get("checks") or {}).get("hook_offset_s", "")
    for k, v in (r.get("scores") or {}).items():
        row[f"score_{k}"] = v
    row["warnings"] = " | ".join(r.get("warnings", []))
    row["rejection_reasons"] = " | ".join(r.get("rejection_reasons", []))
    return row


def to_csv(rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(flat_row(r))
    return buf.getvalue()


def export_all(result, out_dir):
    out = Path(out_dir)
    (out / "final_promo_ranking.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "final_promo_ranking.csv").write_text(to_csv(result["ranked_promos"]), encoding="utf-8")
    (out / "alternates_and_near_misses.csv").write_text(
        to_csv(result["alternates"] + result["near_misses"]), encoding="utf-8")
