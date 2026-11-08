# Deploy PromoFinder to Streamlit Community Cloud (free)

You need a GitHub account and about 10 minutes. No API key or payment is needed: the default app runs the synthetic demo and heuristic mode.

## 0. Before you start: what goes public and what never does

**Upload ONLY the contents of `PromoFinder_Streamlit_Deploy_Final.zip`:**

```
app.py   requirements.txt   requirements-dev.txt   README.md   DEPLOY_TO_STREAMLIT.md
.gitignore   .env.example   .streamlit/config.toml   .streamlit/secrets.toml.example
promofinder/   (all .py files)
demo_data/     (synthetic_show.zip, synthetic_llm_responses/, README.md)
tests/
```

**NEVER upload (to GitHub or the app):**
- the Kuku screenplay ZIP or any extracted episode `.txt` files
- `PromoFinder_Submission_Final_CONFIDENTIAL.zip` or anything from it: `raw_outputs/`, `llm_responses/`, `llm_prompts/`, `timelines/`, the real `final_promo_ranking.json/.csv`, `promo_analysis_report.md`, and so on
- `.env`, `.streamlit/secrets.toml`, or any API key

`.gitignore` blocks the usual names, but GitHub's web uploader does **not** apply `.gitignore`. Check the file list yourself before committing.

## 1. Create a public GitHub repository

1. Go to https://github.com/new
2. **Repository name:** `promofinder` (or any name). **Visibility:** **Public**. Leave "Add a README" **unticked**. Click **Create repository**.

## 2. Upload the project files

**Option A: web browser (no git needed)**

1. Unzip `PromoFinder_Streamlit_Deploy_Final.zip` on your computer. You get a folder `promofinder_streamlit/`.
2. On the empty repository page, click **"uploading an existing file"**.
3. Open the `promofinder_streamlit/` folder and select **everything inside it** (not the folder itself). Drag it into the browser. Folders such as `promofinder/`, `demo_data/` and `tests/` upload with their contents.
   - **Hidden files:** `.gitignore`, `.env.example` and the `.streamlit/` folder start with a dot.
     - On macOS, press **Cmd + Shift + .** in Finder to show them.
     - On Windows, tick **View → Hidden items**.
   - Make sure `.streamlit/config.toml` is uploaded. It sets the 20 MB upload limit and hides stack traces.
4. Check that the list shows `app.py` and `requirements.txt` at the **top level**, not inside a `promofinder_streamlit/` subfolder. Then click **Commit changes**.

**Option B: git command line**

```bash
cd promofinder_streamlit
git init && git add . && git status        # review: no secrets, no client files
git commit -m "PromoFinder public demo"
git branch -M main
git remote add origin https://github.com/<your-username>/promofinder.git
git push -u origin main
```

## 3. Create the Streamlit app

1. Go to https://share.streamlit.io/ and click **Continue with GitHub**. Authorise Streamlit to read your repositories.
2. Click **Create app** → **Deploy a public app from GitHub** (or "Yup, I have an app").
3. Fill in:
   - **Repository:** `<your-username>/promofinder`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** choose a subdomain, e.g. `promofinder-<yourname>`
4. Open **Advanced settings**:
   - **Python version:** **3.12** (or 3.13). pandas 3.x needs Python ≥ 3.11. The project was tested on 3.13.
   - **Secrets:** leave **empty** for the free demo. See step 4 for optional model keys.
5. Click **Deploy**. The first build installs `requirements.txt` and takes about 2–5 minutes.

## 4. Optional: connect a real LLM (server-side secret)

In your app → **⋮ → Settings → Secrets**, paste TOML like this. Use your own values and never commit them.

```toml
PROMOFINDER_PROVIDER = "openai"
PROMOFINDER_MODEL = "gemini-2.5-flash"     # example; check the current model names in Google AI Studio
OPENAI_API_KEY = "your-gemini-key"
OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
PROMOFINDER_ACCESS_CODE = "pick-a-code"     # strongly recommended on a public URL
PROMOFINDER_MAX_LLM_EPISODES = "60"
```

Save the secrets. The app restarts and the sidebar shows "LLM configured on the server". Visitors need the access code to start a live run. When a live run is used, the uploaded screenplay text is sent to that provider.

**Not yet verified:** the live call has only been tested against a mock API, not a real provider. Run one small test (the synthetic ZIP from the demo's download button) before relying on it.

## 5. Test the public URL

Open the URL in a **private/incognito** window and check:

1. The title "PromoFinder — AI-Powered Microdrama Promo Discovery" loads, and the sidebar says "No LLM configured…" (or "LLM configured…" if you added secrets).
2. **▶ Run synthetic demo (saved example LLM responses)** shows **2 qualified promos · 1 alternate · 1 near-miss**, with source "offline replay of saved responses".
3. **▶ Run synthetic demo (heuristic)** shows the yellow "HEURISTIC RESULTS" warning and 0 qualified / 3 near-misses.
4. Click **Download the synthetic demo ZIP**, upload that file, then click **2 · Find promos**. You should see results with episode counts.
5. Upload a non-ZIP file renamed to `.zip`. You should see "This file is not a valid ZIP archive."
6. Click **Ranking CSV** and **Ranking JSON** and check that both files download.
7. Copy this URL into your submission form as the **Prototype link**.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'promofinder'` | The `promofinder/` folder (with `__init__.py`) must be at the repo's top level, next to `app.py`. Don't nest everything inside `promofinder_streamlit/`. |
| `No matching distribution found for pandas==3.0.5` (or another pin) | Python version is too old. Set it to 3.12 in Advanced settings: delete the app and redeploy, since the Python version can't be changed afterwards. As a last resort, relax the pins in `requirements.txt` (e.g. `streamlit>=1.40`, `pandas>=2.2`). |
| `ModuleNotFoundError` for streamlit/pandas | `requirements.txt` must be at the repo root, and the file name must be exact. |
| App shows "Oh no." / a generic error | **Manage app** (bottom-right) → **Logs** shows the real error. Stack traces are hidden from visitors on purpose. |
| Upload limit is 200 MB instead of 20 MB | `.streamlit/config.toml` wasn't uploaded (hidden folder). Upload it. The app still enforces 20 MB in code either way. |
| Secrets not picked up | TOML needs quotes around values. Save, then **Reboot app** from the ⋮ menu. |
| "This app has gone to sleep" | Free apps sleep after inactivity. Click **Yes, get this app back up!** Open the link yourself shortly before evaluators use it. |
| Changes not showing | Commit to `main`. Streamlit redeploys automatically, or use **Reboot app**. |

## 7. Updating later

Edit the files in GitHub (or `git push`) and the app redeploys by itself. Before each commit, check again that no client files or secrets are included.
