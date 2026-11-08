"""PromoFinder — Streamlit UI.   Run locally:  streamlit run app.py

Public-deployment rules implemented here:
* API keys / model settings come only from server-side Streamlit secrets or environment variables.
* No server file paths are accepted from visitors (folder features exist only in LOCAL MODE).
* Uploaded ZIPs are size/type/path-checked before parsing and are never extracted to disk.
* Every result is labelled with its true source: heuristic, offline replay of saved responses, or live LLM call.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from promofinder import __version__
from promofinder.demo import build_bytes as build_demo_zip
from promofinder.export import to_csv
from promofinder.parser import dataset_report, load_zip
from promofinder.pipeline import Run
from promofinder.settings import load_settings, public_summary
from promofinder.timeline import event_line
from promofinder.upload import LIMITS, ZipValidationError, check_zip, require_valid_zip
from promofinder.validate import Index, validate_candidate

try:  # local runs may use a .env file; on Streamlit Cloud use Secrets instead
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DEMO_ZIP = ROOT / "demo_data" / "synthetic_show.zip"
DEMO_RESPONSES = ROOT / "demo_data" / "synthetic_llm_responses"
log = logging.getLogger("promofinder")

st.set_page_config(page_title="PromoFinder", page_icon="🎬", layout="wide")
ss = st.session_state
for k, v in {"result": None, "reviews": {}, "zip_bytes": None, "report": None, "source_label": ""}.items():
    ss.setdefault(k, v)

try:
    _secrets = st.secrets
except Exception:
    _secrets = None
CFG = load_settings(_secrets)

st.title("🎬 PromoFinder — AI-Powered Microdrama Promo Discovery")
st.markdown("Reads microdrama screenplays (a ZIP with one `.txt` per episode) and proposes **20–60 second promo clips** "
            "that open on a **hook within 3 seconds** and end on a **cliffhanger**, with the **episode and exact source "
            "timestamps** of every segment. Every timestamp is verified against the script by code. An editor then approves or rejects each clip.")


# ---------------------------------------------------------------- helpers
def demo_bytes() -> bytes:
    return DEMO_ZIP.read_bytes() if DEMO_ZIP.exists() else build_demo_zip()


def run_pipeline(zip_bytes: bytes, provider: str, responses_dir=None, config=None, label=""):
    """Run in a temporary folder that is deleted afterwards; results are kept in session memory."""
    out = Path(tempfile.mkdtemp(prefix="promofinder_run_"))
    box = st.empty()
    lines = []

    def _log(m):
        lines.append(str(m))
        box.code("\n".join(lines[-10:]))
    try:
        res = Run(out, provider, responses_dir, log=_log, provider_config=config).execute(zip_bytes)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    box.empty()
    if res.get("status") != "complete":
        st.warning(f"Run paused: {len(res.get('missing', []))} LLM responses are missing ({res.get('stage')}).")
        return
    ss.result, ss.reviews, ss.zip_bytes, ss.source_label = res, {}, zip_bytes, label
    eps, fr = load_zip(zip_bytes)
    ss.report = dataset_report(eps, fr)


def show_report(rep):
    c = st.columns(5)
    c[0].metric("Files parsed", rep["txt_files_parsed"])
    c[1].metric("Episodes detected", rep["unique_episodes"])
    c[2].metric("Timestamped events", rep["total_events"])
    c[3].metric("Missing episodes", len(rep["missing_episodes"]))
    c[4].metric("Duplicate episodes", len(rep["duplicate_episodes"]))
    if rep["missing_episodes"] or rep["duplicate_episodes"]:
        st.error(f"Episode sequence incomplete: missing {rep['missing_episodes']}, duplicates {rep['duplicate_episodes']}.")
    if not rep["all_timestamps_parsable"]:
        st.error("Some timestamps could not be parsed; see the structural issues below.")
    if rep["issues"]:
        with st.expander(f"Structural issues in {len(rep['issues'])} episode(s)"):
            st.json(rep["issues"])


def safe_error(prefix, ex):
    log.exception(prefix)
    st.error(f"{prefix}: {ex}")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Analysis engine")
    st.caption(public_summary(CFG))
    engines = ["Heuristic (no LLM — unverified shortlist)"]
    if CFG["_llm_configured"]:
        engines.append(f"LLM: {CFG['_provider']} · {CFG['_model']}")
    engine = st.radio("Engine for uploaded ZIPs", engines)
    use_llm = engine.startswith("LLM")
    code_ok = True
    if use_llm and CFG.get("PROMOFINDER_ACCESS_CODE"):
        code_ok = st.text_input("Access code (set by the app owner)", type="password") == CFG["PROMOFINDER_ACCESS_CODE"]
        if not code_ok:
            st.info("Enter the access code to enable live LLM runs.")
    if use_llm:
        st.warning("Live LLM mode sends the uploaded screenplay text to the configured model provider.")
    else:
        st.warning("Heuristic mode scores keywords and punctuation only. It cannot judge story context or whether a "
                   "clip makes sense to a new viewer. Treat its output as an unverified shortlist, not an LLM analysis.")
    st.divider()
    st.caption(f"PromoFinder v{__version__}. Upload limit {LIMITS['max_zip_bytes'] // 2**20} MB, "
               f"{LIMITS['max_txt_files']} episodes, .txt files only.")

# ---------------------------------------------------------------- input
st.header("1 · Try it or upload a screenplay ZIP")
d1, d2 = st.columns(2)
with d1:
    if st.button("▶ Run synthetic demo (saved example LLM responses)", type="primary"):
        try:
            run_pipeline(demo_bytes(), "file", str(DEMO_RESPONSES),
                         label="Synthetic demo show · offline replay of saved example LLM responses (no live model call)")
        except Exception as ex:
            safe_error("Demo failed", ex)
    st.caption("An original 3-episode show written for this demo, with saved example LLM responses. No API key is needed.")
with d2:
    if st.button("▶ Run synthetic demo (heuristic)"):
        try:
            run_pipeline(demo_bytes(), "heuristic", label="Synthetic demo show · heuristic mode (unverified)")
        except Exception as ex:
            safe_error("Demo failed", ex)
    st.download_button("Download the synthetic demo ZIP", demo_bytes(), "synthetic_show.zip", "application/zip")

st.subheader("Upload your own screenplay ZIP")
st.caption("Privacy: the ZIP is checked and parsed in memory. Run files are written to a temporary folder on this "
           "server and deleted when the run finishes. Results stay in your browser session until you close the tab. "
           "This is a public demo, so do not upload confidential scripts here. Run PromoFinder locally for those.")
up = st.file_uploader("Screenplay ZIP (one .txt per episode)", type=["zip"])
if up is not None:
    data = up.getvalue()
    chk = check_zip(data)
    for w in chk.warnings[:5]:
        st.caption(f"ℹ️ {w}")
    if not chk.ok:
        for e in chk.errors[:10]:
            st.error(e)
    else:
        try:
            eps, fr = load_zip(data)
            rep = dataset_report(eps, fr)
            show_report(rep)
            if not eps:
                st.error("No episodes could be parsed. Check the screenplay format.")
            elif st.button("2 · Find promos", type="primary"):
                if use_llm and not code_ok:
                    st.error("Live LLM runs need the access code.")
                elif use_llm and len(eps) > CFG["_max_llm_episodes"]:
                    st.error(f"{len(eps)} episodes exceeds this server's live-LLM limit of {CFG['_max_llm_episodes']}.")
                else:
                    if use_llm:
                        cache = ss.setdefault("llm_cache_dir", tempfile.mkdtemp(prefix="promofinder_cache_"))
                        run_pipeline(data, CFG["_provider"], cache, config=CFG,
                                     label=f"Your upload · live LLM call: {CFG['_provider']}:{CFG['_model']}")
                    else:
                        run_pipeline(data, "heuristic", label="Your upload · heuristic mode (unverified)")
        except ZipValidationError as ex:
            st.error(str(ex))
        except RuntimeError as ex:
            safe_error("Model configuration problem", ex)
            st.info("If a run stopped because of a rate limit, wait a minute and press 'Find promos' again: "
                    "answers already received in this session are reused.")
        except Exception as ex:
            safe_error("Processing failed", ex)

with st.expander("View a saved result file (final_promo_ranking.json)"):
    rj = st.file_uploader("Saved final_promo_ranking.json", type=["json"], key="rj")
    rz = st.file_uploader("Optional: the matching screenplay ZIP (enables timeline inspection and re-validation)",
                          type=["zip"], key="rz")
    if rj is not None and st.button("Load saved result"):
        try:
            res = json.loads(rj.getvalue())
            assert isinstance(res, dict) and isinstance(res.get("ranked_promos"), list)
            zb = None
            if rz is not None:
                zb = rz.getvalue()
                require_valid_zip(zb)
            ss.result, ss.reviews, ss.zip_bytes = res, {}, zb
            ss.source_label = f"Saved result file · recorded source: {res.get('llm_source', 'see run metadata')}"
            ss.report = None
            if zb:
                eps, fr = load_zip(zb)
                ss.report = dataset_report(eps, fr)
        except (ValueError, AssertionError, KeyError) as ex:
            st.error(f"Not a valid PromoFinder result file ({ex}).")
        except ZipValidationError as ex:
            st.error(str(ex))

if CFG["_local_mode"]:
    with st.expander("LOCAL MODE: replay saved LLM responses from a folder on this computer"):
        folder = st.text_input("Folder containing <prompt_id>.json responses")
        lz = st.file_uploader("Screenplay ZIP for that run", type=["zip"], key="lz")
        if st.button("Replay") and folder and lz is not None:
            if not Path(folder).is_dir():
                st.error("Folder not found.")
            else:
                try:
                    zb = lz.getvalue()
                    require_valid_zip(zb)
                    run_pipeline(zb, "file", folder, label="Local replay of saved LLM responses (no live model call)")
                except ZipValidationError as ex:
                    st.error(str(ex))
                except Exception as ex:
                    safe_error("Replay failed", ex)

res = ss.result
if not res:
    st.info("Run the demo or upload a ZIP to see results.")
    st.stop()

# ---------------------------------------------------------------- results
st.header("3 · Ranked promos")
st.markdown(f"**Source:** {ss.source_label}")
if res.get("mode") == "heuristic":
    st.warning("HEURISTIC RESULTS: not evaluated by an LLM. An editor must check every clip.")
if ss.report:
    show_report(ss.report)
idx = None
if ss.zip_bytes:
    try:
        eps, _ = load_zip(ss.zip_bytes)
        idx = Index(eps)
    except Exception as ex:
        safe_error("Could not re-open the screenplay ZIP", ex)
ranked = res["ranked_promos"]
st.write(f"**{len(ranked)} qualified promos** · {len(res.get('alternates', []))} alternate cuts of the same beats · "
         f"{len(res.get('near_misses', []))} near-misses.")
st.caption("**Score rank** orders clips by the rubric score out of 100. **Editorial priority** (1–5) is the separate "
           "publish-first choice from the show-wide stage, which balances angles and spoilers. The two can differ.")


def segs_str(p):
    return " + ".join(f"Ep{s['episode']} {s['start']}–{s['end']}" for s in p["segments"])


df = pd.DataFrame([{"score rank": p.get("rank"), "editorial priority": p.get("editorial_priority") or "",
                    "id": p["id"], "score": p["total_score"], "priority": p.get("priority"),
                    "confidence": p["confidence"], "title": p["title"], "angle": p["angle"],
                    "duration_s": p["total_duration_s"], "segments": segs_str(p), "warnings": len(p.get("warnings", [])),
                    "review": ss.reviews.get(p["id"], {}).get("decision", "—")} for p in ranked])
if len(df):
    pick = st.multiselect("Filter by angle", sorted(df["angle"].dropna().unique()))
    st.dataframe(df[df["angle"].isin(pick)] if pick else df, hide_index=True)
else:
    st.info("No clip qualified. See the near-misses below for the reasons.")
if res.get("publication_top5"):
    with st.expander("Editorial publish-first picks (show-wide stage)"):
        for i, t in enumerate(res["publication_top5"], 1):
            st.markdown(f"{i}. **{t.get('candidate_id')}** — {t.get('reason')} *(emotion: {t.get('target_emotion', '')})*")
if res.get("portfolio_note"):
    st.caption("Portfolio note: " + res["portfolio_note"])

# ---------------------------------------------------------------- detail + review
st.header("4 · Inspect & review a promo")
pool = ranked + res.get("alternates", []) + res.get("near_misses", [])
if not pool:
    st.stop()
labels = [f"{q['id']} · {q['title']} · {q['status']}" for q in pool]
p = pool[labels.index(st.selectbox("Promo", labels))]
left, right = st.columns([3, 2])
with left:
    st.subheader(p["title"])
    st.markdown(f"**Angle:** {p['angle']} · **Duration:** {p['total_duration_s']}s · **Score:** {p['total_score']}/100 · "
                f"**Score rank:** {p.get('rank', '—')} · **Editorial priority:** {p.get('editorial_priority') or '—'} · "
                f"**Confidence:** {p['confidence']} · **Status:** {p['status']}"
                + (f" · alternate of **{p['duplicate_of']}**" if p.get("duplicate_of") else ""))
    st.markdown(f"**Hook** (starts {p['checks'].get('hook_offset_s')}s in): {p['hook']}")
    st.markdown(f"**Cliffhanger:** {p['cliffhanger']}")
    st.markdown(f"**Why it works:** {p['why_it_works']}")
    st.markdown(f"**Standalone context:** {p['standalone_context']}")
    if p.get("why_combine"):
        st.markdown(f"**Why these segments together:** {p['why_combine']}")
    if p.get("concerns"):
        st.markdown(f"**Editorial concerns:** {p['concerns']}")
    if p["segments"]:
        st.dataframe(pd.DataFrame([{"#": s["order"], "episode": s["episode"], "start": s["start"], "end": s["end"],
                                    "duration_s": s["duration_s"], "start evidence": s["boundary_evidence"]["start"],
                                    "end evidence": s["boundary_evidence"]["end"]} for s in p["segments"]]),
                     hide_index=True)
    for s in p["segments"]:
        with st.expander(f"Segment {s['order']} source lines (Ep{s['episode']} {s['start']}–{s['end']})"):
            st.code("\n".join(s["source_evidence"]) or "(no dialogue/action lines)")
            if s["boundary_notes"]:
                st.caption("Boundary adjustments: " + "; ".join(s["boundary_notes"]))
with right:
    st.bar_chart(pd.DataFrame({"score": p["scores"], "max": p["score_max"]}))
    st.json(p["checks"])
    for w in p.get("warnings", []):
        st.warning(w)
    for e in p.get("rejection_reasons", []):
        st.error(e)

st.subheader("Editor decision")
rv = ss.reviews.get(p["id"], {})
opts = ["approve", "needs edit", "reject"]
dec = st.radio("Decision", opts, horizontal=True, index=opts.index(rv.get("decision", "approve")), key=f"d_{p['id']}")
notes = st.text_area("Notes", rv.get("notes", ""), key=f"n_{p['id']}")
if idx is not None:
    # a toggle (not an expander) so the section stays open across the rerun that Re-validate triggers
    if st.toggle("Adjust boundaries (event IDs) and re-validate", key=f"t_{p['id']}"):
        seg_txt = st.text_input("Segments as START..END, comma separated",
                                ", ".join(f"{s['start_event']}..{s['end_event']}" for s in p["segments"]), key=f"s_{p['id']}")
        h = st.text_input("Hook event", p.get("hook_event") or "", key=f"h_{p['id']}")
        c = st.text_input("Cliffhanger event", p.get("cliffhanger_event") or "", key=f"c_{p['id']}")
        if st.button("Re-validate", key=f"v_{p['id']}"):
            try:
                segs = [{"start_event": a.strip(), "end_event": b.strip()} for a, b in
                        (x.split("..", 1) for x in seg_txt.split(",") if ".." in x)]
                ss[f"adj_{p['id']}"] = {"segments": segs, "hook_event": h, "cliffhanger_event": c,
                                        "result": validate_candidate(idx, {"segments": segs, "hook_event": h,
                                                                           "cliffhanger_event": c, "scores": p["scores"]})}
            except Exception as ex:
                st.error(f"Could not re-validate: {ex}")
        a = ss.get(f"adj_{p['id']}")
        if a:
            r = a["result"]
            st.write(f"Adjusted total: **{r['total_duration_s']}s**, eligible: **{r['eligible']}**")
            if r["segments"]:
                st.dataframe(pd.DataFrame([{k: s[k] for k in ("order", "episode", "start", "end", "duration_s")}
                                           for s in r["segments"]]), hide_index=True)
            for e in r["errors"]:
                st.error(e)
            for w in r["warnings"]:
                st.warning(w)
        ep_no = st.number_input("Inspect episode timeline", 1, 9999, p["segments"][0]["episode"] if p["segments"] else 1)
        ep = idx.episodes.get(int(ep_no))
        st.code("\n".join(event_line(e, 140) for e in ep.events) if ep else "Episode not in this ZIP.", language=None)
else:
    st.caption("Load the matching screenplay ZIP to adjust boundaries and inspect timelines.")
if st.button("Save decision", type="primary"):
    ss.reviews[p["id"]] = {"decision": dec, "notes": notes, "reviewed_at": time.strftime("%Y-%m-%d %H:%M"),
                           "adjusted": {k: v for k, v in (ss.get(f"adj_{p['id']}") or {}).items() if k != "result"} or None}
    st.success(f"Saved decision for {p['id']}.")

# ---------------------------------------------------------------- export
st.header("5 · Export")
merged = []
for q in ranked:
    q2 = dict(q)
    r = ss.reviews.get(q["id"], {})
    q2["editor_decision"], q2["editor_notes"] = r.get("decision", ""), r.get("notes", "")
    merged.append(q2)
c1, c2, c3 = st.columns(3)
c1.download_button("Ranking JSON", json.dumps({**res, "ranked_promos": merged, "editor_reviews": ss.reviews}, indent=1),
                   "final_promo_ranking.json", "application/json")
c2.download_button("Ranking CSV", to_csv(merged), "final_promo_ranking.csv", "text/csv")
c3.download_button("Alternates + near-misses CSV", to_csv(res.get("alternates", []) + res.get("near_misses", [])),
                   "alternates_and_near_misses.csv", "text/csv")
