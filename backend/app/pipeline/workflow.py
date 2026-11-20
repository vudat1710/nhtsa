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
        res.emit({"type": "evidence", "recalls": [recall.campno for recall in case.evidence.recalls],
                  "recalls_total": case.evidence.recalls_total, "stats": case.evidence.stats.model_dump()})
        if "unknown_year" in case.intake.flags:
            case.use_llm = False  # no candidate recalls to compare against: the rules answer needs_info
        if case.use_llm:
            def emit_tool_call(call: dict) -> None:
                res.emit({"type": "tool_call", **call})

            res.judge = build_judge(res.con, case.complaint, res.llm, res.fault, emit_tool_call)
        await ctx.send_message(case)


class JudgeStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        attempt_no = len(case.attempts) + 1
        self.res.emit({"type": "step", "step": self.id, "attempt": attempt_no})
        if attempt_no == 1:
            text = case_message(case.complaint, case.intake, case.evidence)
        else:
            text = repair_message(case.attempts[-1].issues)
        attempt, case.reply, case.model = await ask(self.res.judge, attempt_no, text, self.res.llm.model_name)
        case.attempts.append(attempt)
        self.res.emit({"type": "agent", "attempt": attempt_no, "error": attempt.error,
                       "input_tokens": attempt.input_tokens, "output_tokens": attempt.output_tokens})
        await ctx.send_message(case)


class VerifyStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case]) -> None:
        """ok -> keep the judgment; issues on the first answer -> repair; otherwise -> fallback."""
        attempt = case.attempts[-1]
        judgment = None
        self.res.emit({"type": "step", "step": self.id, "attempt": attempt.n})

        # Parse and verify the reply (a failed model call has no reply to check)
        if attempt.error is None:
            try:
                judgment = parse_judgment(case.reply)
                attempt.issues = verify(judgment, case.complaint, case.intake, case.evidence, self.res.judge.found)
            except (ValidationError, ValueError) as exc:
                first_line = str(exc).splitlines()[0]
                attempt.issues = [Issue(code="malformed_output", message=first_line[:300])]

        # Where to go next
        if judgment is not None and not attempt.issues:
            case.judgment = judgment
            case.status = "ok" if attempt.n == 1 else "repaired"
        elif attempt.error is None and attempt.n < MAX_ATTEMPTS:
            case.status = "repair"
        else:
            case.status = "fallback"

        self.res.emit({"type": "verify", "attempt": attempt.n, "result": case.status,
                       "issues": [issue.model_dump() for issue in attempt.issues]})
        if case.judgment:  # what the agent concluded per recall, now that every quote is verified
            self.res.emit({"type": "judgment", "checks": [check.model_dump() for check in case.judgment.checks],
                           "similar": [similar.model_dump() for similar in case.judgment.similar]})
        await ctx.send_message(case)


class DecideStep(Step):
    @handler
    async def run(self, case: Case, ctx: WorkflowContext[Case, Case]) -> None:
        self.res.emit({"type": "step", "step": self.id})
        source = SOURCE.get(case.status, "rules")
        case.decision = decide(case.complaint, case.intake, case.evidence, case.judgment, source)
        await ctx.yield_output(case)


def build_workflow(res: Resources):
    intake_step = IntakeStep("intake", res)
    evidence_step = EvidenceStep("evidence", res)
    judge_step = JudgeStep("judge", res)
    verify_step = VerifyStep("verify", res)
    decide_step = DecideStep("decide", res)
    return (WorkflowBuilder(start_executor=intake_step, name="recall_match")
            .add_edge(intake_step, evidence_step)
            .add_edge(evidence_step, judge_step, condition=lambda case: case.use_llm)
            .add_edge(evidence_step, decide_step, condition=lambda case: not case.use_llm)
            .add_edge(judge_step, verify_step)
            .add_edge(verify_step, judge_step, condition=lambda case: case.status == "repair")
            .add_edge(verify_step, decide_step, condition=lambda case: case.status != "repair")
            .build())


async def run(con, complaint: Complaint, llm: LlmSetup | None, use_llm: bool = True, fault: str | None = None,
              emit: Callable[[dict], None] | None = None) -> Result:
    started = time.perf_counter()
    use_llm = use_llm and llm is not None
    llm_for_run = llm if use_llm else None
    on_event = emit or (lambda event: None)  # nobody listening: drop progress events
    res = Resources(con, llm_for_run, fault, on_event)
    case = Case(complaint, use_llm)

    steps: list[str] = []
    async for event in build_workflow(res).run(case, stream=True):  # the workflow's own events: which steps ran
        if event.type == "executor_invoked":
            steps.append(event.executor_id)

    tool_calls = res.judge.trace.calls if res.judge else []
    return Result(
        id=uuid.uuid4().hex[:12], complaint=complaint, intake=case.intake, evidence=case.evidence,
        judgment=case.judgment, decision=case.decision, attempts=case.attempts, tool_calls=tool_calls, steps=steps,
        model=case.model, fault=fault, latency_ms=round((time.perf_counter() - started) * 1000),
        created_at=datetime.now(UTC).isoformat())
