"""Tool gateway: the single choke point between any identity and any tool.

    request -> kill switch -> policy check -> permission (constraints) check -> approval check
            -> dry-run short circuit -> execution -> output screening -> audit log

No agent holds a reference to a tool implementation. Agents hold a gateway, and the gateway
decides. Tool output is screened before it is returned, because tool results are untrusted too.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models import Approval, ToolCall, User
from . import audit, injection, secrets_scan
from .policy import ALLOW, DENY, REQUIRE_APPROVAL, PolicyResult, PolicyStore

BLOCKED_KILL_SWITCH = "BLOCKED_KILL_SWITCH"
DRY_RUN = "DRY_RUN"
KILL_SWITCH_MESSAGE = "TOOL EXECUTION DISABLED BY OPERATOR"


@dataclass
class Actor:
    id: str
    type: str  # agent | human | system
    roles: list = field(default_factory=list)


@dataclass
class ToolResult:
    tool: str
    decision: str
    rule: str
    reason: str
    executed: bool = False
    ok: bool = False
    output: Any = None
    required_role: str = ""
    approval: str = ""
    redactions: int = 0
    injection_flags: list = field(default_factory=list)
    latency_ms: int = 0
    would: str = ""

    def as_dict(self) -> dict:
        return {
            "tool": self.tool, "decision": self.decision, "rule": self.rule, "reason": self.reason,
            "executed": self.executed, "ok": self.ok, "required_role": self.required_role,
            "approval": self.approval, "redactions": self.redactions,
            "injection_flags": self.injection_flags, "latency_ms": self.latency_ms, "would": self.would,
        }


@dataclass
class ToolContext:
    db: Session
    actor: Actor
    run: Any = None


class ToolGateway:
    def __init__(self, store: PolicyStore, registry: dict):
        self.store = store
        self.registry = registry

    # --- decision ------------------------------------------------------------------------------
    def _decide(self, actor: Actor, tool: str, args: dict) -> PolicyResult:
        if actor.type == "human":
            if self.store.human_can(actor.roles, tool):
                return PolicyResult(ALLOW, "rbac", f"Role grants '{tool}'.")
            return PolicyResult(DENY, "rbac", f"None of the roles {actor.roles} grants '{tool}'.")
        return self.store.evaluate(actor.id, tool, args)

    def _check_approval(self, db: Session, approval_id: int, tool: str, run) -> tuple[Approval | None, str]:
        approval = db.get(Approval, approval_id)
        if approval is None:
            return None, "Approval record does not exist."
        if approval.status != "approved":
            return None, f"Approval is '{approval.status}', not approved."
        if not approval.decided_by or db.get(User, approval.decided_by) is None:
            return None, "Approval was not decided by a known human."
        if approval.action != tool:
            return None, f"Approval covers '{approval.action}', not '{tool}'."
        if approval.consumed:
            return None, "Approval has already been used once."
        if run is not None and approval.run_id != run.id:
            return None, "Approval belongs to a different run."
        return approval, ""

    # --- entry point ---------------------------------------------------------------------------
    def call(self, db: Session, actor: Actor, tool: str, args: dict | None = None, *, run=None,
             approval_id: int | None = None, tag: str = "", dry_run: bool = False) -> ToolResult:
        args = dict(args or {})
        started = time.perf_counter()
        flags = audit.get_flags(db)
        spec = self.registry.get(tool)
        result: ToolResult

        if spec is None:
            result = ToolResult(tool, DENY, "unknown-tool", f"Tool '{tool}' is not registered (allowlist).")
        elif flags.get("kill_switch") and actor.type != "human":
            result = ToolResult(tool, BLOCKED_KILL_SWITCH, "kill-switch", KILL_SWITCH_MESSAGE)
        else:
            policy = self._decide(actor, tool, args)
            result = ToolResult(tool, policy.decision, policy.rule, policy.reason, required_role=policy.required_role)

            if policy.decision == REQUIRE_APPROVAL and approval_id is not None:
                if actor.type == "agent" and tool in self.store.approval_at_most:
                    result = ToolResult(tool, DENY, "invariant:pipeline-identity-only",
                                        f"'{tool}' is executed by the pipeline identity after approval, never by an AI agent.")
                else:
                    approval, problem = self._check_approval(db, approval_id, tool, run)
                    if approval is None:
                        result = ToolResult(tool, DENY, "approval-check", problem)
                    else:
                        approval.consumed = True
                        result = ToolResult(tool, ALLOW, f"approved-by:{approval.decided_by}",
                                            f"Approved by {approval.decided_by} ({approval.required_role}).",
                                            approval=f"#{approval.id} by {approval.decided_by}")

            if result.decision in (ALLOW, REQUIRE_APPROVAL) and (dry_run or flags.get("dry_run")):
                would = spec.simulate(args)
                result = ToolResult(tool, DRY_RUN, result.rule, f"Would be {result.decision}. Nothing was executed.",
                                    required_role=result.required_role, would=would)
            elif result.decision == ALLOW:
                try:
                    output = spec.fn(ToolContext(db=db, actor=actor, run=run), **args)
                    result.executed, result.ok, result.output = True, True, output
                except Exception as exc:  # tool failures are results, not crashes
                    result.executed, result.ok = True, False
                    result.reason = f"{type(exc).__name__}: {exc}"
                if result.ok:
                    self._screen_output(result)

        result.latency_ms = int((time.perf_counter() - started) * 1000)
        self._log(db, actor, run, tool, args, result, tag)
        return result

    # --- output screening ----------------------------------------------------------------------
    @staticmethod
    def _screen_output(result: ToolResult) -> None:
        if result.output is None:
            return
        text = result.output if isinstance(result.output, str) else json.dumps(result.output, default=str)
        clean, count = secrets_scan.redact(text)
        if count:
            result.redactions = count
            if isinstance(result.output, str):
                result.output = clean
            else:
                try:
                    result.output = json.loads(clean)
                except ValueError:
                    result.output = clean
        result.injection_flags = [f.as_dict() for f in injection.scan(text)][:10]

    # --- audit ---------------------------------------------------------------------------------
    @staticmethod
    def _log(db: Session, actor: Actor, run, tool: str, args: dict, result: ToolResult, tag: str) -> None:
        run_id = getattr(run, "id", None)
        summary = result.would or (audit.summarize(result.output) if result.ok else result.reason)
        db.add(ToolCall(
            run_id=run_id, actor=actor.id, actor_type=actor.type, tool=tool, args_summary=audit.summarize(args),
            decision=result.decision, rule=result.rule, reason=result.reason, executed=result.executed,
            ok=result.ok, result_summary=audit.summarize(summary), redactions=result.redactions,
            injection_flags=len(result.injection_flags), latency_ms=result.latency_ms, tag=tag,
        ))
        outcome = "executed" if result.ok else ("failed" if result.executed else "blocked")
        if result.decision == DRY_RUN:
            outcome = "simulated"
        elif result.decision == REQUIRE_APPROVAL:
            outcome = "awaiting_approval"
        audit.record(
            db, action="tool.call", tool=tool, run_id=run_id,
            user=actor.id if actor.type == "human" else "",
            agent=actor.id if actor.type != "human" else "", actor_type=actor.type,
            input_summary=args, output_summary=summary, policy_decision=result.decision,
            approval=result.approval, result=outcome, latency_ms=result.latency_ms, tag=tag,
        )
