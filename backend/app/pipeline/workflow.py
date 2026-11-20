"""The wiring: one complaint = one Microsoft Agent Framework workflow of five steps. No logic of its own; each step
calls its module in this folder.

    intake ─> evidence ──(AI on)──> judge ─> verify ──(ok, or gave up)──> decide
                 │                    ^         │
                 │                    └─repair──┘  (once, with the verifier's issues)
                 └──(AI off / model year unknown)────────────────────> decide

- Case: the state passed from step to step. Plain data only (MAF copies it into its events).
- Resources: what the steps work with during one run (database, model setup, the agent, progress callback). Not
  passed as a message, so it may hold connections and clients.
"""
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler
from pydantic import ValidationError

from app.ai.clients import LlmSetup
from app.ai.prompt import case_message, parse_judgment, repair_message
from app.models import Attempt, Complaint, Decision, Evidence, Intake, Issue, Judgment, Result
from app.pipeline.decide import decide
from app.pipeline.evidence import gather
from app.pipeline.intake import intake
from app.pipeline.judge import Judge, ask, build_judge
from app.pipeline.verify import verify

MAX_ATTEMPTS = 2  # first answer + one repair
SOURCE = {"ok": "ai_verified", "repaired": "ai_repaired", "fallback": "fallback"}


@dataclass
class Case:
    complaint: Complaint
    use_llm: bool
    intake: Intake | None = None
    evidence: Evidence | None = None
    attempts: list[Attempt] = field(default_factory=list)
    reply: str = ""
    judgment: Judgment | None = None
    status: str = "rules"           # -> ok | repair | repaired | fallback
    decision: Decision | None = None
    model: str = ""


@dataclass
class Resources:
    con: Any                        # sqlite3 connection to the NHTSA data (read-only)
    llm: LlmSetup | None
    fault: str | None
    emit: Callable[[dict], None]    # progress events for the UI
    judge: Judge | None = None


class Step(Executor):
    def __init__(self, name: str, res: Resources):
        super().__init__(id=name)
        self.res = res


class IntakeStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        self.res.emit({"type": "step", "step": self.id})
        case.intake = intake(case.complaint)
        self.res.emit({"type": "intake", "flags": case.intake.flags, "masked": case.intake.masked})
        await ctx.send_message(case)


class EvidenceStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        res = self.res
        res.emit({"type": "step", "step": self.id})
        case.evidence = gather(res.con, case.complaint, case.intake)
        res.emit({"type": "evidence", "recalls": [r.campno for r in case.evidence.recalls],
                  "recalls_total": case.evidence.recalls_total, "stats": case.evidence.stats.model_dump()})
        if "unknown_year" in case.intake.flags:
            case.use_llm = False  # no candidate recalls to compare against: the rules answer needs_info
        if case.use_llm:
            res.judge = build_judge(res.con, case.complaint, res.llm, res.fault,
                                    lambda call: res.emit({"type": "tool_call", **call}))
        await ctx.send_message(case)


class JudgeStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        n = len(case.attempts) + 1
        self.res.emit({"type": "step", "step": self.id, "attempt": n})
        text = case_message(case.complaint, case.intake, case.evidence) if n == 1 else \
            repair_message(case.attempts[-1].issues)
        att, case.reply, case.model = await ask(self.res.judge, n, text, self.res.llm.model_name)
        case.attempts.append(att)
        self.res.emit({"type": "agent", "attempt": n, "error": att.error, "input_tokens": att.input_tokens,
                       "output_tokens": att.output_tokens})
        await ctx.send_message(case)


class VerifyStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        """ok -> keep the judgment; issues on the first answer -> repair; otherwise -> fallback."""
        att, j = case.attempts[-1], None
        self.res.emit({"type": "step", "step": self.id, "attempt": att.n})
        if att.error is None:
            try:
                j = parse_judgment(case.reply)
                att.issues = verify(j, case.complaint, case.intake, case.evidence, self.res.judge.found)
            except (ValidationError, ValueError) as exc:
                att.issues = [Issue(code="malformed_output", message=str(exc).splitlines()[0][:300])]
        if j is not None and not att.issues:
            case.judgment, case.status = j, ("ok" if att.n == 1 else "repaired")
        elif att.error is None and att.n < MAX_ATTEMPTS:
            case.status = "repair"
        else:
            case.status = "fallback"
        self.res.emit({"type": "verify", "attempt": att.n, "result": case.status,
                       "issues": [i.model_dump() for i in att.issues]})
        await ctx.send_message(case)


class DecideStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case, Case]) -> None:
        self.res.emit({"type": "step", "step": self.id})
        case.decision = decide(case.complaint, case.intake, case.evidence, case.judgment,
                               SOURCE.get(case.status, "rules"))
        await ctx.yield_output(case)


def build_workflow(res: Resources):
    i, e, j, v, d = (IntakeStep("intake", res), EvidenceStep("evidence", res), JudgeStep("judge", res),
                     VerifyStep("verify", res), DecideStep("decide", res))
    return (WorkflowBuilder(start_executor=i, name="recall_match")
            .add_edge(i, e)
            .add_edge(e, j, condition=lambda c: c.use_llm)
            .add_edge(e, d, condition=lambda c: not c.use_llm)
            .add_edge(j, v)
            .add_edge(v, j, condition=lambda c: c.status == "repair")
            .add_edge(v, d, condition=lambda c: c.status != "repair")
            .build())


async def run(con, complaint: Complaint, llm: LlmSetup | None, use_llm: bool = True, fault: str | None = None,
              emit: Callable[[dict], None] | None = None) -> Result:
    started = time.perf_counter()
    use_llm = use_llm and llm is not None
    res = Resources(con, llm if use_llm else None, fault, emit or (lambda event: None))
    case = Case(complaint, use_llm)
    steps: list[str] = []
    async for ev in build_workflow(res).run(case, stream=True):  # the workflow's own events: which steps ran
        if ev.type == "executor_invoked":
            steps.append(ev.executor_id)
    return Result(
        id=uuid.uuid4().hex[:12], complaint=complaint, intake=case.intake, evidence=case.evidence,
        judgment=case.judgment, decision=case.decision, attempts=case.attempts,
        tool_calls=res.judge.trace.calls if res.judge else [], steps=steps, model=case.model, fault=fault,
        latency_ms=round((time.perf_counter() - started) * 1000), created_at=datetime.now(UTC).isoformat())
