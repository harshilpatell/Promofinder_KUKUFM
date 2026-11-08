"""Deterministic timestamp / duration / structure validation.

Input: a candidate whose boundaries are event IDs. Output: resolved segments with
source timestamps, evidence, eligibility checks, errors and warnings.
Nothing here uses an LLM.
"""
from __future__ import annotations

import difflib
import re

from .parser import fmt_ts

MIN_S, MAX_S, HOOK_WINDOW_S, CLIFF_WINDOW_S = 20.0, 60.0, 3.0, 3.0
SNAP_TOLERANCE_S = 1.5      # snap a boundary to the nearest shot cut if within this
DIALOGUE_EXTEND_S = 2.0     # auto-extend a boundary to finish a cut dialogue line
MAX_SEGMENTS = 3
SCORE_MAX = {"hook": 25, "cliffhanger": 25, "standalone": 20, "emotion": 15, "visual": 10, "distinct": 5}
THRESH = {"hook": 15, "cliffhanger": 15, "standalone": 12}


class Index:
    def __init__(self, episodes):
        self.episodes = {e.number: e for e in episodes}
        self.events = {}
        self.order = {}
        for e in episodes:
            for i, ev in enumerate(e.events):
                self.events[ev.eid] = ev
                self.order[ev.eid] = i

    def get(self, eid):
        return self.events.get(str(eid).strip())


def _shot_containing(ep, t, for_start=True):
    cams = [c for c in ep.events if c.kind == "CAMERA"]
    for c in cams:
        if for_start and c.start_s <= t < c.end_s:
            return c
        if not for_start and c.start_s < t <= c.end_s:
            return c
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("…", " ").replace("...", " ")).split()


def quote_found(quote, text):
    q, t = " ".join(_norm(quote)), " ".join(_norm(text))
    if not q:
        return True
    if q in t:
        return True
    return difflib.SequenceMatcher(None, q, t).ratio() > 0.75


def resolve_segment(idx: Index, seg: dict, errors: list, warnings: list, n: int):
    a, b = idx.get(seg.get("start_event")), idx.get(seg.get("end_event"))
    if a is None or b is None:
        errors.append(f"segment {n}: unknown event id {seg.get('start_event')}/{seg.get('end_event')}")
        return None
    if a.episode != b.episode:
        errors.append(f"segment {n}: start and end events are in different episodes")
        return None
    ep = idx.episodes[a.episode]
    raw_start, raw_end = a.start_s, b.end_s
    if raw_end <= raw_start:
        errors.append(f"segment {n}: end {b.end} is not after start {a.start}")
        return None
    start, end = raw_start, raw_end
    start_ev, end_ev = a, b
    notes = []
    dlg = [d for d in ep.events if d.kind == "DIALOGUE"]
    # snap start back to the shot cut that contains it, but never into the tail of an earlier line
    c = _shot_containing(ep, start, True)
    if c and 0 < start - c.start_s <= SNAP_TOLERANCE_S:
        if any(d.start_s < start - 0.01 and d.end_s > c.start_s + 0.01 for d in dlg):
            notes.append(f"start kept at {fmt_ts(start)}: snapping to shot {c.eid} would include part of a previous line")
        else:
            notes.append(f"start snapped {fmt_ts(start)}->{c.start} (shot cut {c.eid})")
            start, start_ev = c.start_s, c
    elif c and start - c.start_s > SNAP_TOLERANCE_S:
        warnings.append(f"segment {n}: starts {start - c.start_s:.1f}s into shot {c.eid} (mid-shot cut)")
    # snap end forward to the end of its shot, but never into the start of the next line
    c = _shot_containing(ep, end, False)
    if c and 0 < c.end_s - end <= SNAP_TOLERANCE_S:
        if any(d.start_s > end + 0.01 and d.start_s < c.end_s - 0.01 for d in dlg):
            notes.append(f"end kept at {fmt_ts(end)}: snapping to shot {c.eid} would include part of the next line")
        else:
            notes.append(f"end snapped {fmt_ts(end)}->{c.end} (shot cut {c.eid})")
            end, end_ev = c.end_s, c
    elif c and c.end_s - end > SNAP_TOLERANCE_S:
        warnings.append(f"segment {n}: ends {c.end_s - end:.1f}s before shot {c.eid} ends (mid-shot cut)")
    # dialogue cut through at boundaries
    for d in ep.events:
        if d.kind != "DIALOGUE":
            continue
        if d.start_s < end < d.end_s - 0.05:
            if d.end_s - end <= DIALOGUE_EXTEND_S:
                notes.append(f"end extended {fmt_ts(end)}->{d.end} to finish line {d.eid}")
                end, end_ev = d.end_s, d
            else:
                warnings.append(f"segment {n}: end cuts dialogue {d.eid} '{d.text[:40]}'")
        if d.start_s + 0.05 < start < d.end_s:
            warnings.append(f"segment {n}: start cuts into dialogue {d.eid} '{d.text[:40]}'")
    if end > ep.duration_s + 0.01 or start < 0:
        errors.append(f"segment {n}: outside episode {ep.number} duration {fmt_ts(ep.duration_s)}")
    inside = [e for e in ep.events if e.start_s >= start - 0.01 and e.start_s < end - 0.01]
    evidence = [f"[{e.start}] {e.speaker}: \"{e.text}\"" if e.kind == "DIALOGUE"
                else f"[{e.start}] ({e.kind}) {e.text}" for e in inside if e.kind in ("DIALOGUE", "ACTION", "SOUND")]
    return {
        "order": n, "episode": ep.number,
        "start_event": a.eid, "end_event": b.eid,
        "start": fmt_ts(start), "end": fmt_ts(end),
        "start_s": round(start, 2), "end_s": round(end, 2),
        "duration_s": round(end - start, 2),
        "boundary_evidence": {
            "start": f"{start_ev.eid} {start_ev.kind} starts at {start_ev.start}",
            "end": f"{end_ev.eid} {end_ev.kind} ends at {end_ev.end}"},
        "boundary_notes": notes,
        "opening_beat": evidence[0] if evidence else "",
        "closing_beat": evidence[-1] if evidence else "",
        "source_evidence": evidence,
        "event_ids": [e.eid for e in inside],
    }


def validate_candidate(idx: Index, cand: dict) -> dict:
    errors, warnings = [], []
    segs_in = cand.get("segments") or []
    if not segs_in:
        errors.append("no segments")
    if len(segs_in) > MAX_SEGMENTS:
        errors.append(f"{len(segs_in)} segments (max {MAX_SEGMENTS})")
    segs = []
    for n, s in enumerate(segs_in, 1):
        r = resolve_segment(idx, s, errors, warnings, n)
        if r:
            segs.append(r)
    total = round(sum(s["duration_s"] for s in segs), 2)
    # overlap / order between segments
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            a, b = segs[i], segs[j]
            if a["episode"] == b["episode"] and a["start_s"] < b["end_s"] and b["start_s"] < a["end_s"]:
                errors.append(f"segments {a['order']} and {b['order']} overlap")
    for a, b in zip(segs, segs[1:]):
        if (b["episode"], b["start_s"]) < (a["episode"], a["start_s"]):
            warnings.append(f"segment {b['order']} plays before segment {a['order']} in story order (flashback-style edit)")
    duration_ok = MIN_S <= total <= MAX_S
    if not duration_ok and segs:
        errors.append(f"total duration {total}s outside {MIN_S:.0f}-{MAX_S:.0f}s")
    # hook within first 3s of the ASSEMBLED promo
    hook_ok, hook_offset = False, None
    h = idx.get(cand.get("hook_event"))
    if h is None:
        errors.append(f"hook_event {cand.get('hook_event')} not found")
    elif segs:
        offset = 0.0
        for s in segs:
            if s["episode"] == h.episode and s["start_s"] - 0.01 <= h.start_s < s["end_s"]:
                hook_offset = round(offset + h.start_s - s["start_s"], 2)
                break
            offset += s["duration_s"]
        if hook_offset is None:
            errors.append(f"hook event {h.eid} is not inside the promo")
        elif hook_offset > HOOK_WINDOW_S:
            errors.append(f"hook starts at {hook_offset}s of the promo (must be <= {HOOK_WINDOW_S}s)")
        else:
            hook_ok = True
        q = cand.get("hook_quote", "")
        if h.kind == "DIALOGUE" and q and not quote_found(q, h.text):
            warnings.append(f"hook_quote not found verbatim in {h.eid}: model may have paraphrased")
    # cliffhanger at the end
    cliff_ok, cliff_gap = False, None
    c = idx.get(cand.get("cliffhanger_event"))
    if c is None:
        errors.append(f"cliffhanger_event {cand.get('cliffhanger_event')} not found")
    elif segs:
        last = segs[-1]
        if last["episode"] != c.episode or not (last["start_s"] - 0.01 <= c.start_s < last["end_s"]):
            errors.append(f"cliffhanger event {c.eid} is not in the last segment")
        else:
            cliff_gap = round(last["end_s"] - c.end_s, 2)
            if cliff_gap > CLIFF_WINDOW_S:
                errors.append(f"promo continues {cliff_gap}s after the cliffhanger beat ends (max {CLIFF_WINDOW_S}s)")
            else:
                cliff_ok = True
    # every quoted line in the hook/cliffhanger description must occur inside the promo
    inside_text = [idx.get(e).text for s in segs for e in s["event_ids"] if idx.get(e)]
    for field in ("hook", "cliffhanger"):
        for q in re.findall(r"'([^']{8,}?)'(?=[\s.,;:!?)-]|$)", cand.get(field) or ""):
            frags = [f.strip() for f in re.split(r"\.\.\.|…|(?<=[.!?])\s+", q) if len(f.strip()) >= 6]
            for f in frags:
                if not any(quote_found(f, t) or " ".join(_norm(f)) in " ".join(_norm(t)) for t in inside_text):
                    errors.append(f"{field} quotes '{f[:50]}' but no line inside the promo matches (unverifiable evidence)")
    scores = {k: max(0, min(SCORE_MAX[k], int(round(float((cand.get('scores') or {}).get(k, 0) or 0)))))
              for k in SCORE_MAX}
    total_score = sum(scores.values())
    weak = [k for k, t in THRESH.items() if scores[k] < t]
    eligible = (not errors) and duration_ok and hook_ok and cliff_ok and not weak
    reasons = list(errors) + [f"{k} score {scores[k]} below threshold {THRESH[k]}" for k in weak]
    return {
        "segments": segs, "total_duration_s": total,
        "checks": {"duration_20_60": duration_ok, "hook_within_3s": hook_ok, "hook_offset_s": hook_offset,
                   "ends_on_cliffhanger": cliff_ok, "cliffhanger_gap_s": cliff_gap,
                   "standalone_ok": scores["standalone"] >= THRESH["standalone"],
                   "episodes_valid": all(s["episode"] in idx.episodes for s in segs)},
        "scores": scores, "total_score": total_score,
        "eligible": eligible, "rejection_reasons": reasons,
        "errors": errors, "warnings": warnings,
    }
