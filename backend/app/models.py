"""The data shapes, in the order a complaint flows through the system:
Complaint -> Intake -> Evidence -> Judgment (AI, verified) -> Decision."""
from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["known_recall", "related_different", "possible_new", "needs_info"]
Confidence = Literal["high", "medium", "low"]
MIN_QUOTE_WORDS = 3  # every quote the AI gives must be at least this many words copied exactly (prompt + verifier)


class Complaint(BaseModel):
    odino: int | None = None          # None for a complaint typed into the UI
    make: str
    model: str
    year: str                         # '9999' = unknown, as NHTSA writes it
    received: str                     # ISO date; the as_of for every evidence query
    crash: int = 0
    fire: int = 0
    injured: int = 0
    text: str
    components: list[str] = []        # as the owner chose them, e.g. 'AIR BAGS:FRONTAL'

    @property
    def comps(self) -> list[str]:
        return sorted({c.split(":")[0].strip() for c in self.components})


class Intake(BaseModel):
    text: str                         # complaint text with recall numbers masked: all the AI ever sees of it
    masked: int                       # how many recall numbers were removed
    flags: list[str]                  # unknown_year | unknown_component | short_text | severe


class RecallItem(BaseModel):
    campno: str
    filed: str
    influenced_by: str
    units: int | None
    components: list[str]
    comps: list[str]
    same_component: bool              # shares a top-level component with the complaint
    defect: str
    consequence: str
    remedy: str
    replaced_by: str | None = None    # another candidate that replaced this recall (parsed from the remedy text)
    complaints_since: int = 0         # earlier complaints on this vehicle + component filed after this recall
    model_years: list[str] = []       # model years of this make/model the recall covers (shown to the analyst only)


class InvestigationItem(BaseModel):
    action: str
    opened: str
    closed: str | None
    campno: str | None
    subject: str


class Stats(BaseModel):
    """Earlier complaints on the same vehicle sharing a component. All counts come from code, never from the AI."""
    total: int
    crash: int
    fire: int
    injury: int
    first: str | None
    last: str | None
    last_12_months: int


class Evidence(BaseModel):
    recalls: list[RecallItem]
    recalls_total: int                # before the cap; > len(recalls) means some were not shown
    investigations: list[InvestigationItem]
    stats: Stats

    def recall(self, campno: str) -> RecallItem | None:
        return next((r for r in self.recalls if r.campno == campno), None)


class RecallCheck(BaseModel):
    campno: str
    verdict: Literal["same", "partial", "different"] = Field(
        description="same: the owner's symptoms match what this recall says happens; partial: compatible but too vague "
                    "to tell; different: related part, different failure")
    complaint_quote: str = Field(description="exact words copied from the complaint")
    recall_quote: str = Field(description="exact words copied from this recall's defect, consequence or remedy")
    reason: str = Field(description="one plain sentence")


class SimilarComplaint(BaseModel):
    odino: int = Field(description="an id returned by search_complaints")
    quote: str = Field(description="exact words copied from that complaint")


class Judgment(BaseModel):
    """What the AI returns. Only relevant recalls are listed; unlisted candidates are judged unrelated."""
    checks: list[RecallCheck]
    similar: list[SimilarComplaint] = []
    proposed: Outcome
    summary: str = Field(description="2-3 plain sentences for an analyst; no numbers that are not in the evidence")
    questions: list[str] = Field(default=[], description="what to ask the owner, when details are missing")


class Issue(BaseModel):
    code: str                         # unknown_recall | quote_not_found | ... (see verify.py)
    message: str


class Attempt(BaseModel):
    n: int
    raw: str = ""
    error: str | None = None
    issues: list[Issue] = []
    input_tokens: int = 0
    output_tokens: int = 0


class Decision(BaseModel):
    """The final answer, set by rules (decide.py) from verified evidence. The AI proposes; this decides."""
    outcome: Outcome
    confidence: Confidence
    campno: str | None = None         # the matched recall, for known_recall
    reasons: list[str]                # why this outcome and confidence, in plain words
    flags: list[str] = []             # severe | after_remedy | superseded | ai_disagreed | ...
    escalate: bool
    source: Literal["ai_verified", "ai_repaired", "fallback", "rules"]


class Result(BaseModel):
    """Everything about one run: the stored audit record and what the UI shows."""
    id: str
    complaint: Complaint
    intake: Intake
    evidence: Evidence
    judgment: Judgment | None
    decision: Decision
    attempts: list[Attempt]
    tool_calls: list[dict]
    steps: list[str]
    model: str = ""
    fault: str | None = None
    latency_ms: int
    created_at: str
