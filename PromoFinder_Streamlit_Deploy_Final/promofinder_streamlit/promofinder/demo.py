"""Synthetic demo show. Builds: a tiny, ORIGINAL 3-episode microdrama written for
testing/demo only (no Kuku content). Same file format as the real input pack, including
the upper-case scene-header variant seen in one real episode.

    python -m promofinder.demo  (writes demo_data/synthetic_show.zip)
"""
import zipfile
from pathlib import Path

SHOW = "The Florist Who Owned the City"


def ts(x):
    m, s = divmod(x, 60)
    return f"{int(m):02d}:{s:05.2f}"


def block(kind, start, end, text, speaker=None, direction=None):
    if kind == "DLG":
        label = f"{speaker} ({direction})" if direction else speaker
        return f"**{label}:**\nStart: ({ts(start)}) | End: ({ts(end)})\n\"{text}\"\n"
    lab = {"CAM": "CAMERA", "ACT": "ACTION", "SFX": "SOUND FX"}[kind]
    return f"**{lab}:**\nStart: ({ts(start)}) | End: ({ts(end)})\n{text}\n"


EPISODES = {
    1: ("Mara, a struggling florist, is publicly fired from a gala by her fiance's mother - and a silent driver steps in.",
        "First episode. Establishes Mara, fiance Theo, his mother Vivian, and the driver Cole.",
        [("INT. GRAND BALLROOM - NIGHT", [
            ("CAM", 0.0, 3.0, "Wide shot of a glittering ballroom; Mara carries a towering flower arrangement."),
            ("ACT", 0.5, 3.0, "Mara balances the vase, smiling nervously at the guests."),
            ("CAM", 3.0, 6.0, "Close-up on Vivian snapping her fingers."),
            ("DLG", 3.2, 5.8, "Stop right there. Who let the help into my party?", "VIVIAN", "Icy"),
            ("CAM", 6.0, 9.0, "Medium shot of Mara freezing."),
            ("DLG", 6.3, 8.8, "Theo asked me to do the flowers. I'm his fiancee.", "MARA", "Confused"),
            ("CAM", 9.0, 12.5, "Close-up on Theo looking away."),
            ("DLG", 9.2, 12.2, "Theo is engaged to a woman of standing. Not a shop girl.", "VIVIAN", "Cruel"),
            ("ACT", 12.5, 15.0, "Vivian tips the vase; water and roses crash over Mara's dress."),
            ("SFX", 12.8, 14.0, "Glass shattering."),
            ("CAM", 12.5, 15.5, "Slow-motion insert of roses hitting the marble floor."),
            ("DLG", 15.6, 17.6, "Theo... say something.", "MARA", "Pleading"),
            ("CAM", 17.6, 21.0, "Close-up on Theo's hand slipping into another woman's."),
            ("DLG", 18.0, 20.8, "I'm sorry, Mara. Mother is right.", "THEO", "Weak"),
            ("CAM", 21.0, 24.0, "Mara's tear-streaked face."),
            ("DLG", 21.5, 23.9, "Three years. You let me believe it for three years.", "MARA", "Broken"),
            ("CAM", 24.0, 27.0, "Vivian gestures to security."),
            ("DLG", 24.2, 26.6, "Security. Remove her before she drips on my floor.", "VIVIAN", "Dismissive"),
            ("ACT", 27.0, 30.0, "Two guards grab Mara's arms."),
            ("CAM", 30.0, 33.0, "Low angle: the doors open; a man in a plain driver's jacket walks in."),
            ("DLG", 31.0, 33.0, "Let go of her.", "COLE", "Quiet"),
            ("CAM", 33.0, 36.0, "Guards hesitate; one goes pale."),
            ("DLG", 33.3, 35.8, "You're just the valet. Get out.", "VIVIAN", "Scornful"),
            ("CAM", 36.0, 40.0, "Cole kneels and picks up a single unbroken rose, offering it to Mara."),
            ("DLG", 36.4, 39.8, "Marry me, and none of them will ever touch you again.", "COLE", "Steady"),
            ("CAM", 40.0, 44.0, "Push-in on Mara's stunned face. Cut to black."),
            ("SFX", 40.5, 44.0, "String swell to a cliffhanger."),
        ])]),
    2: ("Mara accepts Cole's offer; Vivian's lawyer arrives to evict her shop.",
        "Mara and Cole are married at city hall. Vivian owns Mara's shop building.",
        [("INT. CITY HALL - DAY", [
            ("CAM", 0.0, 3.0, "Mara and Cole stand before a clerk."),
            ("DLG", 0.4, 2.8, "Last chance to say no.", "COLE", "Gentle"),
            ("DLG", 3.0, 5.0, "I said yes. I meant it.", "MARA", "Firm"),
            ("CAM", 3.0, 6.5, "Close-up of plain rings exchanged."),
            ("DLG", 5.5, 8.0, "Then you're my wife.", "COLE", "Warm"),
            ("CAM", 6.5, 10.0, "Mara smiles for the first time."),
         ]),
         ("INT. FLOWER SHOP - DAY", [
            ("CAM", 10.0, 13.0, "A lawyer in a grey suit slaps a document on the counter."),
            ("DLG", 10.3, 12.8, "Mrs. Vivian Hale owns this building. You have one hour.", "LAWYER", "Cold"),
            ("ACT", 13.0, 16.0, "Mara grips the counter, knuckles white."),
            ("DLG", 13.2, 15.8, "One hour? Everything I own is in here!", "MARA", "Panicked"),
            ("CAM", 16.0, 19.0, "The lawyer tears down her hand-painted sign."),
            ("DLG", 16.5, 18.8, "Then I suggest you start carrying.", "LAWYER", "Smug"),
            ("CAM", 19.0, 23.0, "Cole steps in from the back, phone to ear."),
            ("DLG", 19.4, 22.6, "Buy the building. No. Buy the whole street.", "COLE", "Calm"),
            ("CAM", 23.0, 27.0, "The lawyer's face drains of colour."),
            ("DLG", 23.4, 26.4, "Who... who are you?", "LAWYER", "Shaken"),
            ("CAM", 27.0, 30.0, "Cole smiles faintly. Cut to black."),
         ])]),
    3: ("Vivian learns who owns the street - and that the driver is the heir she spent ten years searching for.",
        "Cole is secretly the heir of the Calloway fortune.",
        [("INT. HALE MANSION - NIGHT", [
            ("CAM", 0.0, 3.0, "Vivian throws a newspaper onto the table."),
            ("DLG", 0.3, 2.8, "Calloway Holdings bought Fifth Street?", "VIVIAN", "Furious"),
            ("CAM", 3.0, 6.0, "Theo reads the headline, stunned."),
            ("DLG", 3.4, 5.9, "The Calloway heir vanished ten years ago.", "THEO", "Uneasy"),
            ("CAM", 6.0, 10.0, "Insert: a photo in the paper - Cole, younger, in a suit."),
            ("ACT", 6.0, 10.0, "Vivian's hand trembles over the photo."),
            ("DLG", 10.2, 12.6, "That's the valet.", "VIVIAN", "Horrified"),
            ("CAM", 12.6, 16.0, "Doorbell. Vivian turns."),
            ("SFX", 12.6, 13.5, "Doorbell chime."),
            ("CAM", 16.0, 20.0, "Mara stands at the door in a red dress, holding a single rose."),
            ("DLG", 16.4, 19.6, "Hello, Vivian. I came to talk about your lease.", "MARA", "Cool"),
            ("CAM", 20.0, 24.0, "Vivian forces a smile."),
            ("DLG", 20.3, 23.6, "Mara, darling. Let's not be hasty.", "VIVIAN", "Fake-sweet"),
            ("CAM", 24.0, 28.0, "Mara hands her an envelope; inside, an eviction notice with Vivian's name."),
            ("DLG", 24.4, 27.6, "You have one hour.", "MARA", "Icy"),
            ("CAM", 28.0, 32.0, "Behind Mara, Theo steps out of the shadows."),
            ("DLG", 28.4, 31.5, "Mara, wait. There's something you don't know about Cole.", "THEO", "Desperate"),
            ("CAM", 32.0, 35.0, "Mara freezes. Cut to black."),
         ])]),
}


def build_bytes() -> bytes:
    """Return the synthetic show as an in-memory ZIP (no disk access needed)."""
    import io
    buf = io.BytesIO()
    _write(buf)
    return buf.getvalue()


def build(out_zip: Path):
    _write(out_zip)
    return out_zip


def _write(target):
    with zipfile.ZipFile(target, "w") as z:
        for n, (log, cont, scenes) in EPISODES.items():
            upper = n == 3  # exercise the upper-case header variant
            lines = [f"EPISODE NUMBER: Episode {n}", f"EPISODE LOGLINE: {log}", f"CONTINUITY NOTES: {cont}", "",
                     "--- SCRIPT START ---", ""]
            for i, (heading, evs) in enumerate(scenes, 1):
                s0, s1 = min(e[1] for e in evs), max(e[2] for e in evs)
                h = ["SCENE HEADING", "SCENE START", "SCENE END", "ACTIONS AND DIALOGUE"] if upper else \
                    ["Scene heading", "Scene start", "Scene end", "Actions and dialogue"]
                lines += [f"SCENE {i:02d}", f"{h[0]}: {heading}", f"{h[1]}: {ts(s0)}", f"{h[2]}: {ts(s1)}", "", f"{h[3]}:", ""]
                for e in evs:
                    kind, a, b, text = e[:4]
                    lines.append(block(kind, a, b, text, *(e[4:6] if len(e) > 4 else (None, None))))
            lines.append("--- SCRIPT END ---")
            z.writestr(f"{SHOW}/episode-{n:03d}-Synthetic {9000 + n}.txt", "\n".join(lines))


if __name__ == "__main__":
    p = build(Path(__file__).resolve().parents[1] / "demo_data" / "synthetic_show.zip")
    print("wrote", p)
