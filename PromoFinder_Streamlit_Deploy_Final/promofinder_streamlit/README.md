# PromoFinder — AI-Powered Microdrama Promo Discovery

PromoFinder reads a ZIP of microdrama screenplays (one `.txt` per episode, in the format described below) and proposes **20–60 second promo clips**. Each clip:

- opens on a **hook within the first 3 seconds**
- ends on a **cliffhanger**
- should make sense to someone who has never seen the show

For every clip you get the episode number(s), the **exact source timestamps** of each segment, the hook, the cliffhanger, a score breakdown, and any validation warnings. An editor then approves, rejects or adjusts each clip, and exports the result as CSV or JSON.

```
ZIP ─► upload checks ─► parser ─► ID'd timeline ─► LLM stage 1 (per episode) ─► validator ─► LLM repair (once)
        export ◄─ editor review ◄─ rank ◄─ dedupe ◄─ validator ◄─ LLM stage 2 (show-wide)
```

**AI vs code.** The LLM only judges which moments are strong and why. It refers to moments by **event ID** (e.g. `E3-047`) and never writes a timestamp. Deterministic Python does the rest:

- turns IDs into source timestamps and snaps boundaries to shot cuts without clipping dialogue
- adds up segment durations, excluding the gaps between segments
- checks that the hook starts ≤3.0s into the assembled promo and that the cliffhanger is at the end
- checks that every quoted line actually occurs inside the clip
- removes duplicates and ranks the clips

## Try it

- **One-click demo:** press **▶ Run synthetic demo**. It uses an original 3-episode show (`demo_data/`) and needs no API key.
  - The default demo replays **saved example LLM responses** written for this demo, and is labelled *offline replay*.
  - The heuristic demo shows the no-LLM fallback, labelled *unverified*.
- **Your own ZIP:** upload it. It is checked before parsing (see below).
  - With no LLM configured on the server, it runs in **heuristic mode**. This only scores keywords and punctuation and is clearly labelled as an unverified shortlist, not an LLM analysis.
- **Saved results:** open *View a saved result file* to load a `final_promo_ranking.json`. Add the matching ZIP to inspect timelines and re-validate boundaries.

## Run locally

```bash
pip install -r requirements.txt          # Python 3.11+ (tested on 3.13)
streamlit run app.py                     # http://localhost:8501
pip install -r requirements-dev.txt && python -m pytest -q tests    # 32 tests
```

Command line:

```bash
python -m promofinder.cli validate --zip show.zip
python -m promofinder.cli run --zip show.zip --out runs/show --provider heuristic
python -m promofinder.cli run --zip show.zip --out runs/show --provider openai     # key from .env / environment
python -m promofinder.cli run --zip show.zip --out runs/show --provider file --responses saved_responses/   # offline replay
python -m promofinder.cli inspect --zip show.zip --episode 3 --start 00:58 --end 01:30
```

Set `PROMOFINDER_LOCAL_MODE=1` (in `.env`) to enable the local-only feature that replays saved LLM responses **from a folder on your computer**. This feature is off on public deployments.

## Model configuration (server-side only)

Keys are **never** entered in the web page. Configure them in Streamlit Community Cloud → *Settings → Secrets*, or in a local `.env`. See `.streamlit/secrets.toml.example`.

| Setting | Meaning |
|---|---|
| `PROMOFINDER_PROVIDER` | `openai` (any OpenAI-compatible endpoint: OpenAI, Gemini, Groq, OpenRouter, Ollama) or `anthropic` |
| `PROMOFINDER_MODEL` | model name, e.g. `gemini-2.5-flash` (example; check your provider's current model names) |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | for `openai` |
| `ANTHROPIC_API_KEY` | for `anthropic` |
| `PROMOFINDER_ACCESS_CODE` | recommended: visitors must enter this code before a live LLM run, so strangers can't spend your quota |
| `PROMOFINDER_MAX_LLM_EPISODES` | cap on episodes per live run (default 60) |

Settings are passed to the provider explicitly and are never written into the shared process environment, so visitors can't see or affect each other's configuration.

To add another provider, write one class with `_call(prompt) -> (text, usage)` in `promofinder/providers.py`. Rate-limit and overload errors are retried with backoff.

**Data sharing:** when a live LLM is configured and used, the uploaded screenplay text is sent to that provider, and the app says so before you run.

**Testing status:** the live provider code has been tested end-to-end against a local mock API (`tests/mock_llm_server.py`). It has not been tested against a real paid or free API from this environment.

## Upload safety and privacy

Uploaded ZIPs are:

- rejected if they are larger than 20 MB, have more than 400 entries or more than 300 episode files, contain non-`.txt` files (macOS `__MACOSX`/`.DS_Store` junk is ignored), or contain absolute/`..` paths (zip-slip), symlinks, encrypted members or zip-bomb compression ratios
- read **in memory** and never extracted to disk

Run files are written to a temporary server folder that is deleted when the run finishes. Results stay in the visitor's browser session until the tab is closed. Stack traces are hidden from visitors (`.streamlit/config.toml`).

This is a demo deployment. **Don't upload confidential scripts to a public instance**; run PromoFinder locally for those.

## Scoring

Each clip gets an editorial heuristic score out of 100. It is **not** a prediction of views or click-through rate.

| Component | Max points | Minimum to qualify |
|---|---|---|
| Hook | 25 | 15 |
| Cliffhanger | 25 | 15 |
| Standalone (makes sense to a new viewer) | 20 | 12 |
| Emotion | 15 | – |
| Visual / dialogue | 10 | – |
| Distinctiveness | 5 | – |

A clip also has to pass every hard check (duration, hook timing, cliffhanger position, quotes). Clips that fail become **near-misses**, listed with the reason. Clips that reuse another promo's footage become **alternates**.

**Score rank** and **editorial priority** (the separate publish-first pick, 1–5) are shown separately because they can differ.

## Screenplay format

```
EPISODE NUMBER: Episode 1
EPISODE LOGLINE: ...
CONTINUITY NOTES: ...
--- SCRIPT START ---
SCENE 01
Scene heading: INT. BALLROOM – NIGHT
Scene start: 00:00.00
Scene end: 00:44.00
Actions and dialogue:
**CAMERA:**
Start: (00:00.00) | End: (00:03.00)
Wide shot ...
**VIVIAN (Icy):**
Start: (00:03.20) | End: (00:05.80)
"Stop right there."
--- SCRIPT END ---
```

Timestamps are episode-relative `MM:SS.ss`. Upper-case scene headers (`SCENE START:`) are also accepted.

## Layout

```
app.py                      Streamlit UI (demo, upload, results, editor review, export)
promofinder/upload.py       ZIP safety checks
promofinder/parser.py       screenplay parser + dataset report
promofinder/validate.py     timestamp, duration, hook, cliffhanger and quote checks
promofinder/pipeline.py     orchestration, repair loop, dedupe, ranking
promofinder/providers.py    anthropic | openai-compatible | file (replay) | heuristic
promofinder/settings.py     server-side secrets/env loading
promofinder/heuristic.py    no-LLM fallback (labelled unverified)
promofinder/prompts.py      prompts and rubric
promofinder/demo.py         synthetic demo show generator
promofinder/export.py, cli.py, timeline.py
demo_data/                  synthetic show ZIP + saved example LLM responses (no client content)
tests/                      32 tests + mock LLM API server
```
