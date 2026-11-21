"""Drafted messages, built only from the recall's own text and the complaint's own fields (templates, not AI), so a
draft can never promise a remedy the recall does not state."""
import re
from datetime import date

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


def long_date(iso: str) -> str:
    """'2021-10-04' -> 'October 4, 2021'."""
    return date.fromisoformat(iso).strftime("%B %d, %Y").replace(" 0", " ")


def build_window(recall: RecallItem, complaint: Complaint) -> str | None:
    """'2024 models built October 4, 2021 – October 9, 2024' when NHTSA publishes build dates for this model year
    (the dates are per model year, so they are labelled with the complaint's)."""
    if not (recall.built_from and recall.built_to):
        return None
    return f"{complaint.year} models built {long_date(recall.built_from)} – {long_date(recall.built_to)}"


def owner_recall_reply(complaint: Complaint, recall: RecallItem, after_remedy: bool) -> str:
    """'May be covered', never 'is covered': a recall covers certain build dates, and only the VIN shows the car's."""
    vehicle = f"{complaint.year} {complaint.make.title()} {complaint.model.title()}"
    window = build_window(recall, complaint)
    scope = f"{covers(recall, complaint)} vehicles" + (f" ({window})" if window else "")
    lines = [
        f"Thank you for reporting this problem with your {vehicle}.",
        "",
        f"Your vehicle may be covered by safety recall {display_campno(recall.campno)}, which includes certain "
        f"{scope}. To confirm that your vehicle is included, enter its VIN at nhtsa.gov/recalls or ask an "
        f"authorized {complaint.make.title()} dealer.",
        "",
        f"What the recall says: {plain_defect(recall.defect)}",
        "",
        f"The remedy: {recall.remedy.strip()}",
        "",
        "If your vehicle is included, please contact the dealer to have the recall repair done.",
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
