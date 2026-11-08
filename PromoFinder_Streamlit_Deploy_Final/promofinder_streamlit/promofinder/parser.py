"""Deterministic screenplay parser.

Turns Kuku-style screenplay TXT files into a structured timeline. No AI here:
every timestamp in the system originates from this module.
Timestamps are episode-relative MM:SS.ss and are kept in their original string
form alongside a float-seconds value used for arithmetic.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Optional

TS_RE = re.compile(r"^(\d{1,2}):(\d{2})\.(\d{1,2})$")
EVENT_HDR_RE = re.compile(r"^\*\*(?P<label>.+?):\*\*\s*$")
START_END_RE = re.compile(
    r"^Start:\s*\((?P<s>[^)]*)\)\s*\|\s*End:\s*\((?P<e>[^)]*)\)\s*$", re.I)
EP_NUM_RE = re.compile(r"^EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", re.I)
FILE_EP_RE = re.compile(r"episode[-_ ]?0*(\d+)", re.I)


def parse_ts(s: str) -> Optional[float]:
    m = TS_RE.match(s.strip())
    if not m:
        return None
    mm, ss, frac = m.groups()
    if int(ss) >= 60:  # MM:SS.ss -> seconds field must be 00-59
        return None
    return int(mm) * 60 + int(ss) + int(frac) / (10 ** len(frac))


def fmt_ts(sec: float) -> str:
    """Format seconds as MM:SS.ss (same as source)."""
    cs = int(round(sec * 100))
    mm, rem = divmod(cs, 6000)
    ss, c = divmod(rem, 100)
    return f"{mm:02d}:{ss:02d}.{c:02d}"


@dataclass
class Event:
    eid: str              # e.g. "E1-037" (episode 1, event 37) — stable ID
    episode: int
    scene: int
    kind: str             # CAMERA | ACTION | DIALOGUE | SOUND | OTHER
    speaker: str          # dialogue speaker ("" otherwise)
    direction: str        # parenthetical, e.g. "Cold, Commanding"
    start: str            # source timestamp string
    end: str
    start_s: float
    end_s: float
    text: str


@dataclass
class Scene:
    number: int
    heading: str
    start: str
    end: str
    start_s: Optional[float]
    end_s: Optional[float]


@dataclass
class Episode:
    number: int
    file_name: str
    logline: str
    continuity: str
    scenes: list = field(default_factory=list)
    events: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        ends = [s.end_s for s in self.scenes if s.end_s is not None]
        ends += [e.end_s for e in self.events]
        return max(ends) if ends else 0.0

    def to_dict(self):
        d = asdict(self)
        d["duration_s"] = round(self.duration_s, 2)
        d["duration"] = fmt_ts(self.duration_s)
        return d


def _kind_for(label: str):
    up = label.upper().strip()
    if up == "CAMERA":
        return "CAMERA", "", ""
    if up == "ACTION":
        return "ACTION", "", ""
    if up.startswith("SOUND"):
        return "SOUND", "", ""
    # dialogue: "SPEAKER (dir)" or "SPEAKER (O.S.) (dir)"
    m = re.match(r"^(?P<spk>[^(]+?)\s*(?P<rest>\(.*\))?\s*$", label)
    spk = (m.group("spk") if m else label).strip()
    rest = (m.group("rest") or "") if m else ""
    parts = re.findall(r"\(([^)]*)\)", rest)
    return "DIALOGUE", spk, ", ".join(p.strip() for p in parts)


def parse_episode_text(text: str, file_name: str = "") -> Episode:
    lines = text.splitlines()
    ep_num, logline, continuity = None, "", ""
    issues = []
    for ln in lines[:15]:
        s = ln.strip()
        m = EP_NUM_RE.match(s)
        if m:
            ep_num = int(m.group(1))
        elif s.upper().startswith("EPISODE LOGLINE:"):
            logline = s.split(":", 1)[1].strip()
        elif s.upper().startswith("CONTINUITY NOTES:"):
            continuity = s.split(":", 1)[1].strip()
    fm = FILE_EP_RE.search(file_name or "")
    file_ep = int(fm.group(1)) if fm else None
    if ep_num is None:
        issues.append("EPISODE NUMBER header missing; used file name")
        ep_num = file_ep if file_ep is not None else -1
    elif file_ep is not None and file_ep != ep_num:
        issues.append(f"Header episode {ep_num} != file-name episode {file_ep}")
    if not logline:
        issues.append("EPISODE LOGLINE missing")
    if not continuity:
        issues.append("CONTINUITY NOTES missing")
    if "SCRIPT START" not in text.upper():
        issues.append("'--- SCRIPT START ---' marker missing")
    if "SCRIPT END" not in text.upper():
        issues.append("'--- SCRIPT END ---' marker missing (possible truncation)")

    ep = Episode(number=ep_num, file_name=file_name, logline=logline,
                 continuity=continuity, issues=issues)
    cur_scene = 0
    pending = None  # (kind, spk, dir)
    pending_ts = None
    buf: list[str] = []
    counter = 0

    def flush():
        nonlocal pending, pending_ts, buf, counter
        if pending is None:
            return
        kind, spk, direc = pending
        body = " ".join(b.strip() for b in buf if b.strip())
        if pending_ts is None:
            ep.issues.append(f"Scene {cur_scene}: {kind} {spk} block without Start/End line")
        else:
            s_str, e_str = pending_ts
            s, e = parse_ts(s_str), parse_ts(e_str)
            if s is None or e is None:
                ep.issues.append(f"Unparsable timestamp '{s_str}'/'{e_str}' in scene {cur_scene}")
            else:
                if e < s:
                    ep.issues.append(f"End before start at {s_str}-{e_str} ({kind})")
                counter += 1
                ep.events.append(Event(
                    eid=f"E{ep_num}-{counter:03d}", episode=ep_num, scene=cur_scene,
                    kind=kind, speaker=spk, direction=direc, start=s_str.strip(),
                    end=e_str.strip(), start_s=s, end_s=e,
                    text=body.strip().strip('"').strip("“”")))
        pending, pending_ts, buf = None, None, []

    scene_hdr = {}
    for raw in lines:
        s = raw.strip()
        up = s.upper()
        if re.match(r"^SCENE\s+\d+\s*$", up):
            flush()
            cur_scene = int(re.findall(r"\d+", up)[0])
            scene_hdr = {"number": cur_scene, "heading": "", "start": "", "end": ""}
            ep.scenes.append(scene_hdr)
            continue
        if up.startswith("SCENE HEADING:"):
            scene_hdr["heading"] = s.split(":", 1)[1].strip(); continue
        if up.startswith("SCENE START:"):
            scene_hdr["start"] = s.split(":", 1)[1].strip(); continue
        if up.startswith("SCENE END:"):
            scene_hdr["end"] = s.split(":", 1)[1].strip(); continue
        if up.startswith("ACTIONS AND DIALOGUE") or up.startswith("--- SCRIPT"):
            flush(); continue
        m = EVENT_HDR_RE.match(s)
        if m:
            flush()
            pending = _kind_for(m.group("label"))
            continue
        m = START_END_RE.match(s)
        if m and pending is not None and pending_ts is None:
            pending_ts = (m.group("s"), m.group("e")); continue
        if pending is not None and s:
            buf.append(s)
    flush()

    scenes = []
    for sh in ep.scenes:
        ss, se = parse_ts(sh["start"]) if sh["start"] else None, parse_ts(sh["end"]) if sh["end"] else None
        if ss is None or se is None:
            ep.issues.append(f"Scene {sh['number']}: missing/unparsable scene start/end")
        scenes.append(Scene(sh["number"], sh["heading"], sh["start"], sh["end"], ss, se))
    ep.scenes = scenes
    if not ep.scenes:
        ep.issues.append("No SCENE blocks found")
    if not ep.events:
        ep.issues.append("No timestamped events found")
    # events outside scene bounds
    for sc in ep.scenes:
        if sc.start_s is None or sc.end_s is None:
            continue
        for ev in ep.events:
            if ev.scene == sc.number and (ev.start_s < sc.start_s - 0.05 or ev.end_s > sc.end_s + 0.05):
                ep.issues.append(f"{ev.eid} [{ev.start}-{ev.end}] outside scene {sc.number} bounds [{sc.start}-{sc.end}]")
    return ep


def load_zip(data: bytes | str):
    """Load every .txt in a ZIP (path or bytes). Returns (episodes, file_report)."""
    zf = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    episodes, report = [], []
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        name = info.filename
        if info.is_dir() or "__MACOSX" in name or name.split("/")[-1].startswith("."):
            continue
        if not name.lower().endswith(".txt"):
            report.append({"file": name, "status": "skipped (not .txt)"})
            continue
        raw = zf.read(info)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        ep = parse_episode_text(text, name.split("/")[-1])
        episodes.append(ep)
        report.append({"file": name, "status": "parsed", "episode": ep.number,
                       "events": len(ep.events), "scenes": len(ep.scenes)})
    episodes.sort(key=lambda e: e.number)
    return episodes, report


def dataset_report(episodes, file_report) -> dict:
    nums = [e.number for e in episodes]
    uniq = sorted(set(nums))
    dups = sorted({n for n in nums if nums.count(n) > 1})
    lo, hi = (min(uniq), max(uniq)) if uniq else (0, 0)
    missing = [n for n in range(1, hi + 1) if n not in uniq] if uniq else []
    kinds = {}
    for e in episodes:
        for ev in e.events:
            kinds[ev.kind] = kinds.get(ev.kind, 0) + 1
    durs = [e.duration_s for e in episodes]
    return {
        "files_in_zip": len(file_report),
        "txt_files_parsed": sum(1 for f in file_report if f["status"] == "parsed"),
        "unique_episodes": len(uniq),
        "episode_range": [lo, hi],
        "missing_episodes": missing,
        "duplicate_episodes": dups,
        "complete_sequence": not missing and not dups and lo == 1,
        "total_scenes": sum(len(e.scenes) for e in episodes),
        "total_events": sum(len(e.events) for e in episodes),
        "events_by_kind": kinds,
        "all_timestamps_parsable": not any("Unparsable" in i for e in episodes for i in e.issues),
        "episode_duration_s": {"min": round(min(durs), 2) if durs else 0,
                                "max": round(max(durs), 2) if durs else 0,
                                "mean": round(sum(durs) / len(durs), 2) if durs else 0},
        "issues": {e.number: e.issues for e in episodes if e.issues},
        "files": file_report,
    }
