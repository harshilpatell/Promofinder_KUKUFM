"""Prompt templates. The LLM does semantic/editorial judgement only.

Contract: the model must reference event IDs (e.g. "E12-034") for every
boundary, hook and cliffhanger. It must never write timestamps itself —
deterministic code resolves IDs to source timestamps and validates them.
"""
import json

RUBRIC = """SCORING RUBRIC (editorial prioritisation heuristic, NOT a performance prediction):
- hook (0-25): does the first 3 seconds stop a scrolling viewer? (slap, reveal, shocking line,
  threat, accusation, dramatic visual). Dramatic wording alone is not enough; it must create curiosity.
- cliffhanger (0-25): does the clip CUT at an unresolved question? Endings that resolve the beat score low.
- standalone (0-20): can a viewer who never saw the show tell who is involved, what is happening,
  what is at stake? Penalise clips that depend on names/relationships not shown in the clip.
- emotion (0-15): intensity of betrayal, humiliation, danger, romance, revenge, suspense.
- visual (0-10): strength of CAMERA/ACTION storytelling plus dialogue quality.
- distinct (0-5): how different this promo's angle is from other promos of this show (stage 1: your
  best guess; stage 2 re-scores it show-wide).
Do not inflate scores. A typical decent candidate totals 60-75; reserve 85+ for exceptional clips."""

PROMO_RULES = """PROMO RULES (Kuku brief):
- Total duration 20-60 seconds (sum of segment durations; gaps between segments are removed).
- Usually one continuous stretch; may join a few moments (same or different episodes) ONLY when it
  materially improves context, pacing or suspense. Keep segments as few as possible (max 3).
- Opens on a hook: the hook event must START within the first 3 seconds of the assembled promo,
  so the first segment should usually begin AT the hook event (or the shot right before it).
- Ends on a cliffhanger: the last segment must END on the cliffhanger event.
- Must make sense to someone who has never seen the show.
- CAMERA/ACTION/DLG lines can overlap in time; they describe the same moment from different angles.
- Prefer boundaries that keep full dialogue lines; do not start or end mid-sentence.
- Never invent dialogue or events. Quote only text that appears in the timeline."""

STAGE1_SCHEMA = {
    "episode": "int",
    "episode_summary": "1-2 sentences, what actually happens",
    "story_facts": ["short facts useful for cross-episode promos, e.g. reveals, relationship changes"],
    "candidates": [{
        "title": "short promo title",
        "angle": "one of: betrayal, humiliation, rescue, romance, revenge, danger, mystery/reveal, injustice, power-reversal, villain-scheme, action, other",
        "segments": [{"start_event": "E<ep>-<nnn>", "end_event": "E<ep>-<nnn>"}],
        "hook_event": "event id of the hook (must be within first 3s of the promo)",
        "hook_quote": "verbatim words from the hook event, or a short visual description if it is an ACTION/CAM event",
        "hook": "what exactly stops the scroll",
        "cliffhanger_event": "event id of the final unresolved beat (last segment must end on it)",
        "cliffhanger": "what question is left open",
        "standalone_context": "why a new viewer understands it / what they might not understand",
        "why_it_works": "ONE specific line",
        "scores": {"hook": 0, "cliffhanger": 0, "standalone": 0, "emotion": 0, "visual": 0, "distinct": 0},
        "confidence": "high|medium|low",
        "concerns": "editorial concerns (pacing, context, brand safety, continuity) or empty"
    }],
    "rejected_moments": [{"events": "E<ep>-<nnn>..E<ep>-<nnn>", "reason": "why it is not a promo"}]
}


def stage1_prompt(show_title: str, ep_timeline: str, prior_context: str) -> str:
    return f"""You are a senior short-form video promo editor for a microdrama app (like ReelShort/DramaBox).
You are reading the screenplay of ONE episode of the show "{show_title}" and must find the moments in it
that would make the strongest 20-60 second promos for Instagram/TikTok/YouTube.

{PROMO_RULES}

{RUBRIC}

STORY SO FAR (loglines of previous episodes; for context only, do not cite):
{prior_context or "(this is the first episode)"}

EPISODE TIMELINE. Each line: EVENT_ID [start-end] TYPE text. TYPE is CAM (camera), ACT (action),
DLG (dialogue), SFX (sound). Timestamps are episode-relative MM:SS.ss.
{ep_timeline}

TASK: Return 0-3 promo candidates for this episode (only genuinely strong ones; zero is acceptable).
Do not automatically pick the final scene. Look across the whole episode. Also list weak/rejected moments
that a naive tool might pick, with the reason. Reference boundaries ONLY by event IDs.

Respond with ONLY a JSON object of this shape (no markdown):
{json.dumps(STAGE1_SCHEMA, indent=1)}"""


STAGE2_SCHEMA = {
    "show_summary": "3-4 sentences: protagonist, antagonist(s), core conflicts",
    "cross_episode_promos": [{
        "title": "...", "angle": "...",
        "segments": [{"start_event": "E<ep>-<nnn>", "end_event": "E<ep>-<nnn>"}],
        "hook_event": "...", "hook_quote": "...", "hook": "...",
        "cliffhanger_event": "...", "cliffhanger": "...",
        "standalone_context": "...", "why_it_works": "...",
        "why_combine": "why these segments together beat any single segment, and why this order",
        "scores": {"hook": 0, "cliffhanger": 0, "standalone": 0, "emotion": 0, "visual": 0, "distinct": 0},
        "confidence": "high|medium|low", "concerns": "..."
    }],
    "distinct_scores": {"<candidate_id>": "0-5 show-wide distinctiveness"},
    "duplicate_groups": [["<candidate_id>", "<candidate_id>"]],
    "publication_top5": [{"candidate_id": "...", "reason": "why publish early",
                          "target_emotion": "...", "angle_difference": "how it differs from other top picks"}],
    "portfolio_note": "does the set cover different dramatic moment types or over-rely on one?"
}


def stage2_prompt(show_title: str, ep_summaries: str, candidates_compact: str, key_events: str) -> str:
    return f"""You are the lead promo strategist for the microdrama "{show_title}". Episode-level analysis is
done. Now work show-wide.

{PROMO_RULES}

{RUBRIC}

EPISODE SUMMARIES AND STORY FACTS:
{ep_summaries}

VALIDATED EPISODE-LEVEL CANDIDATES (id | episode | title | angle | duration | hook | cliffhanger | scores):
{candidates_compact}

KEY EVENTS YOU MAY USE AS SEGMENT BOUNDARIES FOR CROSS-EPISODE PROMOS:
{key_events}

TASKS:
1. Propose 0-5 cross-episode promos that tell a stronger mini-story than any single clip
   (e.g. segment 1 sets up a conflict, segment 2 escalates, segment 3 ends on a reveal/cliffhanger).
   Only combine when coherent; boundaries by event IDs only; max 3 segments; 20-60s total.
2. Re-score distinctiveness (0-5) of every candidate show-wide.
3. Group candidates that communicate the same dramatic beat (duplicates).
4. Pick the five promos to publish first (may include your cross-episode ids as "X1".."X5"), each
   with a different angle where possible.

Respond with ONLY a JSON object (no markdown) of this shape:
{json.dumps(STAGE2_SCHEMA, indent=1)}"""


def repair_prompt(candidate: dict, errors: list, window_timeline: str) -> str:
    return f"""A promo candidate you proposed failed deterministic validation. Fix ONLY the segment
boundaries / hook / cliffhanger event IDs so that it passes, keeping the same dramatic idea. If it cannot be
fixed without destroying the idea, return {{"unfixable": true, "reason": "..."}}.

{PROMO_RULES}

CANDIDATE:
{json.dumps(candidate, indent=1)}

VALIDATION ERRORS:
{json.dumps(errors, indent=1)}

RELEVANT TIMELINE:
{window_timeline}

Respond with ONLY the corrected candidate JSON (same keys), no markdown."""
