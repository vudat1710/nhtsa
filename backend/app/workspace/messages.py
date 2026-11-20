"""Drafted messages, built only from the recall's own text and the complaint's own fields (templates, not AI), so a
draft can never promise a remedy the recall does not state."""
import re

from app.models import Complaint, RecallItem


def display_campno(campno: str) -> str:
    """'24V868000' -> '24V-868', the way NHTSA and owners write it."""
    return f"{campno[:3]}-{campno[3:6]}" if len(campno) == 9 else campno


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def readable(text: str) -> str:
    """Older NHTSA recall texts are ALL CAPS; show them in sentence case."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters or sum(ch.isupper() for ch in letters) / len(letters) <= 0.5:
        return text
    return " ".join(s[:1].upper() + s[1:].lower() for s in sentences(text))


def plain_defect(defect: str) -> str:
    """Drop the boilerplate opening ('Hyundai ... is recalling certain 2022-2024 IONIQ 5, ...') and keep the failure."""
    defect = readable(defect)
    kept = [s for s in sentences(defect)
            if "is recalling" not in s.lower() and not s.lower().startswith("please refer")]
    return " ".join(kept) or defect


def covers(r: RecallItem, c: Complaint) -> str:
    years = r.model_years
    span = years[0] if len(years) == 1 else f"{years[0]}–{years[-1]}" if years else "?"
    return f"{span} {c.make.title()} {c.model.title()}"


def owner_recall_reply(c: Complaint, r: RecallItem, after_remedy: bool) -> str:
    vehicle = f"{c.year} {c.make.title()} {c.model.title()}"
    lines = [
        f"Thank you for reporting this problem with your {vehicle}.",
        "",
        f"Your vehicle is covered by safety recall {display_campno(r.campno)}. What the recall says: "
        f"{plain_defect(r.defect)}",
        "",
        f"The remedy: {r.remedy.strip()}",
        "",
        f"Please contact an authorized {c.make.title()} dealer to have the recall repair done.",
    ]
    if after_remedy:
        lines += ["", "If this recall repair was already done on your vehicle, please reply with the date of the "
                      "repair so we can review your case."]
    return "\n".join(lines)


def owner_info_request(c: Complaint, questions: list[str]) -> str:
    vehicle = f"{c.year} {c.make.title()} {c.model.title()}" if c.year.isdigit() else \
        f"{c.make.title()} {c.model.title()}"
    asks = questions or ["What exactly happened, and what warning lights or messages did you see?",
                         "What is the model year of the vehicle (or its VIN)?"]
    return "\n".join([f"Thank you for reporting this problem with your {vehicle}.", "",
                      "To check whether an existing recall covers it, could you tell us:",
                      *[f"{i}. {q}" for i, q in enumerate(asks, 1)]])
