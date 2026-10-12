import { useState } from "react";
import { Link } from "react-router-dom";
import { Actor, Badge, Bar, Card, Decision, List, Mermaid, Page, Simulated, Stat, Tabs, dateTime, money, num } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

/* ------------------------------------------------------------------ Governance */
const yesNo = (value) => <Badge kind={value === "NO" ? "ok" : value === "YES" ? "blocked" : "human"}>{value}</Badge>;

function AuditTimeline() {
  const { run } = useLab();
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [decision, setDecision] = useState("");
  const [scope, setScope] = useState("run");
  const params = new URLSearchParams({ limit: "300" });
  if (q) params.set("q", q);
  if (actor) params.set("actor", actor);
  if (decision) params.set("decision", decision);
  if (scope === "run") params.set("run_id", run.id);
  const { data } = useFetch(`/api/audit?${params}`, [run.step_index, run.status]);
  const { meta } = useLab();
  const kind = (e) => (e.actor_type === "human" || e.user ? "human" : e.actor_type === "system" || e.agent === "ci-pipeline" ? "system" : "ai");
  return (
    <Card title="Audit timeline" right={<span className="small muted">{data ? `${data.entries.length} of ${data.total} entries` : ""}</span>}>
      <div className="row" style={{ marginBottom: 10 }}>
        <input className="input" style={{ maxWidth: 280 }} placeholder="Search action, tool, input, output…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search audit log" />
        <select className="input" style={{ width: 190 }} value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Actor">
          <option value="">All actors</option>{meta.agents.map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}<option value="ci-pipeline">ci-pipeline</option>{meta.users.map((u) => <option key={u.id} value={u.id}>{u.id} (human)</option>)}
        </select>
        <select className="input" style={{ width: 190 }} value={decision} onChange={(e) => setDecision(e.target.value)} aria-label="Decision">
          <option value="">All decisions</option>{["ALLOW", "DENY", "REQUIRE_APPROVAL", "BLOCKED_KILL_SWITCH", "DRY_RUN", "approved", "blocked"].map((d) => <option key={d}>{d}</option>)}
        </select>
        <select className="input" style={{ width: 160 }} value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Scope"><option value="run">This run</option><option value="all">Everything</option></select>
      </div>
      <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}><table>
        <thead><tr><th>Timestamp</th><th>Who</th><th>Action</th><th>Tool</th><th>Input → output</th><th>Policy</th><th>Approval</th><th>Result</th><th className="num">ms</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
        <tbody>{data && data.entries.map((e) => (
          <tr key={e.id}>
            <td className="small" style={{ whiteSpace: "nowrap" }}>{dateTime(e.ts)}</td>
            <td><Badge kind={kind(e)}>{e.user || e.agent || "system"}</Badge>{e.simulated && <> <Simulated label="seeded" /></>}</td>
            <td className="mono small">{e.action}</td><td className="mono small">{e.tool}</td>
            <td className="small muted" style={{ maxWidth: 330 }}>{e.input_summary}{e.output_summary ? <><br />→ {e.output_summary}</> : null}</td>
            <td>{e.policy_decision && <Decision value={e.policy_decision} />}</td><td className="small">{e.approval}</td><td className="small">{e.result}</td>
            <td className="num">{e.latency_ms || ""}</td><td className="num">{e.tokens ? num(e.tokens) : ""}</td><td className="num">{e.cost_usd ? money(e.cost_usd) : ""}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </Card>
  );
}

export function Governance() {
  const lab = useLab();
  const { run, flags } = lab;
  const { data: agents } = useFetch("/api/governance/agents", [run.step_index, run.status]);
  const { data: architecture } = useFetch("/api/architecture");
  const [tab, setTab] = useState("registry");
  const [open, setOpen] = useState("coding-agent");
  return (
    <Page title="Governance" stage="governance" teach="governance" steps={["continuous_improvement"]}
      sub="Every AI capability has an owner, a purpose, a boundary and an audit trail. The policy file is both the enforced rule and the governance record.">
      <div className="grid g2">
        <Card kind={flags.kill_switch ? "blocked" : ""} title="Kill switch" right={<Actor kind="human" label="● Operator control" />}>
          <p>{flags.kill_switch ? <b>TOOL EXECUTION DISABLED BY OPERATOR.</b> : "Stops every agent and pipeline tool call immediately."} Agents may still analyze and explain. They may not execute tools.</p>
          <button className={`btn ${flags.kill_switch ? "" : "danger"}`} onClick={() => lab.setFlags({ kill_switch: !flags.kill_switch })}>{flags.kill_switch ? "Re-enable AI tool execution" : "DISABLE ALL AI TOOL EXECUTION"}</button>
        </Card>
        <Card kind={flags.dry_run ? "warn" : ""} title="Dry run / simulation mode">
          <p>Shows what the AI <b>would</b> do: which tools it would call, with real policy decisions for each. No action is executed and the workflow does not advance.</p>
          <button className="btn" onClick={() => lab.setFlags({ dry_run: !flags.dry_run })}>{flags.dry_run ? "Turn dry-run mode off" : "Turn dry-run mode on"}</button>
        </Card>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[["registry", "AI capability registry"], ["audit", "Audit timeline"], ["flow", "How a tool call is governed"]]} />
      {tab === "registry" && agents && (
        <>
          <Card title="Agents and identities">
            <div className="table-wrap"><table>
              <thead><tr><th>Agent</th><th>Owner</th><th>Purpose</th><th>Production access</th><th>Secret access</th><th>Merge rights</th><th>Human approval</th><th>Reachability</th><th className="num">Cost / ceiling</th></tr></thead>
              <tbody>{agents.map((a) => (
                <tr key={a.agent} onClick={() => setOpen(a.agent)} style={{ cursor: "pointer", background: open === a.agent ? "var(--surface-2)" : undefined }}>
                  <td><b>{a.display_name}</b><div><Badge kind={a.kind === "ai" ? "ai" : "system"}>{a.kind === "ai" ? a.name : "not an AI"}</Badge></div></td>
                  <td>{a.owner}</td><td className="small">{a.purpose}</td><td>{yesNo(a.production_access)}</td><td>{yesNo(a.secret_access)}</td><td>{yesNo(a.merge_rights)}</td>
                  <td><Badge kind="human">{a.human_approval}</Badge></td>
                  <td><Badge kind={a.capability_status === "OK" ? "ok" : "blocked"}>{a.capability_status === "OK" ? "as declared" : `${a.unexpected_paths} unexpected`}</Badge></td>
                  <td className="num">{money(a.usage.cost_usd)}{a.cost_ceiling_usd ? ` / ${money(a.cost_ceiling_usd, 2)}` : ""}</td>
                </tr>
              ))}</tbody>
            </table></div>
          </Card>
          {agents.filter((a) => a.agent === open).map((a) => (
            <Card key={a.agent} title={`${a.display_name} · governance record`} right={<Badge>{a.source}</Badge>}>
              <div className="grid g2">
                <dl className="kv">
                  <dt>Model</dt><dd>{a.model} {a.prompt_versions.length ? `· prompt versions ${a.prompt_versions.join(", ")}` : ""}</dd>
                  <dt>Owner</dt><dd>{a.owner}</dd><dt>Purpose</dt><dd>{a.purpose}</dd>
                  <dt>Security classification</dt><dd><Badge>{a.classification}</Badge></dd>
                  <dt>Data accessed</dt><dd>{a.data_accessed.join(", ")}</dd>
                  <dt>Network access</dt><dd>{String(a.network)}</dd><dt>Secrets access</dt><dd>{a.secrets ? "yes" : "no"}</dd>
                  <dt>Cost ceiling</dt><dd>{a.cost_ceiling_usd ? `${money(a.cost_ceiling_usd, 2)} per run (enforced)` : "n/a"}</dd>
                  <dt>Retention</dt><dd>{a.retention_days} days</dd>
                  <dt>Usage</dt><dd>{a.usage.runs} model calls · {num(a.usage.tokens)} tokens · {money(a.usage.cost_usd)}</dd>
                </dl>
                <div className="stack">
                  <div><h3>Tools accessed</h3><div className="chip-list">{a.allowed.map((t) => <Badge key={t} kind="ok">{t}</Badge>)}</div></div>
                  <div><h3>Human approval required for</h3><div className="chip-list">{a.human_approval_actions.map((t) => <Badge key={t} kind="human">{t}</Badge>)}</div></div>
                  <div><h3>Denied</h3><div className="chip-list">{a.denied.map((t) => <Badge key={t} kind="blocked">{t}</Badge>)}</div></div>
                  <Link to="/security">Open in the capability auditor →</Link>
                </div>
              </div>
            </Card>
          ))}
        </>
      )}
      {tab === "audit" && <AuditTimeline />}
      {tab === "flow" && architecture && (
        <Card title="Agent request → policy check → permission check → approval check → tool execution → audit log">
          <Mermaid chart={architecture.tool_flow} />
        </Card>
      )}
      {lab.artifacts.improvement && (
        <Card title="Governance summary for this run" kind="ai">
          <p><b>{lab.artifacts.improvement.summary.headline}</b></p>
          <div className="grid g3">
            <div><h3>Observations</h3><List items={lab.artifacts.improvement.summary.observations} /></div>
            <div><h3>Improvements</h3><List items={lab.artifacts.improvement.summary.improvements} /></div>
            <div><h3>Feedback loop</h3><List items={lab.artifacts.improvement.feedback_loop} /></div>
          </div>
        </Card>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Productivity */
function fmt(value, unit) {
  if (unit === "min" && value >= 60) return `${Math.floor(value / 60)}h ${String(Math.round(value % 60)).padStart(2, "0")}m`;
  if (unit === "hours" && value >= 24) return `${(value / 24).toFixed(1)} days`;
  return unit === "%" ? `${value}%` : `${value} ${unit}`;
}

function Compare({ metric, labels }) {
  const improved = metric.better === "lower" ? metric.after_value < metric.before_value : metric.after_value > metric.before_value;
  const change = Math.round((100 * (metric.after_value - metric.before_value)) / metric.before_value);
  const max = Math.max(metric.before_value, metric.after_value);
  return (
    <div className="card">
      <div className="row between"><h3>{metric.label}</h3><Badge kind={improved ? "ok" : "blocked"}>{change > 0 ? "+" : ""}{change}%</Badge></div>
      <div className="stack" style={{ marginTop: 10, gap: 6 }}>
        <div><div className="row between small"><span className="muted">{labels[0]}</span><b>{fmt(metric.before_value, metric.unit)}</b></div><Bar value={metric.before_value} max={max} /></div>
        <div><div className="row between small"><span className="muted">{labels[1]}</span><b>{fmt(metric.after_value, metric.unit)}</b></div><Bar value={metric.after_value} max={max} kind="ok" /></div>
      </div>
    </div>
  );
}

export function Productivity() {
  const { run } = useLab();
  const { data } = useFetch(`/api/productivity?run_id=${run.id}`, [run.step_index, run.status]);
  if (!data) return null;
  const m = data.measured, roi = data.roi;
  return (
    <Page title="Productivity" stage="productivity" teach="productivity"
      sub="Does AI assistance pay for itself? Compare flow, quality and stability before and after, and set the value against the exact token cost.">
      <Card kind="warn"><b>{data.simulated_notice}</b> The section “Measured in this session” below is the only part computed from this lab's own records.</Card>
      <Card title="BEFORE AI → AFTER AI" right={<Simulated />}>
        <div className="grid g3">{data.comparison.map((x) => <Compare key={x.name} metric={x} labels={["Before AI", "After AI"]} />)}</div>
      </Card>
      <Card title="Return on investment" right={<Simulated />}>
        <div className="grid g-auto">
          <Stat label="Engineer hours saved" value={`${roi.engineer_hours_saved}h`} hint="per feature" />
          <Stat label="AI cost" value={money(roi.ai_cost_usd, 2)} /><Stat label="Cost per feature" value={money(roi.cost_per_feature_usd, 2)} />
          <Stat label="Estimated engineering value" value={money(roi.engineering_value_usd, 0)} hint={`at ${money(roi.hourly_rate_usd, 0)} per hour`} />
          <Stat label="ROI" value={`${roi.roi_multiple}×`} hint={roi.formula} kind="ok" />
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>An ROI this large is typical on paper because tokens are cheap next to engineer time. The honest questions are whether the hours saved are real, and what review and rework cost. That is why the numbers above are labelled simulated.</p>
      </Card>
      <Card title="DORA metrics: without AI → with AI" right={<Simulated />}>
        <div className="grid g4">{data.dora.map((x) => <Compare key={x.name} metric={x} labels={["Without AI", "With AI"]} />)}</div>
        <div className="card flat" style={{ marginTop: 12 }}><b>Read this before quoting the numbers.</b> {data.dora_note}</div>
      </Card>
      {m && (
        <Card title="Measured in this session" kind="ok" right={<Badge kind="ok">REAL · run #{run.id}</Badge>}>
          <div className="grid g-auto">
            <Stat label="AI cost for this feature" value={money(m.ai_cost_usd)} hint={`${num(m.tokens)} tokens`} />
            <Stat label="Model calls / tool calls" value={`${m.agent_runs} / ${m.tool_calls}`} />
            <Stat label="Human approvals" value={m.human_approvals} hint={`${m.human_steps} human steps of ${m.steps_total}`} />
            <Stat label="Actions blocked" value={m.blocked_actions} />
            <Stat label="Tests" value={m.tests_after != null ? `${m.tests_before} → ${m.tests_after}` : "-"} />
            <Stat label="Coverage" value={m.coverage_after != null ? `${m.coverage_before}% → ${m.coverage_after}%` : "-"} />
            <Stat label="Evaluation score" value={m.evaluation_score != null ? `${m.evaluation_score}%` : "-"} />
            <Stat label="Progress" value={`${m.steps_done} / ${m.steps_total}`} hint="workflow steps" />
          </div>
          <p className="small muted" style={{ marginTop: 10 }}>{m.note}</p>
        </Card>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Learn */
export function Learn() {
  const { learn } = useLab();
  const [current, setCurrent] = useState(1);
  const [answers, setAnswers] = useState({});
  if (!learn) return null;
  const lesson = learn.lessons.find((l) => l.id === current);
  const picked = answers[lesson.id];
  const score = learn.lessons.filter((l) => answers[l.id] === l.quiz.answer).length;
  return (
    <Page title="Learn" teach="learn" sub="Nineteen lessons that connect AI, software engineering, security, evaluation, operations and governance into one system."
      right={<Badge kind="ai">{score} / {learn.lessons.length} quizzes correct</Badge>}>
      <div className="grid" style={{ gridTemplateColumns: "280px minmax(0, 1fr)" }}>
        <Card title="Modules">
          <div className="stack" style={{ gap: 2 }}>
            {learn.lessons.map((l) => (
              <button key={l.id} className={`btn sm ${l.id === current ? "primary" : "ghost"}`} style={{ justifyContent: "flex-start", textAlign: "left" }} onClick={() => setCurrent(l.id)}>
                <span style={{ width: 20 }}>{answers[l.id] === l.quiz.answer ? "✓" : l.id}</span>{l.title}
              </button>
            ))}
          </div>
        </Card>
        <div className="stack" style={{ alignContent: "start" }}>
          <Card title={`${lesson.id}. ${lesson.title}`} right={<Link className="btn sm" to={lesson.page}>See it in the lab</Link>}>
            <h3>Concept</h3><p style={{ fontSize: 15 }}>{lesson.concept}</p>
            <div className="grid g2">
              <div className="card flat"><h3>Simple example</h3><p style={{ margin: "4px 0 0" }}>{lesson.simple_example}</p></div>
              <div className="card flat"><h3>Real engineering example</h3><p style={{ margin: "4px 0 0" }}>{lesson.real_example}</p></div>
            </div>
            <div className="card warn" style={{ marginTop: 12 }}><h3>Risk</h3><p style={{ margin: "4px 0 0" }}>{lesson.risk}</p></div>
          </Card>
          <Card title="Mini quiz">
            <p><b>{lesson.quiz.question}</b></p>
            <div className="stack" style={{ gap: 6 }}>
              {lesson.quiz.options.map((option, i) => {
                const chosen = picked === i, right = i === lesson.quiz.answer;
                return <button key={i} className="btn" style={{ justifyContent: "flex-start", borderColor: picked != null && right ? "var(--ok)" : chosen ? "var(--blocked)" : undefined, background: picked != null && right ? "var(--ok-bg)" : chosen ? "var(--blocked-bg)" : undefined }}
                  onClick={() => setAnswers({ ...answers, [lesson.id]: i })}>{picked != null && right ? "✓ " : chosen ? "✗ " : ""}{option}</button>;
              })}
            </div>
            {picked != null && <p style={{ marginTop: 10 }}><b>{picked === lesson.quiz.answer ? "Correct." : "Not quite."}</b> {lesson.quiz.explanation}</p>}
            <div className="row between" style={{ marginTop: 10 }}>
              <button className="btn sm" disabled={current === 1} onClick={() => setCurrent(current - 1)}>← Previous</button>
              <button className="btn sm" disabled={current === learn.lessons.length} onClick={() => setCurrent(current + 1)}>Next lesson →</button>
            </div>
          </Card>
        </div>
      </div>
    </Page>
  );
}

/* ------------------------------------------------------------------ Architecture diagram */
export function ArchitectureDiagram() {
  const { data } = useFetch("/api/architecture");
  const { meta } = useLab();
  const [tab, setTab] = useState("system");
  if (!data) return null;
  return (
    <Page title="Architecture Diagram" teach="architecture_diagram" sub="How the lab itself is built, and the security architecture that every tool call passes through.">
      <Tabs value={tab} onChange={setTab} tabs={[["system", "System"], ["flow", "Tool-call flow"], ["states", "Workflow state machine"], ["security", "Security architecture"]]} />
      {tab === "system" && (
        <>
          <Card title="System architecture"><Mermaid chart={data.system} /></Card>
          <div className="grid g2">
            <Card title="Model provider abstraction">
              <table><thead><tr><th>Provider</th><th>Needs</th><th></th></tr></thead>
                <tbody>{meta.providers.map((p) => <tr key={p.name}><td className="mono">{p.name}</td><td className="small muted">{p.requires.join(", ") || "nothing"}</td>
                  <td>{p.active && <Badge kind="ok">active</Badge>} {p.verified_in_ci ? <Badge kind="ok">exercised by tests</Badge> : <Badge kind="warn">needs your credentials to verify</Badge>}</td></tr>)}</tbody></table>
            </Card>
            <Card title="What is real and what is simplified" kind="warn"><List items={data.honest_notes} /></Card>
          </div>
        </>
      )}
      {tab === "flow" && <Card title="Every tool call, for every identity"><Mermaid chart={data.tool_flow} /></Card>}
      {tab === "states" && <Card title="State transitions (human steps are interrupts the engine cannot pass)"><Mermaid chart={data.state_machine} /></Card>}
      {tab === "security" && (
        <>
          <Card kind="blocked" title="LLM output is UNTRUSTED INPUT"><p style={{ margin: 0 }}>Everything a model returns is parsed strictly, validated against a contract, scanned for secrets, tested in a sandbox, evaluated against fixtures and reviewed by a human before it can affect anything that matters.</p></Card>
          <div className="grid g3">{data.principles.map(([name, text]) => <Card key={name} title={name}><p className="muted" style={{ margin: 0 }}>{text}</p></Card>)}</div>
        </>
      )}
    </Page>
  );
}
