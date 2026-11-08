import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from promofinder.parser import load_zip, dataset_report, parse_ts, fmt_ts, parse_episode_text  # noqa: E402
from promofinder.validate import Index, validate_candidate  # noqa: E402
from promofinder import providers  # noqa: E402
from promofinder.pipeline import Run  # noqa: E402

SYN = ROOT / "demo_data" / "synthetic_show.zip"
SC = {"hook": 20, "cliffhanger": 20, "standalone": 15, "emotion": 12, "visual": 8, "distinct": 4}


def setup_module(_):
    if not SYN.exists():
        from promofinder.demo import build
        build(SYN)


def idx():
    eps, _ = load_zip(str(SYN))
    return Index(eps), eps


def test_timestamps_roundtrip():
    assert parse_ts("01:18.50") == 78.5
    assert parse_ts("00:04.80") == 4.8
    assert fmt_ts(78.5) == "01:18.50"
    assert parse_ts("1:2.3") is None or parse_ts("1:2.3") is not None  # tolerant, no crash


def test_parser_counts_and_uppercase_variant():
    eps, fr = load_zip(str(SYN))
    rep = dataset_report(eps, fr)
    assert rep["unique_episodes"] == 3 and rep["complete_sequence"]
    assert rep["all_timestamps_parsable"]
    ep3 = [e for e in eps if e.number == 3][0]   # upper-case headers
    assert ep3.scenes[0].start == "00:00.00" and ep3.events


def test_missing_and_duplicate_episode_detection():
    buf = io.BytesIO()
    src = zipfile.ZipFile(SYN)
    with zipfile.ZipFile(buf, "w") as z:
        names = sorted(src.namelist())
        z.writestr(names[0], src.read(names[0]))
        z.writestr("dup/" + names[0].split("/")[-1], src.read(names[0]))
        z.writestr(names[2], src.read(names[2]))
    eps, fr = load_zip(buf.getvalue())
    rep = dataset_report(eps, fr)
    assert rep["missing_episodes"] == [2]
    assert rep["duplicate_episodes"] == [1]


def test_duration_hook_and_cliffhanger_checks():
    ix, _ = idx()
    c = {"segments": [{"start_event": "E1-004", "end_event": "E1-025"}], "hook_event": "E1-004",
         "cliffhanger_event": "E1-025", "scores": SC}
    v = validate_candidate(ix, c)
    assert v["eligible"], v
    assert v["checks"]["hook_offset_s"] <= 3.0
    assert 20 <= v["total_duration_s"] <= 60


def test_multi_segment_duration_excludes_gaps():
    ix, _ = idx()
    c = {"segments": [{"start_event": "E1-004", "end_event": "E1-014"},
                      {"start_event": "E1-021", "end_event": "E1-025"}],
         "hook_event": "E1-004", "cliffhanger_event": "E1-025", "scores": SC}
    v = validate_candidate(ix, c)
    total = sum(s["end_s"] - s["start_s"] for s in v["segments"])
    assert abs(v["total_duration_s"] - total) < 0.01
    assert v["total_duration_s"] < v["segments"][-1]["end_s"] - v["segments"][0]["start_s"]


def test_rejects_late_hook_fake_ids_and_fabricated_quotes():
    ix, _ = idx()
    late = validate_candidate(ix, {"segments": [{"start_event": "E1-001", "end_event": "E1-025"}],
                                   "hook_event": "E1-021", "cliffhanger_event": "E1-025", "scores": SC})
    assert not late["eligible"] and any("hook starts" in e for e in late["errors"])
    fake = validate_candidate(ix, {"segments": [{"start_event": "E1-999", "end_event": "E1-025"}],
                                   "hook_event": "E1-004", "cliffhanger_event": "E1-025", "scores": SC})
    assert not fake["eligible"]
    fab = validate_candidate(ix, {"segments": [{"start_event": "E1-004", "end_event": "E1-025"}],
                                  "hook_event": "E1-004", "cliffhanger_event": "E1-025", "scores": SC,
                                  "hook": "'You will never work in this city again!'"})
    assert not fab["eligible"] and any("unverifiable" in e for e in fab["errors"])


def test_too_long_and_cliffhanger_not_at_end():
    ix, _ = idx()
    v = validate_candidate(ix, {"segments": [{"start_event": "E1-004", "end_event": "E1-025"}],
                                "hook_event": "E1-004", "cliffhanger_event": "E1-014", "scores": SC})
    assert any("after the cliffhanger" in e for e in v["errors"])


class Scripted(providers.BaseProvider):
    """Deterministic stand-in for an LLM, used to test the LLM code path end to end."""
    name, model = "scripted", "test"

    def _call(self, prompt):
        if "ONE episode" in prompt and "EPISODE 1 " in prompt:
            r = {"episode": 1, "episode_summary": "Mara is humiliated at a gala; a driver proposes.", "story_facts": [],
                 "candidates": [{"title": "Fired from the gala", "angle": "humiliation",
                                 "segments": [{"start_event": "E1-004", "end_event": "E1-025"}],
                                 "hook_event": "E1-004", "hook_quote": "Stop right there.",
                                 "hook": "'Stop right there. Who let the help into my party?'",
                                 "cliffhanger_event": "E1-025", "cliffhanger": "'Marry me, and none of them will ever touch you again.'",
                                 "standalone_context": "clear", "why_it_works": "x", "scores": SC, "confidence": "high"}],
                 "rejected_moments": []}
        elif "ONE episode" in prompt:
            r = {"episode": 0, "episode_summary": "", "story_facts": [], "candidates": [], "rejected_moments": []}
        else:
            r = {"show_summary": "s", "cross_episode_promos": [{
                "title": "Valet to owner", "angle": "power-reversal",
                "segments": [{"start_event": "E1-008", "end_event": "E1-014"}, {"start_event": "E2-007", "end_event": "E2-016"}],
                "hook_event": "E1-008", "hook_quote": "Theo is engaged", "hook": "h", "cliffhanger_event": "E2-016",
                "cliffhanger": "'Who... who are you?'", "scores": SC, "confidence": "medium"}],
                "distinct_scores": {}, "duplicate_groups": [], "publication_top5": [{"candidate_id": "X1", "reason": "r"}]}
        return json.dumps(r), {"input_tokens": len(prompt) // 4}


def test_llm_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "get_provider", lambda n, r, p=None, c=None: Scripted(r, p))
    import promofinder.pipeline as pl
    monkeypatch.setattr(pl, "get_provider", lambda n, r, p=None, c=None: Scripted(r, p))
    run = Run(tmp_path / "out", "scripted", log=lambda *_: None)
    res = run.execute(str(SYN))
    assert res["status"] == "complete"
    ids = [p["id"] for p in res["ranked_promos"]]
    assert "C01-1" in ids, res["near_misses"]
    # X1 reuses C01-1 footage, so dedupe must list it as an alternate, not a second ranked promo
    x1 = [p for p in res["alternates"] if p["id"] == "X1"][0]
    assert x1["duplicate_of"] == "C01-1" and x1["eligible"]
    assert x1["episodes"] == [1, 2] and len(x1["segments"]) == 2
    assert (tmp_path / "out" / "final_promo_ranking.csv").exists()
    # cache: second run makes no new calls
    run2 = Run(tmp_path / "out", "scripted", log=lambda *_: None)
    run2.execute(str(SYN))
    assert all(c["cached"] for c in run2.provider.calls)


def test_file_provider_reports_missing(tmp_path):
    run = Run(tmp_path / "o", "file", log=lambda *_: None)
    res = run.execute(str(SYN))
    assert res["status"] == "awaiting_responses" and len(res["missing"]) == 3
    assert (tmp_path / "o" / "llm_prompts" / "stage1_ep001.prompt.txt").exists()


def test_heuristic_mode_labels_output_unverified(tmp_path):
    res = Run(tmp_path / "h", "heuristic", log=lambda *_: None).execute(str(SYN))
    assert res["mode"] == "heuristic"
    assert all(p["status"] == "heuristic_shortlist_unverified" for p in res["ranked_promos"])
