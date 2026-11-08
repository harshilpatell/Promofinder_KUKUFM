"""Compact, ID-addressable timeline text that is sent to the LLM.

The LLM never returns raw timestamps; it returns event IDs. Deterministic code
maps IDs back to source timestamps (see validate.py). This is the main guard
against fabricated timestamp precision.
"""
from __future__ import annotations


def event_line(ev, camera_chars: int = 110) -> str:
    if ev.kind == "DIALOGUE":
        d = f" ({ev.direction})" if ev.direction else ""
        body = f'{ev.speaker}{d}: "{ev.text}"'
        tag = "DLG"
    elif ev.kind == "CAMERA":
        t = ev.text if len(ev.text) <= camera_chars else ev.text[:camera_chars].rstrip() + "…"
        body, tag = t, "CAM"
    elif ev.kind == "ACTION":
        body, tag = ev.text, "ACT"
    elif ev.kind == "SOUND":
        body, tag = ev.text, "SFX"
    else:
        body, tag = ev.text, ev.kind[:3]
    return f"{ev.eid} [{ev.start}-{ev.end}] {tag} {body}"


def episode_timeline(ep, camera_chars: int = 110) -> str:
    out = [f"EPISODE {ep.number}  (duration {ep.to_dict()['duration']})",
           f"LOGLINE: {ep.logline}", f"CONTINUITY: {ep.continuity}"]
    by_scene = {}
    for ev in ep.events:
        by_scene.setdefault(ev.scene, []).append(ev)
    for sc in ep.scenes:
        out.append(f"-- SCENE {sc.number}: {sc.heading} [{sc.start}-{sc.end}]")
        for ev in by_scene.get(sc.number, []):
            out.append(event_line(ev, camera_chars))
    return "\n".join(out)
