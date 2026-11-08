"""Tests added for the public deployment: upload safety, credentials, exports, demo, app smoke test."""
import csv
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from promofinder.export import to_csv  # noqa: E402
from promofinder.parser import load_zip, parse_episode_text, parse_ts, dataset_report  # noqa: E402
from promofinder.pipeline import Run  # noqa: E402
from promofinder.providers import get_provider  # noqa: E402
from promofinder.settings import load_settings, public_summary  # noqa: E402
from promofinder.upload import check_zip, require_valid_zip, ZipValidationError  # noqa: E402

DEMO = ROOT / "demo_data" / "synthetic_show.zip"
DEMO_RESP = ROOT / "demo_data" / "synthetic_llm_responses"
EP = (ROOT / "tests" / "fixtures_episode.txt")


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


# ---------- upload safety ----------
def test_demo_zip_accepted():
    chk = check_zip(DEMO.read_bytes())
    assert chk.ok and len(chk.txt_files) == 3


def test_rejects_non_zip_and_empty():
    assert not check_zip(b"").ok
    assert "not a valid ZIP" in check_zip(b"hello world").errors[0]
    with pytest.raises(ZipValidationError):
        require_valid_zip(b"garbage")


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd.txt", "a/../../b.txt", "C:/win.txt", "..\\x.txt"])
def test_rejects_zip_slip_paths(bad):
    chk = check_zip(_zip([(bad, "x")]))
    assert not chk.ok and any("Unsafe path" in e for e in chk.errors)


def test_rejects_unexpected_file_types_but_ignores_mac_junk():
    chk = check_zip(_zip([("show/ep1.txt", "x"), ("show/run.exe", "MZ")]))
    assert not chk.ok and any("Unexpected file type" in e for e in chk.errors)
    chk2 = check_zip(_zip([("show/ep1.txt", "x"), ("__MACOSX/show/._ep1.txt", "x"), ("show/.DS_Store", "x")]))
    assert chk2.ok and chk2.warnings


def test_rejects_too_large_too_many_and_zip_bomb():
    assert not check_zip(_zip([("a.txt", "x" * 5000)]), {"max_zip_bytes": 100}).ok
    many = _zip([(f"e{i}.txt", "x") for i in range(30)])
    assert not check_zip(many, {"max_entries": 10}).ok
    assert not check_zip(many, {"max_txt_files": 10}).ok
    bomb = _zip([("bomb.txt", "0" * 3_000_000)])
    chk = check_zip(bomb)
    assert not chk.ok and any("zip bomb" in e or "uncompressed" in e for e in chk.errors)


def test_rejects_zip_without_txt():
    chk = check_zip(_zip([("folder/", "")]))
    assert not chk.ok


# ---------- parsing ----------
def test_timestamp_parsing_and_invalid_values():
    assert parse_ts("02:18.00") == 138.0
    assert parse_ts("00:04.80") == 4.8
    for bad in ("00:75.00", "ab:cd.ef", "1:2", "", "00-04.80"):
        assert parse_ts(bad) is None, bad


def test_invalid_timestamp_is_reported_not_crashing():
    text = """EPISODE NUMBER: Episode 1
EPISODE LOGLINE: x
CONTINUITY NOTES: y
--- SCRIPT START ---
SCENE 01
Scene heading: INT. ROOM - DAY
Scene start: 00:00.00
Scene end: 00:30.00
Actions and dialogue:
**CAMERA:**
Start: (00:00.00) | End: (00:75.00)
Bad end time.
**ANNA (Calm):**
Start: (00:05.00) | End: (00:07.00)
"Hello."
--- SCRIPT END ---"""
    ep = parse_episode_text(text, "episode-001.txt")
    assert any("Unparsable timestamp" in i for i in ep.issues)
    assert len(ep.events) == 1 and ep.events[0].speaker == "ANNA"
    rep = dataset_report([ep], [{"file": "episode-001.txt", "status": "parsed"}])
    assert rep["all_timestamps_parsable"] is False


def test_extraction_from_uploaded_bytes():
    eps, fr = load_zip(DEMO.read_bytes())
    assert [e.number for e in eps] == [1, 2, 3]
    assert sum(len(e.events) for e in eps) == 62


# ---------- credentials / settings ----------
def test_missing_credentials_fall_back_safely(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "PROMOFINDER_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    cfg = load_settings({})
    assert cfg["_llm_configured"] is False and cfg["_provider"] == "heuristic"
    assert "No LLM configured" in public_summary(cfg)
    with pytest.raises(RuntimeError, match="not configured"):
        get_provider("anthropic", tempfile.mkdtemp())
    with pytest.raises(RuntimeError, match="not configured"):
        get_provider("openai", tempfile.mkdtemp())


def test_secrets_configure_provider_without_touching_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = dict(os.environ)
    cfg = load_settings({"PROMOFINDER_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test-not-real",
                         "PROMOFINDER_MODEL": "m1"})
    assert cfg["_llm_configured"] and cfg["_provider"] == "openai" and cfg["_model"] == "m1"
    assert "sk-test" not in public_summary(cfg)
    prov = get_provider("openai", tempfile.mkdtemp(), config=cfg)
    assert prov.model == "m1"
    assert dict(os.environ) == before  # no global mutation -> no cross-session leakage


# ---------- demo, exports ----------
def _demo_result():
    return Run(tempfile.mkdtemp(), "file", str(DEMO_RESP), log=lambda *_: None).execute(DEMO.read_bytes())


def test_demo_replay_is_labelled_and_complete():
    res = _demo_result()
    assert res["status"] == "complete"
    assert res["llm_source"] == "offline replay of saved responses"
    assert [p["id"] for p in res["ranked_promos"]] == ["C01-1", "C03-1"]
    assert res["ranked_promos"][0]["editorial_priority"] == 1
    assert [a["id"] for a in res["alternates"]] == ["X1"]
    assert res["near_misses"][0]["id"] == "C02-1"
    for p in res["ranked_promos"]:
        assert 20 <= p["total_duration_s"] <= 60 and p["checks"]["hook_offset_s"] <= 3.0


def test_heuristic_demo_labelled_unverified():
    res = Run(tempfile.mkdtemp(), "heuristic", log=lambda *_: None).execute(DEMO.read_bytes())
    assert res["llm_source"] == "none (heuristic)"
    assert all(p["status"] == "heuristic_shortlist_unverified" for p in res["ranked_promos"])


def test_csv_and_json_exports():
    res = _demo_result()
    rows = list(csv.DictReader(io.StringIO(to_csv(res["ranked_promos"]))))
    assert len(rows) == 2
    assert rows[0]["id"] == "C01-1" and rows[0]["editorial_priority"] == "1"
    assert rows[0]["seg1_start"] and rows[0]["seg1_end"] and float(rows[0]["total_duration_s"]) > 20
    back = json.loads(json.dumps(res))
    assert back["ranked_promos"][0]["segments"][0]["start"] == rows[0]["seg1_start"]


def test_empty_zip_rejected_by_pipeline():
    with pytest.raises(ValueError):
        Run(tempfile.mkdtemp(), "heuristic", log=lambda *_: None).execute(_zip([("readme.md", "x")]))


# ---------- confidentiality ----------
def test_repository_contains_no_client_content_or_secrets():
    banned = re.compile(r"Juliana|Ashcroft|Broken Soldier|Clarissa|Dowager|sk-[A-Za-z0-9]{20,}|sk-ant-", re.I)
    hits = []
    for f in ROOT.rglob("*"):
        if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts and f.name != "test_deploy.py":
            try:
                txt = f.read_text(errors="ignore") if f.suffix != ".zip" else \
                    " ".join(zipfile.ZipFile(f).read(n).decode(errors="ignore") for n in zipfile.ZipFile(f).namelist())
            except Exception:
                continue
            if banned.search(txt):
                hits.append(str(f.relative_to(ROOT)))
    assert not hits, hits
    assert not (ROOT / ".env").exists() and not (ROOT / ".streamlit" / "secrets.toml").exists()


# ---------- app smoke test (Streamlit's headless AppTest, no browser) ----------
def test_app_starts_and_runs_demo():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    labels = [t.label for t in at.text_input]
    assert not any("KEY" in l.upper() or "URL" in l.upper() or "FOLDER" in l.upper() for l in labels)
    at.button[0].click().run()   # "Run synthetic demo (saved example LLM responses)"
    assert not at.exception
    body = " ".join(m.value for m in at.markdown)
    assert "2 qualified promos" in body and "offline replay" in body


def test_heuristic_shortlist_respects_hook_and_cliffhanger_floors():
    res = Run(tempfile.mkdtemp(), "heuristic", log=lambda *_: None).execute(DEMO.read_bytes())
    for p in res["ranked_promos"]:
        assert p["scores"]["hook"] >= 15 and p["scores"]["cliffhanger"] >= 15
    assert res["near_misses"], "weak heuristic windows must be reported as near-misses, not shortlisted"
