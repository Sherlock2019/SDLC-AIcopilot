import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Actor, Badge, Card, Decision, Legend, Page, Stat, StepControl, dateTime, money } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

const KIND = { ai: "ai", approval: "human", human_action: "human", system: "system" };

function FlowStrip() {
  const { run } = useLab();
  if (!run) return null;
  return (
    <div className="row" style={{ gap: 4, rowGap: 8 }}>
      <Badge kind="outline">BUSINESS REQUIREMENT</Badge>
      {run.steps.map((s) => (
        <span key={s.key} className="row" style={{ gap: 4 }}>
          <span className="faint">→</span>
          <Link to={s.page} title={s.description} style={{ textDecoration: "none" }}>
            <Badge kind={s.status === "blocked" ? "blocked" : KIND[s.kind]}>
              {s.status === "done" ? "✓ " : s.status === "pending" ? "" : "▶ "}{s.title.replace(/^(AI|Human) /, (m) => m.toUpperCase())}
            </Badge>
          </Link>
        </span>
      ))}
    </div>
  );
}

export function Dashboard() {
  const lab = useLab();
  const navigate = useNavigate();
  const { run, meta, artifacts, me } = lab;
  const stamp = run ? `${run.step_index}:${run.status}` : "";
  const { data: productivity } = useFetch(run ? `/api/productivity?run_id=${run.id}` : null, [stamp]);
  const { data: security } = useFetch("/api/observability/security", [stamp]);
  const { data: audit } = useFetch(run ? `/api/audit?run_id=${run.id}&limit=8` : null, [stamp]);
  const measured = productivity && productivity.measured;
  const tests = artifacts.tests && artifacts.tests.after;
  const admin = me && me.roles.includes("security_admin");
  return (
    <Page title="AI-SDLC Champion Lab" teach="dashboard"
      sub="One feature, taken through every stage of the software development life cycle by AI agents, with humans in control of every decision that matters.">
      <section className="card ai">
        <div className="grid g3">
          {meta.messages.map((m) => <div className="quote" key={m}>{m}</div>)}
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={() => { lab.setGuided(true); navigate("/journey"); }}>▶ START GUIDED DEMO</button>
          <Link className="btn" to="/journey">Open the SDLC journey</Link>
          <Link className="btn" to="/security">Capability &amp; escape-path auditor</Link>
          <span style={{ flex: 1 }} />
          {admin && <button className="btn sm" onClick={() => window.confirm("Reset all lab data to the initial state?") && lab.resetDemo()}>Reset demo</button>}
        </div>
      </section>

      <div className="grid g-auto">
        <Stat label="Workflow state" value={<span style={{ fontSize: 16 }}>{run.state.replaceAll("_", " ")}</span>} hint={`step ${Math.min(run.step_index + 1, run.total_steps)} of ${run.total_steps}`} />
        <Stat label="Human approvals given" value={measured ? measured.human_approvals : 0} hint="5 gates + 2 human-only actions" />
        <Stat label="AI cost, this feature" value={measured ? money(measured.ai_cost_usd) : "$0"} hint={measured ? `${measured.tokens.toLocaleString()} tokens · mock prices` : ""} />
        <Stat label="Actions blocked by policy" value={security ? security.policy_violations + security.kill_switch_blocks : 0} hint="all runs, including red-team attempts" />
        <Stat label="AI evaluation score" value={artifacts.evaluation ? `${artifacts.evaluation.score}%` : "-"} hint="gate: above 80%" />
        <Stat label="Test coverage" value={tests ? `${tests.coverage}%` : "-"} hint={tests ? `was ${artifacts.tests.before.coverage}% · measured` : "measured by running pytest"} />
      </div>

      <Card title="The journey" right={<Legend />}>
        <FlowStrip />
      </Card>

      {run.pending_approval && (
        <Card kind="human" title={`Waiting for a human: ${run.pending_approval.title}`} right={<Link className="btn human" to={run.current_step.page}>Review and decide</Link>}>
          <p>{run.pending_approval.summary}</p>
        </Card>
      )}
      {run.status === "blocked" && (
        <Card kind="blocked" title="The workflow is blocked by a control" right={<Link className="btn danger" to={run.current_step.page}>Open</Link>}>
          <p>{run.blocked_reason}</p>
        </Card>
      )}

      <div className="grid g3">
        <Card title="Pillar 1 · AI-assisted SDLC" kind="ai">
          <p className="muted">Requirements, architecture, code, tests, review, CI/CD, deployment, monitoring and RCA, each with a narrow agent.</p>
          <Link to="/journey">25 explicit steps →</Link>
        </Card>
        <Card title="Pillar 2 · AI safety and capability control" kind="blocked">
          <p className="muted">Policies, approvals, a capability graph with escape-path analysis, red-team simulation, kill switch and sandbox.</p>
          <Link to="/security">Verify what agents can reach →</Link>
        </Card>
        <Card title="Pillar 3 · Productivity and business value" kind="ok">
          <p className="muted">Cycle time, DORA metrics, token cost per feature and ROI, with simulated data clearly labelled.</p>
          <Link to="/productivity">Measure outcomes →</Link>
        </Card>
      </div>

      <div className="grid g2">
        <Card title="What AI may and may not do">
          <div className="grid g2">
            <div><h3 style={{ color: "var(--ok)", marginBottom: 6 }}>AI may</h3><ul>{meta.ai_may.map((x) => <li key={x}>{x}</li>)}</ul></div>
            <div><h3 style={{ color: "var(--blocked)", marginBottom: 6 }}>AI may NOT automatically</h3><ul>{meta.ai_may_not.map((x) => <li key={x}>{x}</li>)}</ul></div>
          </div>
        </Card>
        <Card title="Latest audit events" right={<Link to="/governance">Full audit timeline</Link>}>
          {audit && audit.entries.length ? (
            <div className="tl">
              {audit.entries.map((e) => (
                <div className="tl-item" key={e.id} style={{ gridTemplateColumns: "92px minmax(0,1fr) auto" }}>
                  <span className="small muted">{dateTime(e.ts).split(", ").pop()}</span>
                  <span className="small"><b>{e.agent || e.user}</b> · {e.action}{e.tool ? ` · ${e.tool}` : ""}</span>
                  {e.policy_decision ? <Decision value={e.policy_decision} /> : <Badge>{e.result}</Badge>}
                </div>
              ))}
            </div>
          ) : <p className="muted">Nothing yet. Start the guided demo; every action will appear here.</p>}
        </Card>
      </div>
    </Page>
  );
}

export function Journey() {
  const lab = useLab();
  const { run, meta, busy } = lab;
  const [text, setText] = useState(meta.default_requirement);
  const [version, setVersion] = useState("v2");
  return (
    <Page title="SDLC Journey" teach="journey" right={<Legend />}
      sub="Business requirement to continuous improvement as an explicit state machine. The engine cannot pass a human step.">
      {run.current_step && <StepControl keys={[run.current_step.key]} />}
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(0, 1fr)" }}>
        <Card title={`Run #${run.id} · ${run.title}`} right={<Badge kind="outline">prompt {run.prompt_version}</Badge>}>
          <div className="journey">
            {run.steps.map((s) => (
              <div key={s.key} className={`jstep ${KIND[s.kind]} ${s.status}`}>
                <span className="num">{s.status === "done" ? "✓" : s.index + 1}</span>
                <div>
                  <Link to={s.page} style={{ color: "inherit", fontWeight: 650 }}>{s.title}</Link>
                  <div className="small muted">{s.description}</div>
                  <code className="small faint">→ {s.state_done}</code>
                </div>
                <div className="row" style={{ justifyContent: "flex-end", maxWidth: 230 }}>
                  <Actor kind={s.status === "blocked" ? "blocked" : s.kind} />
                  {s.agent && <Badge>{s.agent}</Badge>}
                  {s.required_role && <Badge kind="human">role: {s.required_role}</Badge>}
                </div>
              </div>
            ))}
          </div>
        </Card>
        <div className="stack" style={{ alignContent: "start" }}>
          <Card title="Start with a business requirement">
            <label className="field">Feature request
              <textarea className="input" value={text} onChange={(e) => setText(e.target.value)} />
            </label>
            <label className="field" style={{ marginTop: 8 }}>Prompt version for the agents
              <select className="input" value={version} onChange={(e) => setVersion(e.target.value)}>
                <option value="v2">v2 · grounded prompt with policy context</option>
                <option value="v1">v1 · naive prompt (watch the security gate stop it)</option>
              </select>
            </label>
            <button className="btn primary" style={{ marginTop: 10 }} disabled={busy || text.trim().length < 8} onClick={() => lab.createRun(text, version)}>Create a new run</button>
            <p className="small muted" style={{ marginTop: 8 }}>With MOCK_AI the agents use scripted answers for the password-reset scenario. Tests, policy decisions, scans and evaluation are computed for real.</p>
          </Card>
          <Card title="How to read this page">
            <div className="stack small">
              <div><Actor kind="ai" /> an agent drafts, analyzes or recommends. It acts only through policy-checked tools.</div>
              <div><Actor kind="human" /> a named person with the right role decides. Recorded in the audit log.</div>
              <div><Actor kind="system" /> ordinary automation such as the CI pipeline. No model involved.</div>
              <div><Actor kind="blocked" /> a control stopped the action. That is the system working.</div>
            </div>
          </Card>
        </div>
      </div>
    </Page>
  );
}
