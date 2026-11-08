# Deployment Test Report: PromoFinder v1.1

**Date:** 2026-11-08 · **Environment:** Linux container, Python 3.13.18, fresh virtualenv · **Browser:** headless Chromium (Playwright)

Every result below comes from a real run. This report does **not** cover anything listed under "Not tested".

## 1. Summary

| Check | Result |
|---|---|
| Clean install `pip install -r requirements-dev.txt` (fresh venv) | ✅ installed: streamlit 1.67.0, pandas 3.0.5, python-dotenv 1.2.3, anthropic 2.6.0, openai 3.46.0, pytest 9.1.1 |
| Compilation `python -m compileall app.py promofinder tests` | ✅ no errors |
| Automated tests `pytest tests` (clean venv) | ✅ **32 passed, 0 failed** |
| Streamlit server start (`streamlit run app.py`) + `/_stcore/health` | ✅ `ok`, with no tracebacks in the server log |
| Browser suite: public app, no secrets | ✅ **18 / 18 passed**, three consecutive runs |
| Browser suite: server-configured LLM against a local mock API + access code | ✅ **4 / 4 passed** |
| Browser suite: load saved full-run results + real ZIP (run locally; confidential data never left the machine) | ✅ **4 / 4 passed** |
| Regression on the real 50-episode pack: v1.1 replay of the saved v1.0 LLM responses | ✅ identical: 32 qualified / 14 alternates / 3 near-misses, same IDs, scores, durations and segment timestamps; dataset still 50 episodes, 100 scenes, 3,727 events, all parsable |

Earlier runs that failed, shown for honesty:
- **Browser check 14:** the re-validation result was hidden because the expander collapsed on rerun. This was a **real app bug**, now fixed (quality audit D3).
- **Browser checks 5 and S3** failed once each because the test read the page before Streamlit finished rendering. These were **test-timing** faults: the app was showing the values. Fixed by waiting for the metric elements, then re-run 3× with all passing.

## 2. Required checks → evidence

| # | Required check | How it was tested | Result |
|---|---|---|---|
| 1 | Clean dependency install | fresh `python -m venv` + `pip install -r requirements-dev.txt` | ✅ |
| 2 | Python compilation | `compileall` | ✅ |
| 3 | All automated tests | 32 tests (22 new in `tests/test_deploy.py`, 10 original) | ✅ 32/32 |
| 4 | Synthetic demo loading | `test_demo_replay_is_labelled_and_complete`, `test_app_starts_and_runs_demo` (Streamlit AppTest), browser checks 4 and 9 | ✅ |
| 5 | Screenplay ZIP extraction | `test_extraction_from_uploaded_bytes` (in-memory, 3 eps / 62 events), browser check 13 (upload + run) | ✅ |
| 6 | Missing episode detection | `test_missing_and_duplicate_episode_detection` (missing = [2]) | ✅ |
| 7 | Duplicate episode detection | same test (duplicates = [1]) | ✅ |
| 8 | Timestamp parsing | `test_timestamps_roundtrip`, `test_timestamp_parsing_and_invalid_values` | ✅ |
| 9 | Invalid timestamps | `00:75.00`, `ab:cd.ef`, `1:2`, empty → rejected; an episode containing one is reported as "Unparsable", not crashed (`test_invalid_timestamp_is_reported_not_crashing`) | ✅ (**found bug D1**: seconds ≥ 60 were accepted. Fixed.) |
| 10 | Duration validation | `test_duration_hook_and_cliffhanger_checks`, `test_multi_segment_duration_excludes_gaps`, `test_too_long…` | ✅ |
| 11 | Hook timing validation | `test_rejects_late_hook…` (hook at > 3 s rejected) | ✅ |
| 12 | Cliffhanger validation | `test_too_long_and_cliffhanger_not_at_end` | ✅ |
| 13 | CSV / JSON export | `test_csv_and_json_exports` (columns, editorial_priority, JSON round-trip); browser checks 7–8 (real downloads) | ✅ |
| 14 | Missing API credentials | `test_missing_credentials_fall_back_safely` (heuristic fallback, clear "not configured" errors); browser checks 2–3 (no key fields, "No LLM configured") | ✅ |
| 15 | Invalid ZIP uploads | non-ZIP, empty, zip-slip (5 path variants), unexpected file type, too large, too many files, zip bomb, no `.txt` (`tests/test_deploy.py`); browser checks 10–12 | ✅ |

## 3. Browser suite details

**Public app, no secrets (script: `raw_outputs/qa/uitest2.js` in the confidential package), 18/18:**
- the app loads
- no key, URL or folder inputs are visible
- the "No LLM configured" status is shown
- the replay demo runs and is labelled *offline replay*
- the episode count and timestamps are displayed
- CSV and JSON downloads work and their content is checked
- the heuristic demo is labelled unverified, with 0 qualified and 3 near-misses
- the invalid-ZIP, zip-slip and `.exe` uploads are rejected with messages
- uploading the user's own ZIP and running it works
- re-validation works
- an editor decision can be saved
- no traceback appears and there are no JavaScript errors

**LLM via mock API (script: `raw_outputs/qa/uitest3.js`), 4/4:**
- the configured provider is shown without the key, and the key string never appears in the page or the server log
- the access code is required and a data-sharing warning is shown
- a run without the code is blocked
- a run with the code is labelled "live LLM call: openai:mock-model"

**Saved results (script: `raw_outputs/qa/uitest4.js`), 4/4:**
- the real `final_promo_ranking.json` loads with 32/14/3
- the recorded source shows "offline replay"
- the metrics show 50 episodes and 3,727 events
- X1 re-validates to 46.0 s against the real script

## 4. Security & confidentiality checks

- `test_repository_contains_no_client_content_or_secrets` scans every file, including inside the demo ZIP, for show-specific names and API-key patterns: **none found**. There is no `.env` and no `.streamlit/secrets.toml`.
- `test_secrets_configure_provider_without_touching_environment`: provider settings never change `os.environ`, which prevents keys leaking between visitors.
- The deploy package was also scanned by hand (see the final review in the delivery notes).

## 5. Not tested (needs you or a real service)

- **Actual deployment to Streamlit Community Cloud** (needs your GitHub and Streamlit accounts). The build there uses its own Python image; the pins were tested only on Python 3.13 here.
- **Real LLM APIs** (Gemini, OpenAI, Groq, Anthropic): no key was available. Only a local mock API was used.
- Windows or macOS local installs, mobile layout, and many simultaneous visitors.
- Performance on shows much larger than 50 episodes.
