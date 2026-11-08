"""Keyword/structure heuristic used when no LLM is configured.

HEURISTIC MODE IS NOT SEMANTIC. It cannot understand who characters are, whether a
moment is a resolution or a cliffhanger in story terms, or whether a clip is
understandable to a new viewer. It scores surface signals (intense words, questions,
exclamations, action density) and is meant as a fallback/first-pass shortlist only.
"""
from __future__ import annotations

import re

HOOK_WORDS = {
    "slap": 6, "strike": 5, "strikes": 5, "blood": 5, "dead": 5, "die": 4, "kill": 6, "poison": 6,
    "arrest": 5, "guards": 4, "witch": 6, "execute": 6, "executed": 6, "gallows": 6, "hang": 5,
    "marry": 4, "marrying": 5, "wedding": 3, "betray": 6, "liar": 4, "lie": 3, "stole": 5,
    "explode": 7, "explodes": 7, "fire": 5, "burn": 5, "crawl": 5, "duke": 4, "secret": 4,
    "who": 2, "remove": 3, "enough": 2, "imposter": 5, "invalid": 5, "chained": 4, "chains": 4,
}
CLIFF_SIGNALS = [(r"\?\s*$", 6), (r"\.\.\.\s*$", 4), (r"!\s*$", 2), (r"cliffhanger", 8),
                 (r"cut(s|ting)? (abruptly )?to black", 5), (r"freezes?", 3), (r"stops? (mere|inches)", 6),
                 (r"bursts? open", 6), (r"someone is coming", 8), (r"shock", 3), (r"gasps?", 2)]
RESOLVE_SIGNALS = [r"fades? (out|to black)", r"peaceful", r"relief", r"smil", r"thank you", r"safe"]


def _intensity(text):
    t = text.lower()
    s = sum(w for k, w in HOOK_WORDS.items() if re.search(rf"\b{k}\b", t))
    s += 2 * t.count("!")
    return s


def candidates_for_episode(ep, max_per_ep=2, min_len=24.0, max_len=55.0):
    evs = [e for e in ep.events if e.kind in ("DIALOGUE", "ACTION", "SOUND")]
    if not evs:
        return []
    windows = []
    for i, a in enumerate(evs):
        hook_pool = [e for e in evs[i:] if e.start_s - a.start_s <= 3.0]
        hook_ev = max(hook_pool, key=lambda e: _intensity(e.text))
        hook_raw = _intensity(hook_ev.text)
        for j in range(i + 1, len(evs)):
            b = evs[j]
            L = b.end_s - a.start_s
            if L < min_len:
                continue
            if L > max_len:
                break
            inside = evs[i:j + 1]
            cliff_raw = sum(w for p, w in CLIFF_SIGNALS if re.search(p, b.text.lower()))
            resolve = sum(3 for p in RESOLVE_SIGNALS if re.search(p, b.text.lower()))
            emo = sum(_intensity(e.text) for e in inside)
            acts = sum(1 for e in inside if e.kind in ("ACTION", "SOUND"))
            scores = {
                "hook": min(25, 5 + hook_raw * 2),
                "cliffhanger": max(0, min(25, 5 + cliff_raw * 2 - resolve)),
                "standalone": 10,  # cannot be judged without semantics: fixed neutral value
                "emotion": min(15, emo // 3),
                "visual": min(10, acts * 2),
                "distinct": 3,
            }
            windows.append((sum(scores.values()), a, b, hook_ev, scores))
    windows.sort(key=lambda w: -w[0])
    picked = []
    for w in windows:
        _, a, b, h, sc = w
        if any(not (b.end_s <= p[1].start_s or a.start_s >= p[2].end_s) for p in picked):
            continue
        picked.append(w)
        if len(picked) >= max_per_ep:
            break
    out = []
    for n, (tot, a, b, h, sc) in enumerate(picked, 1):
        out.append({
            "title": f"Ep{ep.number} heuristic window {n}",
            "angle": "unknown (heuristic)",
            "segments": [{"start_event": a.eid, "end_event": b.eid}],
            "hook_event": h.eid, "hook_quote": h.text[:80],
            "hook": f"High-intensity words near the start: '{h.text[:70]}'",
            "cliffhanger_event": b.eid,
            "cliffhanger": f"Window ends on: '{b.text[:70]}'",
            "standalone_context": "NOT ASSESSED in heuristic mode (fixed 10/20). Editor must judge.",
            "why_it_works": "Surface signals only (keywords, questions, action density).",
            "scores": sc, "confidence": "low",
            "concerns": "Heuristic mode: no story understanding; standalone score is a placeholder.",
        })
    return out
