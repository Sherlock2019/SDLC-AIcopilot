"""Capability and escape-path auditor.

A policy file states what an agent is GRANTED. This module computes what the agent can REACH,
by walking the graph

    AGENT -> MCP SERVER -> TOOL -> API -> RESOURCE -> ACTION (-> SYSTEM -> ACTION ...)

including the indirect links between systems declared in policies/topology.yaml. Any sensitive
action that is reachable without a control, and that the policy never declared, is reported as
UNEXPECTED TRANSITIVE ACCESS together with the complete path.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from ..config import settings
from .policy import AgentPolicy, PolicyStore, _matches

SEVERITY = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
STATUS_RANK = {"unexpected": 4, "declared": 3, "gated": 2, "contained": 1}


@lru_cache(maxsize=1)
def load_topology() -> dict:
    return yaml.safe_load((settings.policies_dir / "topology.yaml").read_text())


def tool_catalog() -> dict:
    return load_topology()["tools"]


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.out: dict[str, list[dict]] = {}

    def node(self, node_id: str, kind: str, label: str, **extra) -> str:
        self.nodes.setdefault(node_id, {"id": node_id, "type": kind, "label": label, **extra})
        return node_id

    def edge(self, source: str, target: str, kind: str = "grant", **extra) -> None:
        if any(e["from"] == source and e["to"] == target for e in self.out.get(source, [])):
            return
        edge = {"from": source, "to": target, "kind": kind, **extra}
        self.edges.append(edge)
        self.out.setdefault(source, []).append(edge)


def build_graph(policy: AgentPolicy, store: PolicyStore, topology: dict | None = None) -> Graph:
    topology = topology or load_topology()
    tools, servers, systems = topology["tools"], topology["servers"], topology.get("systems", {})
    graph = Graph()
    agent_id = graph.node(f"agent:{policy.agent}", "agent", policy.display_name or policy.agent)

    def add_tool(name: str, control: dict | None) -> None:
        spec = tools[name]
        server = graph.node(f"server:{spec['server']}", "server", servers[spec["server"]])
        tool = graph.node(f"tool:{name}", "tool", name, description=spec["description"])
        api = graph.node(f"api:{name}", "api", spec["api"])
        resource = graph.node(f"resource:{spec['resource']}", "resource", spec["resource"])
        action = graph.node(f"action:{name}", "action", name, sensitivity=spec["sensitivity"])
        graph.edge(agent_id, server)
        graph.edge(server, tool, control=control) if control else graph.edge(server, tool)
        graph.edge(tool, api)
        graph.edge(api, resource)
        graph.edge(resource, action)

    for name in tools:
        if policy.kind == "ai" and name in store.never_for_ai:
            continue
        if _matches(name, policy.denied):
            continue
        needs_approval = _matches(name, policy.require_approval) or (
            name in store.approval_at_most and _matches(name, policy.allowed)
        )
        if needs_approval:
            add_tool(name, {"type": "approval", "name": f"Human approval ({store.approval_role(name)})"})
        elif _matches(name, policy.allowed):
            add_tool(name, None)

    def ensure(node_id: str) -> str:
        kind, name = node_id.split(":", 1)
        if kind == "action":
            return graph.node(node_id, "action", name, sensitivity=tools.get(name, {}).get("sensitivity", "medium"))
        return graph.node(node_id, kind, systems.get(name, name))

    # Links are added to a fixed point: a link applies once its source node is reachable.
    pending = list(topology.get("links", []))
    changed = True
    while changed:
        changed = False
        for link in list(pending):
            if link["from"] in graph.nodes:
                ensure(link["to"])
                graph.edge(
                    link["from"], link["to"], kind="link", why=link.get("why", ""),
                    control=link.get("control"), remediation=link.get("remediation", []),
                    accepted_risk=link.get("accepted_risk", ""),
                )
                pending.remove(link)
                changed = True
    return graph


def _paths_to_actions(graph: Graph, start: str) -> list[list[dict]]:
    """Every simple path (as a list of edges) from the agent to an action node."""
    found: list[list[dict]] = []

    def walk(node: str, trail: list[dict], seen: set) -> None:
        for edge in graph.out.get(node, []):
            target = edge["to"]
            if target in seen:
                continue
            path = trail + [edge]
            if graph.nodes[target]["type"] == "action":
                found.append(path)
            walk(target, path, seen | {target})

    walk(start, [], {start})
    return found


def audit_agent(agent: str, store: PolicyStore) -> dict:
    policy = store.get(agent)
    if policy is None:
        raise KeyError(agent)
    graph = build_graph(policy, store)
    start = f"agent:{agent}"
    declared = sorted(set(policy.allowed) | set(policy.require_approval))
    forbidden = sorted(set(policy.denied) | (set(store.never_for_ai) if policy.kind == "ai" else set()))

    best: dict[tuple[str, str], dict] = {}
    for path in _paths_to_actions(graph, start):
        action = graph.nodes[path[-1]["to"]]["label"]
        controls = [e["control"] for e in path if e.get("control")]
        transitive = any(e["kind"] == "link" for e in path)
        if any(c["type"] == "blocks" for c in controls):
            status = "contained"
        elif any(c["type"] == "approval" for c in controls):
            status = "gated"
        elif action in declared:
            status = "declared"
        else:
            status = "unexpected"
        entry_tool = next(graph.nodes[e["to"]]["label"] for e in path if graph.nodes[e["to"]]["type"] == "tool")
        record = {
            "action": action,
            "sensitivity": graph.nodes[path[-1]["to"]].get("sensitivity", "medium"),
            "status": status,
            "transitive": transitive,
            "entry_tool": entry_tool,
            "path": [graph.nodes[start]] + [graph.nodes[e["to"]] for e in path],
            "controls": controls,
            "why": [e["why"] for e in path if e.get("why")],
            "remediation": [r for e in path for r in e.get("remediation", [])],
            "accepted_risk": next((e["accepted_risk"] for e in path if e.get("accepted_risk")), ""),
        }
        key = (action, entry_tool)
        current = best.get(key)
        better = current is None or (STATUS_RANK[status], -len(path)) > (
            STATUS_RANK[current["status"]], -len(current["path"]))
        if better:
            best[key] = record

    reach = sorted(best.values(), key=lambda r: (-STATUS_RANK[r["status"]], r["action"], len(r["path"])))

    findings = []
    for record in reach:
        if record["status"] != "unexpected":
            continue
        severity = SEVERITY.get(record["sensitivity"], "MEDIUM")
        if record["accepted_risk"] and severity in {"CRITICAL", "HIGH"}:
            severity = "MEDIUM"
        findings.append({
            "severity": severity,
            "title": "UNEXPECTED TRANSITIVE ACCESS" if record["transitive"] else "UNDECLARED DIRECT ACCESS",
            "agent": agent,
            "action": record["action"],
            "explicitly_denied": record["action"] in forbidden,
            "path": [node["label"] for node in record["path"]],
            "path_nodes": record["path"],
            "why": record["why"],
            "recommendation": list(dict.fromkeys(record["remediation"])),
            "accepted_risk": record["accepted_risk"],
        })

    worst_by_action: dict[str, str] = {}
    for record in reach:
        current = worst_by_action.get(record["action"])
        if current is None or STATUS_RANK[record["status"]] > STATUS_RANK[current]:
            worst_by_action[record["action"]] = record["status"]
    forbidden_check = [
        {"action": action, "reachable_as": worst_by_action.get(action, "not_reachable"),
         "ok": worst_by_action.get(action, "not_reachable") in {"not_reachable", "contained", "gated"}}
        for action in forbidden
    ]
    findings.sort(key=lambda f: (list(SEVERITY.values()).index(f["severity"]), len(f["path"])))
    serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    highlighted = {node["id"] for f in serious for node in f["path_nodes"]}
    flagged_edges = {(a["id"], b["id"]) for f in serious for a, b in zip(f["path_nodes"], f["path_nodes"][1:])}
    return {
        "agent": agent,
        "display_name": policy.display_name or agent,
        "policy_source": policy.source,
        "declared": declared,
        "forbidden": forbidden,
        "reachable_actions": sorted(worst_by_action),
        "undeclared_reachable": sorted(a for a, s in worst_by_action.items() if s == "unexpected"),
        "reach": [{k: v for k, v in r.items() if k != "path"} | {"path": [n["label"] for n in r["path"]]} for r in reach],
        "forbidden_check": forbidden_check,
        "findings": [{k: v for k, v in f.items() if k != "path_nodes"} for f in findings],
        "summary": {
            "critical": sum(f["severity"] == "CRITICAL" for f in findings),
            "high": sum(f["severity"] == "HIGH" for f in findings),
            "medium": sum(f["severity"] == "MEDIUM" for f in findings),
            "status": "CRITICAL" if any(f["severity"] == "CRITICAL" for f in findings) else "OK",
        },
        "graph": {
            "nodes": [n | {"flagged": n["id"] in highlighted} for n in graph.nodes.values()],
            "edges": [
                {"from": e["from"], "to": e["to"], "kind": e["kind"], "why": e.get("why", ""),
                 "control": e.get("control"),
                 "accepted_risk": bool(e.get("accepted_risk")),
                 "flagged": (e["from"], e["to"]) in flagged_edges}
                for e in graph.edges
            ],
        },
    }


def audit_all(store: PolicyStore) -> list[dict]:
    reports = []
    for agent in sorted(store.policies):
        report = audit_agent(agent, store)
        reports.append({k: report[k] for k in ("agent", "display_name", "summary", "findings", "policy_source")})
    return reports
