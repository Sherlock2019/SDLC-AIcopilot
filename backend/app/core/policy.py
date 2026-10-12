"""Policy engine: ALLOW / DENY / REQUIRE_APPROVAL, default deny, with non-overridable invariants.

Policies are YAML files under policies/. The engine is deliberately small and has no access to
the model: the model can ask for anything, and only this code decides what happens.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import settings

ALLOW = "ALLOW"
DENY = "DENY"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass
class PolicyResult:
    decision: str
    rule: str
    reason: str
    required_role: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW


@dataclass
class AgentPolicy:
    agent: str
    display_name: str = ""
    kind: str = "ai"
    owner: str = ""
    purpose: str = ""
    model: str = "default"
    classification: str = "internal"
    data_accessed: list = field(default_factory=list)
    cost_ceiling_usd: float = 0.0
    retention_days: int = 30
    network: object = "none"
    secrets: bool = False
    allowed: list = field(default_factory=list)
    denied: list = field(default_factory=list)
    require_approval: list = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    source: str = ""
    raw_yaml: str = ""

    @classmethod
    def from_yaml(cls, text: str, source: str = "") -> "AgentPolicy":
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict) or not data.get("agent"):
            raise ValueError("A policy file needs an `agent:` field.")
        known = {name for name in cls.__dataclass_fields__ if name not in {"source", "raw_yaml"}}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown policy fields: {sorted(unknown)}")
        for key in ("allowed", "denied", "require_approval", "data_accessed"):
            data[key] = list(data.get(key) or [])
        data["constraints"] = dict(data.get("constraints") or {})
        return cls(**data, source=source, raw_yaml=text)

    def summary(self) -> dict:
        return {
            "agent": self.agent, "display_name": self.display_name or self.agent, "kind": self.kind,
            "owner": self.owner, "purpose": self.purpose, "model": self.model,
            "classification": self.classification, "data_accessed": self.data_accessed,
            "cost_ceiling_usd": self.cost_ceiling_usd, "retention_days": self.retention_days,
            "network": self.network, "secrets": self.secrets, "allowed": self.allowed,
            "denied": self.denied, "require_approval": self.require_approval,
            "constraints": self.constraints, "source": self.source,
        }


def _matches(action: str, patterns: list) -> bool:
    return any(fnmatch.fnmatchcase(action, pattern) for pattern in patterns)


def _path_matches(path: str, patterns: list) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(name, p.replace("**/", "")) for p in patterns)


class PolicyStore:
    """Active policies for every identity, plus the global rules."""

    def __init__(self, policies: dict[str, AgentPolicy], global_rules: dict, scenarios: dict[str, str]):
        self.policies = policies
        self.global_rules = global_rules
        self.scenarios = scenarios
        self.defaults = {agent: policy.raw_yaml for agent, policy in policies.items()}

    @classmethod
    def load(cls, directory: Path | None = None) -> "PolicyStore":
        directory = directory or settings.policies_dir
        global_rules = yaml.safe_load((directory / "global.yaml").read_text()) or {}
        policies = {}
        for path in sorted((directory / "agents").glob("*.yaml")):
            policy = AgentPolicy.from_yaml(path.read_text(), source=f"policies/agents/{path.name}")
            policies[policy.agent] = policy
        scenarios = {p.stem: p.read_text() for p in sorted((directory / "scenarios").glob("*.yaml"))}
        return cls(policies, global_rules, scenarios)

    # --- lookups -----------------------------------------------------------------------------
    @property
    def never_for_ai(self) -> list:
        return self.global_rules.get("invariants", {}).get("never_for_ai", [])

    @property
    def approval_at_most(self) -> list:
        return self.global_rules.get("invariants", {}).get("approval_at_most", [])

    def approval_role(self, action: str) -> str:
        return (self.global_rules.get("require_approval") or {}).get(action, "engineer")

    def human_can(self, roles: list, permission: str) -> bool:
        table = self.global_rules.get("roles") or {}
        return any(permission in (table.get(role) or []) for role in roles or [])

    def get(self, agent: str) -> AgentPolicy | None:
        return self.policies.get(agent)

    def set_policy(self, yaml_text: str, source: str) -> AgentPolicy:
        policy = AgentPolicy.from_yaml(yaml_text, source=source)
        self.policies[policy.agent] = policy
        return policy

    def reset(self, agent: str) -> AgentPolicy:
        return self.set_policy(self.defaults[agent], source=f"policies/agents/{agent}.yaml")

    # --- decisions ---------------------------------------------------------------------------
    def evaluate(self, agent: str, action: str, args: dict | None = None) -> PolicyResult:
        policy = self.policies.get(agent)
        if policy is None:
            return PolicyResult(DENY, "unknown-identity", f"No policy exists for identity '{agent}'.")

        if policy.kind == "ai" and action in self.never_for_ai:
            return PolicyResult(
                DENY, "invariant:never_for_ai",
                f"'{action}' can never be performed by an AI agent. This rule cannot be overridden by a policy file.",
            )
        if _matches(action, policy.denied):
            return PolicyResult(DENY, f"{agent}.denied", f"'{action}' is explicitly denied for {agent}.")

        granted = _matches(action, policy.allowed) or _matches(action, policy.require_approval)
        if action in self.approval_at_most and granted:
            role = self.approval_role(action)
            return PolicyResult(
                REQUIRE_APPROVAL, "invariant:approval_at_most",
                f"'{action}' always needs approval from a human with the '{role}' role.", role,
            )
        if _matches(action, policy.require_approval):
            role = self.approval_role(action)
            return PolicyResult(REQUIRE_APPROVAL, f"{agent}.require_approval",
                                f"'{action}' needs approval from a human with the '{role}' role.", role)
        if _matches(action, policy.allowed):
            violation = self._constraint_violation(policy, action, args or {})
            if violation:
                return PolicyResult(DENY, f"{agent}.constraints.{action}", violation)
            return PolicyResult(ALLOW, f"{agent}.allowed", f"'{action}' is allowed for {agent}.")
        return PolicyResult(DENY, "default-deny", f"'{action}' is not in the allow list of {agent}.")

    @staticmethod
    def _constraint_violation(policy: AgentPolicy, action: str, args: dict) -> str:
        rules = policy.constraints.get(action) or {}
        if not rules:
            return ""
        branch = str(args.get("branch") or args.get("name") or "")
        if branch and _matches(branch, rules.get("deny_branches") or []):
            return f"Branch '{branch}' is protected: {policy.agent} may not write to it."
        files = args.get("files")
        paths = list(files) if isinstance(files, (dict, list)) else ([args["path"]] if args.get("path") else [])
        for path in paths:
            if _path_matches(path, rules.get("deny_paths") or []):
                return f"Path '{path}' is outside what {policy.agent} may write."
            allow_paths = rules.get("allow_paths")
            if allow_paths and not _path_matches(path, allow_paths):
                return f"Path '{path}' is not in the write allow list of {policy.agent}."
        return ""
