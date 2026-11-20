"""Text rules shared by the product (intake) and the evaluation builder, so both mask exactly the same way."""
import re

# NHTSA campaign numbers as owners write them: 24V868, 24V-868, 24 V 868, 24V868000
RECALL_NO = re.compile(r"\b(\d{2})\s?-?\s?V\s?-?\s?(\d{3})(?:\s?-?\s?000)?\b", re.I)
MASK = "[recall no. removed]"


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
