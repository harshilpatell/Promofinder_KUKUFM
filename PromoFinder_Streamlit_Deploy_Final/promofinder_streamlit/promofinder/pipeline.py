"""PromoFinder pipeline.

ZIP -> parse -> timeline -> [stage 1: per-episode LLM discovery] -> validate -> [repair]
    -> [stage 2: show-wide LLM: cross-episode promos, dedupe, distinctiveness, top-5]
    -> validate -> dedupe -> rank -> export (+ human review in the app)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import __version__
from .heuristic import candidates_for_episode
from .parser import load_zip, dataset_report
from .prompts import stage1_prompt, stage2_prompt, repair_prompt
from .providers import get_provider, parse_json, MissingResponse
from .timeline import episode_timeline, event_line
from .validate import Index, validate_candidate, SCORE_MAX, THRESH

FIXABLE = ("total duration", "hook starts at", "continues", "not in the last segment",
           "not inside the promo", "overlap", "segments (max")
CAND_KEYS = ["title", "angle", "segments", "hook_event", "hook_quote", "hook", "cliffhanger_event",
             "cliffhanger", "standalone_context", "why_it_works", "why_combine", "scores",
             "confidence", "concerns"]


class Run:
    def __init__(self, out_dir, provider_name="heuristic", responses_dir=None, show_title=None,
                 log=print, repair=True, provider_config=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.provider_name = provider_name
        self.responses_dir = Path(responses_dir) if responses_dir else self.out / "llm_responses"
        self.provider = get_provider(provider_name, self.responses_dir, self.out / "llm_prompts", provider_config)
        self.mode = "heuristic" if self.provider is None else "llm"
        # honest provenance label: a replay of saved responses is never presented as a live model call
        self.llm_source = ("none (heuristic)" if self.provider is None else
                           "offline replay of saved responses" if self.provider.name == "file" else
                           f"live call: {self.provider.name}:{self.provider.model}")
        self.show_title = show_title
        self.log = log
        self.repair = repair
        self.missing = []
        self.meta = {"promofinder_version": __version__, "mode": self.mode, "provider": provider_name,
                     "llm_source": self.llm_source,
                     "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # ---------- helpers ----------
    def _save(self, name, obj):
        p = self.out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
        return p

    def _ask(self, prompt_id, prompt):
        try:
            text, _ = self.provider.complete(prompt_id, prompt)
        except MissingResponse as m:
            self.missing.append(m.prompt_id)
            return None
        try:
            return parse_json(text)
        except Exception as ex:  # malformed model output is logged, not hidden
            self.log(f"  ! {prompt_id}: could not parse JSON ({ex})")
            return {"_parse_error": str(ex), "_raw": text[:2000]}

    # ---------- main ----------
    def execute(self, zip_source):
        t0 = time.time()
        episodes, file_report = load_zip(zip_source)
        if not episodes:
            raise ValueError("No screenplay episodes could be parsed from this ZIP.")
        report = dataset_report(episodes, file_report)
        self._save("dataset_report.json", report)
        self.log(f"Parsed {report['txt_files_parsed']} files, {report['unique_episodes']} episodes, "
                 f"{report['total_events']} events. Missing={report['missing_episodes']} Dups={report['duplicate_episodes']}")
        if not self.show_title:
            names = [f["file"].split("/")[0] for f in file_report if "/" in f["file"]]
            self.show_title = names[0] if names else "Untitled show"
        self.meta["show_title"] = self.show_title
        self.idx = Index(episodes)
        self.episodes = episodes
        for ep in episodes:
            self._save(f"timelines/ep{ep.number:03d}.json", ep.to_dict())

        if self.mode == "heuristic":
            stage1 = self._stage1_heuristic()
            stage2 = {}
        else:
            stage1 = self._stage1_llm()
            if self.missing:
                return self._awaiting("stage1")
            if self.repair:
                self._repair(stage1)
                if self.missing:
                    return self._awaiting("repair")
            stage2 = self._stage2_llm(stage1)
            if self.missing:
                return self._awaiting("stage2")
        result = self._finalise(stage1, stage2)
        self.meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.meta["wall_time_s"] = round(time.time() - t0, 2)
        if self.provider:
            calls = self.provider.calls
            self.meta["llm_calls"] = len(calls)
            self.meta["llm_calls_cached"] = sum(1 for c in calls if c.get("cached"))
            self.meta["prompt_chars_total"] = sum(c["prompt_chars"] for c in calls)
            self.meta["approx_input_tokens"] = self.meta["prompt_chars_total"] // 4
            self.meta["produced_by"] = sorted({c.get("produced_by", "?") for c in calls})
            self._save("llm_call_log.json", calls)
        self._save("run_metadata.json", self.meta)
        return result

    def _awaiting(self, stage):
        self.meta["status"] = f"awaiting_responses ({stage})"
        self.meta["missing_responses"] = self.missing
        self._save("run_metadata.json", self.meta)
        self.log(f"Awaiting {len(self.missing)} LLM responses for {stage}. Prompts in {self.out/'llm_prompts'}; "
                 f"put <prompt_id>.json files in {self.responses_dir} and re-run.")
        return {"status": "awaiting_responses", "stage": stage, "missing": self.missing}

    # ---------- stage 1 ----------
    def _stage1_heuristic(self):
        out = {}
        for ep in self.episodes:
            cands = candidates_for_episode(ep)
            out[ep.number] = {"episode": ep.number, "episode_summary": ep.logline,
                              "story_facts": [], "candidates": cands, "rejected_moments": []}
        self._save("stage1_episode_analysis.json", out)
        return out

    def _stage1_llm(self):
        out = {}
        prior = []
        for ep in self.episodes:
            prompt = stage1_prompt(self.show_title, episode_timeline(ep), "\n".join(prior))
            prior.append(f"Ep{ep.number}: {ep.logline}")
            pid = f"stage1_ep{ep.number:03d}"
            r = self._ask(pid, prompt)
            if r is None:
                continue
            if "_parse_error" in r:
                r = {"episode": ep.number, "candidates": [], "error": r}
            out[ep.number] = r
            self.log(f"  stage1 ep{ep.number}: {len(r.get('candidates', []))} candidates")
        self._save("stage1_episode_analysis.json", out)
        return out

    # ---------- validation / repair ----------
    def _all_candidates(self, stage1):
        for epn, r in sorted(stage1.items(), key=lambda kv: int(kv[0])):
            for n, c in enumerate(r.get("candidates", []), 1):
                c.setdefault("id", f"C{int(epn):02d}-{n}")
                yield int(epn), c

    def _window_text(self, cand, pad=25.0):
        eps = {}
        for s in cand.get("segments", []):
            for key in ("start_event", "end_event"):
                ev = self.idx.get(s.get(key))
                if ev:
                    lo, hi = eps.get(ev.episode, (1e9, -1))
                    eps[ev.episode] = (min(lo, ev.start_s), max(hi, ev.end_s))
        lines = []
        for epn, (lo, hi) in eps.items():
            ep = self.idx.episodes[epn]
            lines.append(f"EPISODE {epn}")
            lines += [event_line(e) for e in ep.events if lo - pad <= e.start_s <= hi + pad]
        return "\n".join(lines)

    def _repair(self, stage1):
        log = []
        for epn, c in list(self._all_candidates(stage1)):
            v = validate_candidate(self.idx, c)
            if v["eligible"] or not any(any(f in e for f in FIXABLE) for e in v["errors"]):
                continue
            pid = f"repair_{c['id']}"
            r = self._ask(pid, repair_prompt({k: c.get(k) for k in CAND_KEYS if k in c},
                                             v["errors"], self._window_text(c)))
            if r is None:
                continue
            entry = {"candidate_id": c["id"], "errors_before": v["errors"],
                     "original": {k: c.get(k) for k in ("segments", "hook_event", "cliffhanger_event")}}
            if r.get("unfixable") or "_parse_error" in r:
                entry["result"] = "unfixable"
                entry["reason"] = r.get("reason", r.get("_parse_error"))
            else:
                for k in ("segments", "hook_event", "hook_quote", "cliffhanger_event", "hook", "cliffhanger", "scores", "concerns"):
                    if k in r:
                        c[k] = r[k]
                c["repaired"] = True
                v2 = validate_candidate(self.idx, c)
                entry["result"] = "fixed" if v2["eligible"] else "still_failing"
                entry["errors_after"] = v2["errors"]
            log.append(entry)
        self._save("repair_log.json", log)
        self._save("stage1_episode_analysis_after_repair.json", stage1)

    # ---------- stage 2 ----------
    def _stage2_llm(self, stage1):
        summaries, comp, keys = [], [], []
        for epn, r in sorted(stage1.items(), key=lambda kv: int(kv[0])):
            facts = "; ".join(r.get("story_facts", []))
            summaries.append(f"Ep{epn}: {r.get('episode_summary', '')} | facts: {facts}")
        seen = set()
        for epn, c in self._all_candidates(stage1):
            v = validate_candidate(self.idx, c)
            comp.append(f"{c['id']} | ep{epn} | {c.get('title')} | {c.get('angle')} | {v['total_duration_s']}s | "
                        f"hook: {c.get('hook_quote', '')[:60]} | cliff: {c.get('cliffhanger', '')[:70]} | "
                        f"scores {v['scores']} | {'eligible' if v['eligible'] else 'near-miss: ' + '; '.join(v['rejection_reasons'])[:120]}")
            for s in v["segments"]:
                for eid in s["event_ids"]:
                    ev = self.idx.get(eid)
                    if eid not in seen and ev.kind in ("DIALOGUE", "ACTION", "SOUND"):
                        seen.add(eid)
                        keys.append(event_line(ev))
        prompt = stage2_prompt(self.show_title, "\n".join(summaries), "\n".join(comp), "\n".join(keys))
        r = self._ask("stage2_show", prompt)
        if r is not None:
            self._save("stage2_show_analysis.json", r)
        return r or {}

    # ---------- finalise ----------
    def _finalise(self, stage1, stage2):
        rows = []
        for epn, c in self._all_candidates(stage1):
            rows.append(self._row(c, "episode"))
        for n, c in enumerate(stage2.get("cross_episode_promos", []) or [], 1):
            c.setdefault("id", f"X{n}")
            rows.append(self._row(c, "cross_episode"))
        # show-wide distinctiveness override
        for cid, d in (stage2.get("distinct_scores") or {}).items():
            for r in rows:
                if r["id"] == cid:
                    r["llm_scores"]["distinct"] = d
                    r.update(self._validated(r["_cand"] | {"scores": r["llm_scores"]}, r["level"], keep=r))
        # dedupe = greedy non-max suppression. Two promos "clash" if the LLM put them in the same
        # duplicate group OR they share >40% of the shorter segment's footage. Walk eligible promos
        # best-first; a promo that clashes with an already-accepted one becomes its alternate.
        # (Greedy, not union-find: union-merging would chain distinct beats together through a
        # cross-episode promo that happens to overlap both.)
        same_beat = set()
        for g in (stage2.get("duplicate_groups") or []):
            for a in g:
                for b in g:
                    if a != b:
                        same_beat.add((a, b))
        accepted = []
        for r in sorted(rows, key=lambda r: (not r["eligible"], -r["total_score"])):
            if not r["eligible"]:
                continue
            clash = next((a for a in accepted if (r["id"], a["id"]) in same_beat or self._overlap(r, a) > 0.4), None)
            if clash:
                r["duplicate_of"] = clash["id"]
            else:
                accepted.append(r)
        top5 = {t.get("candidate_id"): t for t in (stage2.get("publication_top5") or [])}
        order = {t.get("candidate_id"): i for i, t in enumerate(stage2.get("publication_top5") or [], 1)}
        ranked = [r for r in rows if r["eligible"] and not r.get("duplicate_of")]
        ranked.sort(key=lambda r: (-r["total_score"], -r["scores"]["hook"], -r["scores"]["cliffhanger"]))
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
            r["priority"] = "High" if r["total_score"] >= 80 else "Medium" if r["total_score"] >= 70 else "Low"
            r["publication_pick"] = top5.get(r["id"])
            # editorial publication priority (1-5) is a separate judgement from the score rank
            r["editorial_priority"] = order.get(r["id"], "")
        alternates = [r for r in rows if r.get("duplicate_of")]
        near = [r for r in rows if not r["eligible"] and not r.get("duplicate_of")]
        for r in rows:
            r.pop("_cand", None)
        result = {"status": "complete", "mode": self.mode, "llm_source": self.llm_source,
                  "show_title": self.show_title,
                  "ranked_promos": ranked, "alternates": alternates, "near_misses": near,
                  "show_summary": stage2.get("show_summary", ""),
                  "portfolio_note": stage2.get("portfolio_note", ""),
                  "publication_top5": stage2.get("publication_top5", [])}
        self._save("validation_results.json", rows)
        from .export import export_all
        export_all(result, self.out)
        self.meta["counts"] = {"candidates_total": len(rows), "qualified": len(ranked),
                               "alternates": len(alternates), "near_misses": len(near)}
        self.log(f"Done: {len(ranked)} qualified promos, {len(alternates)} alternates, {len(near)} near-misses")
        return result

    def _row(self, c, level):
        return self._validated(c, level)

    def _validated(self, c, level, keep=None):
        v = validate_candidate(self.idx, c)
        eligible = v["eligible"]
        status = "qualified" if eligible else "near_miss"
        if self.mode == "heuristic":
            # standalone cannot be judged without semantics: never auto-qualify on it
            core_ok = (not v["errors"] and v["checks"]["duration_20_60"] and v["checks"]["hook_within_3s"]
                       and v["checks"]["ends_on_cliffhanger"]
                       and v["scores"]["hook"] >= THRESH["hook"] and v["scores"]["cliffhanger"] >= THRESH["cliffhanger"])
            eligible = core_ok
            status = "heuristic_shortlist_unverified" if core_ok else "near_miss"
        conf = (c.get("confidence") or "medium").lower()
        levels = ["low", "medium", "high"]
        li = levels.index(conf) if conf in levels else 1
        risky = [w for w in v["warnings"] if "mid-shot" in w or "cuts" in w or "paraphrased" in w]
        if len(risky) >= 1:
            li = max(0, li - 1)
        row = {
            "id": c.get("id"), "level": level, "status": status, "eligible": eligible,
            "title": c.get("title"), "angle": c.get("angle"),
            "episodes": sorted({s["episode"] for s in v["segments"]}),
            "total_duration_s": v["total_duration_s"], "segments": v["segments"],
            "hook_event": c.get("hook_event"), "hook_quote": c.get("hook_quote"), "hook": c.get("hook"),
            "cliffhanger_event": c.get("cliffhanger_event"), "cliffhanger": c.get("cliffhanger"),
            "standalone_context": c.get("standalone_context"), "why_it_works": c.get("why_it_works"),
            "why_combine": c.get("why_combine", ""), "concerns": c.get("concerns", ""),
            "llm_scores": dict(c.get("scores") or {}), "scores": v["scores"], "total_score": v["total_score"],
            "score_max": SCORE_MAX, "confidence": levels[li],
            "checks": v["checks"], "errors": v["errors"], "warnings": v["warnings"],
            "rejection_reasons": v["rejection_reasons"], "repaired": bool(c.get("repaired")),
            "_cand": c,
        }
        if keep is not None:
            row = {k: row[k] for k in ("scores", "total_score", "eligible", "status", "checks", "llm_scores")}
        return row

    @staticmethod
    def _overlap(a, b):
        best = 0.0
        for s in a["segments"]:
            for t in b["segments"]:
                if s["episode"] != t["episode"]:
                    continue
                inter = min(s["end_s"], t["end_s"]) - max(s["start_s"], t["start_s"])
                if inter > 0:
                    best = max(best, inter / min(s["duration_s"], t["duration_s"]))
        return best
