"""Workflow engine: a persisted state machine with human approval gates.

    REQUIREMENT_CREATED -> REQUIREMENT_ANALYZED -> (waiting for human) -> REQUIREMENT_APPROVED -> ...

The engine never advances past an approval step on its own. Approvals are decided only through
`decide()`, which requires a human actor holding the required role. The same step list can be
compiled to a LangGraph StateGraph (see langgraph_adapter.py).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import services
from ..agents.base import RunContext, StepBlocked
from ..core import audit
from ..core.gateway import KILL_SWITCH_MESSAGE, Actor
from ..models import Approval, PullRequest, WorkflowRun, to_dict, utcnow
from .steps import STEP_INDEX, STEPS, Step

INITIAL_STATE = "REQUIREMENT_CREATED"
DECISIONS = {"approve": "approved", "request_changes": "changes_requested", "reject": "rejected"}


class WorkflowError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def current_step(run: WorkflowRun) -> Step | None:
    return STEPS[run.step_index] if run.step_index < len(STEPS) else None


def pending_approval(db: Session, run: WorkflowRun) -> Approval | None:
    return db.query(Approval).filter(Approval.run_id == run.id, Approval.status == "pending").order_by(
        Approval.id.desc()).first()


def describe(db: Session, run: WorkflowRun) -> dict:
    steps = []
    for index, step in enumerate(STEPS):
        if index < run.step_index:
            status = "done"
        elif index == run.step_index and run.status not in ("completed", "rejected"):
            status = {"blocked": "blocked", "waiting_approval": "waiting"}.get(run.status, "current")
        else:
            status = "pending"
        steps.append({"index": index, "key": step.key, "title": step.title, "kind": step.kind,
                      "agent": step.agent, "page": step.page, "description": step.description,
                      "state_done": step.state_done, "status": status, "learn": step.learn,
                      "required_role": step.approval.get("role", ""), "permission": step.permission})
    approval = pending_approval(db, run)
    step = current_step(run)
    return {
        **{k: v for k, v in to_dict(run).items() if k != "artifacts"},
        "steps": steps, "total_steps": len(STEPS),
        "current_step": steps[run.step_index] if step else None,
        "pending_approval": to_dict(approval) if approval else None,
    }


def _summarize_for_approval(run: WorkflowRun, step: Step) -> tuple[str, dict]:
    artifacts = run.artifacts or {}
    kind = step.approval["kind"]
    if kind == "requirement":
        analysis = artifacts["requirement_analysis"]["analysis"]
        return (f"{len(analysis.get('acceptance_criteria', []))} acceptance criteria, "
                f"{len(analysis.get('questions', []))} open questions, "
                f"{len(analysis.get('conflicts', []))} conflict(s) with policy."), {}
    if kind == "architecture":
        proposal = artifacts["architecture"]
        return f"Three options proposed. AI recommends option {proposal['recommended']}.", {
            "recommended": proposal["recommended"], "options": [o["key"] for o in proposal["options"]]}
    if kind == "pr":
        return f"Pull request #{artifacts['pr']['number']} with pipeline result '{artifacts['ci']['status']}'.", {}
    if kind == "production":
        deployment = artifacts["deployment"]
        return (f"Deploy {deployment['version']} to PRODUCTION-SIMULATION. "
                f"Deployment Advisor recommends {deployment['advice']['recommendation']}."), {
            "version": deployment["version"]}
    return "Roll production back to the previous healthy build, as recommended by the RCA Agent.", {}


def _open_approval(db: Session, run: WorkflowRun, step: Step) -> Approval:
    existing = pending_approval(db, run)
    if existing is not None and existing.step_key == step.key:
        return existing
    summary, payload = _summarize_for_approval(run, step)
    requested_by = STEPS[run.step_index - 1].agent or "workflow"
    approval = Approval(run_id=run.id, kind=step.approval["kind"], step_key=step.key,
                        action=step.approval.get("action", ""), title=step.approval["title"], summary=summary,
                        required_role=step.approval["role"], requested_by=requested_by, payload=payload)
    db.add(approval)
    db.flush()
    run.status = "waiting_approval"
    audit.record(db, action="approval.requested", agent=requested_by, actor_type="agent", run_id=run.id,
                 input_summary=approval.title, output_summary=summary, approval=f"#{approval.id} pending",
                 result="awaiting_approval")
    return approval


def _complete(db: Session, run: WorkflowRun, step: Step) -> None:
    run.state, run.step_index, run.status, run.blocked_reason = step.state_done, run.step_index + 1, "active", ""
    run.updated_at = utcnow()
    following = current_step(run)
    if following is None:
        run.status = "completed"
    elif following.kind == "approval":
        _open_approval(db, run, following)


def dry_run(db: Session, run: WorkflowRun, user: Actor) -> dict:
    """Show what the next step WOULD do. Every planned call gets a real policy decision; nothing executes."""
    step = current_step(run)
    if step is None:
        raise WorkflowError("The run is complete.")
    gateway, store = services.get_gateway(), services.get_store()
    plan = []
    for identity, tool, args in step.plan:
        policy = store.get(identity)
        actor = Actor(identity, "system" if policy is not None and policy.kind == "system" else "agent")
        result = gateway.call(db, actor, tool, args, run=run, dry_run=True, tag="dry-run")
        verdict = result.reason.replace("Nothing was executed.", "").strip() if result.decision == "DRY_RUN" else result.decision
        plan.append({"identity": identity, "tool": tool, "args": args, "would": result.would or result.reason,
                     "decision": result.decision, "verdict": verdict, "rule": result.rule})
    if step.kind == "approval":
        plan.append({"identity": "human", "tool": "approval", "args": {}, "decision": "REQUIRE_APPROVAL",
                     "would": f"Would request approval from a human with the '{step.approval['role']}' role",
                     "verdict": "Human decision required", "rule": "workflow"})
    db.commit()
    return {"step": step.key, "title": step.title, "kind": step.kind, "executed": False, "plan": plan,
            "message": "DRY RUN - no action was executed."}


def advance(db: Session, run: WorkflowRun, user: Actor) -> dict:
    """Execute the next step, or report what the run is waiting for."""
    step = current_step(run)
    if step is None or run.status in ("completed", "rejected"):
        raise WorkflowError(f"The run is {run.status}.")
    flags = audit.get_flags(db)
    store = services.get_store()
    if not store.human_can(user.roles, "run.advance") and not store.human_can(user.roles, step.permission or "-"):
        raise WorkflowError(f"User '{user.id}' has no role that may advance a run.", 403)

    if step.kind == "approval":
        approval = _open_approval(db, run, step)
        db.commit()
        return {"status": "waiting_approval", "step": step.key, "approval": to_dict(approval)}

    if step.kind == "human_action":
        if not store.human_can(user.roles, step.permission):
            raise WorkflowError(f"'{step.title}' needs a human with permission '{step.permission}'.", 403)
    elif flags.get("dry_run"):
        return dry_run(db, run, user)
    elif flags.get("kill_switch"):
        run.status, run.blocked_reason = "blocked", KILL_SWITCH_MESSAGE
        audit.record(db, action="step.blocked", agent=step.agent, run_id=run.id, input_summary=step.key,
                     output_summary=KILL_SWITCH_MESSAGE, policy_decision="BLOCKED_KILL_SWITCH", result="blocked")
        db.commit()
        return {"status": "blocked", "step": step.key, "reason": KILL_SWITCH_MESSAGE, "detail": {}}

    context = RunContext(db, run, user)
    try:
        step.handler(context)
    except StepBlocked as blocked:
        run.status, run.blocked_reason = "blocked", blocked.reason
        audit.record(db, action="step.blocked", agent=step.agent, run_id=run.id, input_summary=step.key,
                     output_summary=blocked.reason, result="blocked",
                     user=user.id if step.kind == "human_action" else "")
        db.commit()
        return {"status": "blocked", "step": step.key, "reason": blocked.reason, "detail": blocked.detail}
    except Exception:
        db.rollback()
        raise
    audit.record(db, action="step.completed", agent=step.agent, run_id=run.id, input_summary=step.key,
                 output_summary=step.state_done, result="completed",
                 user=user.id if step.kind == "human_action" else "",
                 actor_type={"human_action": "human", "system": "system"}.get(step.kind, "agent"))
    _complete(db, run, step)
    db.commit()
    return {"status": run.status, "step": step.key, "state": run.state}


def decide(db: Session, approval: Approval, user: Actor, decision: str, comment: str = "",
           payload: dict | None = None) -> dict:
    """A human decision on a pending approval. Agents have no code path into this function."""
    if decision not in DECISIONS:
        raise WorkflowError(f"Unknown decision '{decision}'.", 422)
    if user.type != "human":
        raise WorkflowError("Only a human can decide an approval.", 403)
    if approval.status != "pending":
        raise WorkflowError(f"Approval is already {approval.status}.")
    run = db.get(WorkflowRun, approval.run_id)
    step = STEPS[STEP_INDEX[approval.step_key]]
    store = services.get_store()
    if not store.human_can(user.roles, step.approval["permission"]):
        raise WorkflowError(f"This approval needs the '{approval.required_role}' role. "
                            f"{user.id} has roles: {', '.join(user.roles) or 'none'}.", 403)

    approval.status, approval.decided_by = DECISIONS[decision], user.id
    approval.comment, approval.decided_at = comment, utcnow()
    approval.payload = {**(approval.payload or {}), **(payload or {})}
    audit.record(db, action=f"approval.{approval.status}", user=user.id, actor_type="human", run_id=run.id,
                 input_summary=approval.title, output_summary=comment or approval.summary,
                 approval=f"#{approval.id} {approval.status} by {user.id}", result=approval.status)

    artifacts = dict(run.artifacts or {})
    pr = db.query(PullRequest).filter(PullRequest.run_id == run.id).order_by(PullRequest.id.desc()).first()
    if decision == "approve":
        if approval.kind == "architecture":
            proposal = dict(artifacts["architecture"])
            selected = (payload or {}).get("option") or proposal["recommended"]
            if selected not in [o["key"] for o in proposal["options"]]:
                raise WorkflowError(f"Unknown option '{selected}'.", 422)
            proposal["selected"], proposal["approved_by"] = selected, user.id
            artifacts["architecture"] = proposal
            run.artifacts = artifacts
        if approval.kind == "pr" and pr is not None:
            pr.status = "approved"
        _complete(db, run, step)
    elif decision == "request_changes":
        target = step.rework_to or STEPS[run.step_index - 1].key
        feedback = dict(artifacts.get("feedback") or {})
        feedback[target] = feedback.get(target, []) + [{"by": user.id, "comment": comment}]
        artifacts["feedback"] = feedback
        run.artifacts = artifacts
        run.step_index, run.status = STEP_INDEX[target], "active"
        run.state = STEPS[run.step_index - 1].state_done if run.step_index else INITIAL_STATE
        if approval.kind == "pr" and pr is not None:
            pr.status = "changes_requested"
    else:
        run.status, run.blocked_reason = "rejected", f"Rejected by {user.id}: {comment or 'no comment'}"
        if approval.kind == "pr" and pr is not None:
            pr.status = "rejected"
    db.commit()
    return {"approval": to_dict(approval), "run_status": run.status, "state": run.state}


def fast_forward(db: Session, run: WorkflowRun, user: Actor, until: str = "", max_steps: int = 40) -> dict:
    """Presenter convenience: run steps and approve as the signed-in human until `until` is the current step.

    It stops at anything a control blocks. It never weakens a control to keep going."""
    log = []
    for _ in range(max_steps):
        step = current_step(run)
        if step is None or run.status in ("completed", "rejected") or (until and step.key == until):
            break
        if step.kind == "approval":
            approval = _open_approval(db, run, step)
            try:
                decide(db, approval, user, "approve", "Approved during guided fast-forward")
            except WorkflowError as error:
                log.append({"step": step.key, "status": "needs_other_role", "reason": str(error)})
                break
            log.append({"step": step.key, "status": "approved", "by": user.id})
            continue
        result = advance(db, run, user)
        log.append({"step": step.key, "status": result.get("status", "dry_run"), "reason": result.get("reason", "")})
        if result.get("status") == "blocked" or result.get("executed") is False:
            break
    return {"log": log, "run_status": run.status, "state": run.state}


def to_mermaid() -> str:
    lines = ["stateDiagram-v2", "  direction LR", f"  [*] --> {INITIAL_STATE}"]
    previous = INITIAL_STATE
    for step in STEPS:
        label = {"approval": "human approves", "human_action": "human action", "system": "pipeline"}.get(step.kind, step.agent)
        lines.append(f"  {previous} --> {step.state_done}: {label}")
        previous = step.state_done
    lines.append(f"  {previous} --> [*]")
    return "\n".join(lines)
