"""Step 1 (code): intake. Masks recall numbers and flags what is missing, before any evidence or AI.

The masking rule is also used by the evaluation builder, so the product and the evaluation mask exactly the same way.
"""
import re

from app.models import Complaint, Intake

# NHTSA campaign numbers as owners write them: 24V868, 24V-868, 24 V 868, 24V868000
RECALL_NO = re.compile(r"\b(\d{2})\s?-?\s?V\s?-?\s?(\d{3})(?:\s?-?\s?000)?\b", re.I)
MASK = "[recall no. removed]"
SHORT_TEXT = 50  # characters after masking; below this a complaint rarely says what failed and how


def cited_recalls(text: str) -> list[str]:
    """Recall numbers cited in free text, normalized to NHTSA's 9-character CAMPNO (e.g. '24V868000')."""
    seen: list[str] = []
    for yy, nnn in RECALL_NO.findall(text or ""):
        campno = f"{yy}V{nnn}000"
        if campno not in seen:
            seen.append(campno)
    return seen


def mask_recall_numbers(text: str) -> str:
    """Remove cited recall numbers so the answer cannot leak in and the complaint cannot steer the match by number."""
    return RECALL_NO.sub(MASK, text or "")


def intake(c: Complaint) -> Intake:
    text = mask_recall_numbers(c.text)
    flags = []
    if c.year == "9999" or not c.year.isdigit():
        flags.append("unknown_year")
    if not c.comps or c.comps == ["UNKNOWN OR OTHER"]:
        flags.append("unknown_component")
    if len(text.strip()) < SHORT_TEXT:
        flags.append("short_text")
    if c.crash or c.fire or c.injured:
        flags.append("severe")
    return Intake(text=text, masked=text.count(MASK), flags=flags)
