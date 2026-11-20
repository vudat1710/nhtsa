"""Drafted messages, built only from the recall's own text and the complaint's own fields (templates, not AI), so a
draft can never promise a remedy the recall does not state."""
import re

from app.models import Complaint, RecallItem


def display_campno(campno: str) -> str:
    """'24V868000' -> '24V-868', the way NHTSA and owners write it."""
    return f"{campno[:3]}-{campno[3:6]}" if len(campno) == 9 else campno


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    return [sentence.strip() for sentence in parts if sentence.strip()]


def readable(text: str) -> str:
    """Older NHTSA recall texts are ALL CAPS; show them in sentence case."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return text
    uppercase = [ch for ch in letters if ch.isupper()]
    if len(uppercase) / len(letters) <= 0.5:
        return text
    return " ".join(sentence[:1].upper() + sentence[1:].lower() for sentence in sentences(text))


def plain_defect(defect: str) -> str:
    """Drop the boilerplate opening ('Hyundai ... is recalling certain 2022-2024 IONIQ 5, ...') and keep the failure."""
    defect = readable(defect)
    kept = []
    for sentence in sentences(defect):
        lowered = sentence.lower()
        if "is recalling" in lowered or lowered.startswith("please refer"):
            continue
        kept.append(sentence)
    return " ".join(kept) or defect


def covers(recall: RecallItem, complaint: Complaint) -> str:
    years = recall.model_years
    if not years:
        span = "?"
    elif len(years) == 1:
        span = years[0]
    else:
        span = f"{years[0]}–{years[-1]}"
    return f"{span} {complaint.make.title()} {complaint.model.title()}"


def owner_recall_reply(complaint: Complaint, recall: RecallItem, after_remedy: bool) -> str:
    vehicle = f"{complaint.year} {complaint.make.title()} {complaint.model.title()}"
    lines = [
        f"Thank you for reporting this problem with your {vehicle}.",
        "",
        f"Your vehicle is covered by safety recall {display_campno(recall.campno)}. What the recall says: "
        f"{plain_defect(recall.defect)}",
        "",
        f"The remedy: {recall.remedy.strip()}",
        "",
        f"Please contact an authorized {complaint.make.title()} dealer to have the recall repair done.",
    ]
    if after_remedy:
        lines += ["", "If this recall repair was already done on your vehicle, please reply with the date of the "
                      "repair so we can review your case."]
    return "\n".join(lines)


def owner_info_request(complaint: Complaint, questions: list[str]) -> str:
    vehicle = f"{complaint.make.title()} {complaint.model.title()}"
    if complaint.year.isdigit():
        vehicle = f"{complaint.year} {vehicle}"
    asks = questions or ["What exactly happened, and what warning lights or messages did you see?",
                         "What is the model year of the vehicle (or its VIN)?"]
    lines = [f"Thank you for reporting this problem with your {vehicle}.",
             "",
             "To check whether an existing recall covers it, could you tell us:"]
    for number, question in enumerate(asks, 1):
        lines.append(f"{number}. {question}")
    return "\n".join(lines)
