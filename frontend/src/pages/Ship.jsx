import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Actor, Badge, Bar, Card, Decision, DiffViewer, LineChart, List, Markdown, NotRun, Page, Provenance, Simulated, Stat, Tabs, ToolCalls, dateTime, money, num, time } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

/* ------------------------------------------------------------------ CI/CD */
export function CiCd() {
  const { run } = useLab();
  const { data } = useFetch(`/api/pipelines?run_id=${run.id}`, [run.step_index, run.status]);
  const [selected, setSelected] = useState("test");
  const current = (data || []).find((p) => p.run_id === run.id);
  const history = (data || []).filter((p) => p.simulated);
  const stage = current && current.stages.find((s) => s.key === selected);
  return (
    <Page title="CI/CD" stage="cicd" teach="cicd" steps={["ci_pipeline"]}
      sub="The pipeline is ordinary automation that enforces the quality gates. The same stages are defined for GitHub Actions in .github/workflows/ai-sdlc-ci.yml.">
      {!current ? <Card><NotRun what="The pipeline run" /></Card> : (
        <>
          <Card title={`Pipeline ${current.name} · ${current.ref}`} right={<Badge kind={current.status === "failed" ? "blocked" : "ok"}>{current.status}</Badge>}>
            <div className="pipeline">
              {current.stages.map((s) => (
                <button key={s.key} className={`pstage ${s.status} ${selected === s.key ? "sel" : ""}`} onClick={() => setSelected(s.key)}>
                  <b>{s.name}</b>
                  <span className="small">{s.status}{s.duration_s ? ` · ${s.duration_s}s` : ""}</span>
                </button>
              ))}
            </div>
            {stage && (
              <div className="grid g2" style={{ marginTop: 12 }}>
                <div>
                  <h3>{stage.name} · logs {stage.simulated && <Simulated />}</h3>
                  <div className="code" style={{ marginTop: 6 }}><pre>{stage.logs.join("\n")}</pre></div>
                </div>
                <dl className="kv" style={{ alignContent: "start" }}>
                  <dt>Status</dt><dd><Badge kind={stage.status === "passed" ? "ok" : stage.status === "failed" ? "blocked" : "outline"}>{stage.status}</Badge></dd>
                  <dt>Duration</dt><dd>{stage.duration_s ? `${stage.duration_s}s` : "-"}</dd>
                  <dt>AI involvement</dt><dd>{stage.ai ? <><Actor kind="ai" label="✦ AI" /> {stage.ai}</> : "None. Plain automation."}</dd>
                  <dt>Human involvement</dt><dd>{stage.human ? <><Actor kind="human" label="● Human" /> {stage.human}</> : "None at this stage."}</dd>
                </dl>
              </div>
            )}
          </Card>
          <Card title="Quality gates">
            <table><thead><tr><th>Gate</th><th>Measured</th><th>Result</th></tr></thead>
              <tbody>{current.gates.map((g) => <tr key={g.name}><td>{g.name}</td><td className="mono">{g.value}</td><td><Decision value={g.passed ? "PASS" : "FAIL"} /></td></tr>)}</tbody></table>
            <p className="small muted" style={{ marginTop: 8 }}>Lint, tests, coverage, evaluation and scans ran for real against the feature branch. Build and deployments are simulated: nothing is built or deployed outside this machine.</p>
          </Card>
        </>
      )}
      {history.length > 0 && (
        <Card title="Earlier pipelines" right={<Simulated label="SEEDED HISTORY" />}>
          <table><thead><tr><th>Ref</th><th>Status</th><th>Stages</th><th>When</th></tr></thead>
            <tbody>{history.map((p) => <tr key={p.id}><td className="mono">{p.ref}</td><td><Badge kind="ok">{p.status}</Badge></td><td className="small muted">{p.stages.map((s) => s.name).join(" → ")}</td><td className="small">{dateTime(p.created_at)}</td></tr>)}</tbody></table>
        </Card>
      )}
      <ToolCalls actors={["ci-pipeline"]} title="Pipeline identity: tool calls" />
    </Page>
  );
}

/* ------------------------------------------------------------------ Deployment */
export function Deployment() {
  const { run, artifacts, notify, refresh } = useLab();
  const { data, reload } = useFetch("/api/deployments", [run.step_index, run.status]);
  const [health, setHealth] = useState({});
  const d = artifacts.deployment;
  const check = (env) => api.post(`/api/deployments/${env}/health-check`).then((h) => setHealth((x) => ({ ...x, [env]: h })));
  const rollback = (env) => api.post(`/api/deployments/${env}/rollback`).then(() => { notify("ok", `${env} rolled back.`); reload(); refresh(); }).catch((e) => notify("error", e.message));
  return (
    <Page title="Deployment" stage="deployment" teach="deployment" steps={["staging_deploy", "production_approval", "production_deploy"]}
      sub="One build is promoted through DEV, TEST and STAGING. Production is a simulation and always needs a human." right={<Simulated label="SIMULATION ONLY" />}>
      <div className="grid g4">
        {data && data.environments.map((e) => (
          <Card key={e.env} kind={e.health === "degraded" ? "blocked" : e.env === "PRODUCTION" ? "human" : "system"} title={e.label}
            right={<Badge kind={e.health === "healthy" ? "ok" : "blocked"}>{e.health}</Badge>}>
            <div className="stat"><span className="value mono">{e.version}</span>
              <span className="hint">{e.last_kind} by {e.deployed_by} · {dateTime(e.deployed_at)}</span>
              {e.approved_by && <span className="hint">approved by <b>{e.approved_by}</b></span>}</div>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn sm" onClick={() => check(e.env)}>Health check</button>
              <button className="btn sm" disabled={!e.previous_version} onClick={() => rollback(e.env)} title={e.requires_approval ? "Needs SRE approval through the incident workflow" : `Back to ${e.previous_version}`}>Rollback</button>
            </div>
            {health[e.env] && <ul className="small" style={{ marginTop: 8 }}>{health[e.env].checks.map((c) => <li key={c.name}>{c.ok ? "✓" : "✗"} {c.name}</li>)}</ul>}
            {e.requires_approval && <p className="small muted" style={{ marginTop: 8 }}>Deploy and rollback require manual human approval.</p>}
          </Card>
        ))}
      </div>
      {d && (
        <div className="grid g2">
          <Card title={`Deployment Advisor recommends ${d.advice.recommendation}`} kind="ai" right={<Decision value={d.advice.recommendation === "GO" ? "PASS" : "FAIL"} />}>
            <List items={d.advice.rationale} />
            <h3 style={{ marginTop: 10 }}>Watch after release</h3><List items={d.advice.watch_after_release} />
            <p className="small muted" style={{ marginTop: 8 }}>{d.advice.note}</p>
            <Provenance meta={d.advice._meta} />
          </Card>
          <Card title="What happened when the AI asked to deploy" kind="human">
            <dl className="kv">
              <dt>Request</dt><dd className="mono">deployment-advisor → production.deploy</dd>
              <dt>Policy decision</dt><dd><Decision value={d.production_request.decision} /></dd>
              <dt>Rule</dt><dd className="mono">{d.production_request.rule}</dd>
              <dt>Executed by the AI</dt><dd><b>{d.production_request.executed ? "yes" : "No"}</b></dd>
              <dt>Reason</dt><dd>{d.production_request.reason}</dd>
              {d.production && <><dt>Outcome</dt><dd>Approved by <b>{d.production.approved_by}</b>, deployed by <b>{d.production.deployed_by}</b> to the production simulation.</dd></>}
            </dl>
          </Card>
        </div>
      )}
      {data && (
        <Card title="Deployment history">
          <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}><table>
            <thead><tr><th>When</th><th>Environment</th><th>Version</th><th>Kind</th><th>By</th><th>Approved by</th><th>Notes</th></tr></thead>
            <tbody>{data.history.map((h) => <tr key={h.id}><td className="small">{dateTime(h.ts)}</td><td>{h.env}</td><td className="mono">{h.version}</td>
              <td><Badge kind={h.kind === "rollback" ? "warn" : "outline"}>{h.kind}</Badge></td><td>{h.deployed_by}</td><td>{h.approved_by || "-"}</td><td className="small muted">{h.notes}</td></tr>)}</tbody>
          </table></div>
        </Card>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Observability */
function AppTab() {
  const { run } = useLab();
  const { data, reload } = useFetch("/api/observability/app", [run.step_index, run.status]);
  const { data: logs } = useFetch("/api/observability/logs", [run.step_index, run.status]);
  useEffect(() => { const timer = setInterval(reload, 20000); return () => clearInterval(timer); }, [reload]);
  if (!data) return null;
  const p = data.points, last = p[p.length - 1], m = data.deployments;
  const chart = (title, series, unit) => <Card title={title} right={<Simulated />}><LineChart points={p} series={series} unit={unit} markers={m} shade="incident" /></Card>;
  return (
    <div className="stack">
      <div className="grid g-auto">
        <Stat label="Requests / min" value={num(last.requests)} /><Stat label="Latency p95" value={`${last.latency_p95_ms} ms`} />
        <Stat label="Error rate" value={`${last.error_rate_pct}%`} kind={last.incident ? "blocked" : ""} /><Stat label="CPU" value={`${last.cpu_pct}%`} /><Stat label="Memory" value={`${last.memory_pct}%`} />
      </div>
      <div className="grid g2">
        {chart("Requests per second", [{ key: "rps", label: "requests/s", color: "var(--human)" }], "")}
        {chart("Latency", [{ key: "latency_p50_ms", label: "p50", color: "var(--system)" }, { key: "latency_p95_ms", label: "p95", color: "var(--ai)" }], "ms")}
        {chart("Error rate", [{ key: "error_rate_pct", label: "all routes", color: "var(--blocked)" }], "%")}
        {chart("HTTP status per minute", [{ key: "status_2xx", label: "2xx", color: "var(--ok)" }, { key: "status_4xx", label: "4xx", color: "var(--warn)" }, { key: "status_5xx", label: "5xx", color: "var(--blocked)" }], "")}
        {chart("CPU and memory", [{ key: "cpu_pct", label: "CPU %", color: "var(--human)" }, { key: "memory_pct", label: "memory %", color: "var(--ai)" }], "%")}
        <Card title="Application logs" right={<><Simulated /><Badge kind="ok">secrets redacted</Badge></>}>
          <div className="code" style={{ maxHeight: 230, overflowY: "auto" }}>
            {(logs || []).slice(0, 30).map((l, i) => <pre key={i} style={l.level === "ERROR" ? { color: "var(--blocked)" } : undefined}>{time(l.ts)} {l.level.padEnd(5)} {l.message.split("\n")[0]}</pre>)}
          </div>
        </Card>
      </div>
    </div>
  );
}

function AiTab() {
  const { run } = useLab();
  const { data } = useFetch("/api/observability/ai", [run.step_index, run.status]);
  if (!data) return null;
  const table = (title, rows, label) => (
    <Card title={title}>
      <table><thead><tr><th>{label}</th><th className="num">Runs</th><th className="num">Tokens</th><th className="num">Avg latency</th><th className="num">Cost</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key}><td className="mono">{r.key}</td><td className="num">{r.runs}</td><td className="num">{num(r.tokens)}</td><td className="num">{(r.avg_latency_ms / 1000).toFixed(1)}s</td><td className="num">{money(r.cost_usd)}</td></tr>)}</tbody></table>
    </Card>
  );
  return (
    <div className="stack">
      <div className="grid g-auto">
        <Stat label="Model calls" value={data.totals.runs} hint={`${data.totals.live_runs} live, rest seeded`} /><Stat label="Tokens" value={num(data.totals.tokens)} />
        <Stat label="Cost" value={money(data.totals.cost_usd)} hint="mock prices" /><Stat label="Failed tool calls" value={data.totals.failed_tool_calls} />
        <Stat label="Blocked actions" value={data.totals.blocked_actions} kind={data.totals.blocked_actions ? "blocked" : ""} />
      </div>
      <div className="grid g2">
        {table("By agent", data.by_agent, "Agent")}
        <div className="stack">{table("By model", data.by_model, "Provider / model")}{table("By prompt version", data.by_prompt_version, "Prompt")}</div>
      </div>
      <Card title="Evaluation scores over time">
        <table><thead><tr><th>When</th><th>Variant</th><th className="num">Score</th><th className="num">Security</th><th></th></tr></thead>
          <tbody>{data.evaluations.map((e) => <tr key={e.id}><td className="small">{dateTime(e.created_at)}</td><td>{e.variant}{e.simulated && <> <Simulated label="seeded" /></>}</td><td className="num">{e.score}%</td><td className="num">{e.security_score}%</td><td style={{ width: 140 }}><Bar value={e.score} kind={e.score > 80 ? "ok" : "blocked"} /></td></tr>)}</tbody></table>
      </Card>
      <Card title="Recent model calls">
        <div className="table-wrap" style={{ maxHeight: 320, overflowY: "auto" }}><table>
          <thead><tr><th>When</th><th>Agent</th><th>Task</th><th>Model</th><th>Prompt</th><th className="num">Tokens in / out</th><th className="num">Latency</th><th className="num">Cost</th></tr></thead>
          <tbody>{data.recent.map((r) => <tr key={r.id}><td className="small">{dateTime(r.created_at)}</td><td>{r.agent}</td><td className="mono small">{r.task}</td><td className="small">{r.provider}/{r.model}</td><td>{r.prompt_version}</td>
            <td className="num">{num(r.tokens_in)} / {num(r.tokens_out)}</td><td className="num">{(r.latency_ms / 1000).toFixed(1)}s</td><td className="num">{money(r.cost_usd)}</td></tr>)}</tbody>
        </table></div>
        <p className="small muted" style={{ marginTop: 8 }}>{data.pricing_note} Token counts are computed from the actual prompt and response text.</p>
      </Card>
    </div>
  );
}

function SecurityTab() {
  const { run } = useLab();
  const { data } = useFetch("/api/observability/security", [run.step_index, run.status]);
  if (!data) return null;
  return (
    <div className="stack">
      <div className="grid g-auto">
        <Stat label="Policy violations" value={data.policy_violations} hint="tool calls denied" kind={data.policy_violations ? "blocked" : ""} />
        <Stat label="Injection attempts" value={data.injection_attempts} /><Stat label="Secret access attempts" value={data.secret_access_attempts} />
        <Stat label="Secrets redacted" value={data.secrets_redacted} hint="from tool results" />
        <Stat label="Unexpected capability paths" value={data.unexpected_capability_paths} hint={`${data.critical_capability_paths} critical`} kind={data.critical_capability_paths ? "blocked" : ""} />
        <Stat label="Approval requests" value={data.approval_requests} /><Stat label="Kill-switch blocks" value={data.kill_switch_blocks} />
      </div>
      <div className="grid g2">
        <Card title="Denied tools">{data.denied_tools.length ? <table><tbody>{data.denied_tools.map((d) => <tr key={d.tool}><td className="mono">{d.tool}</td><td className="num">{d.count}</td><td style={{ width: 140 }}><Bar value={d.count} max={data.denied_tools[0].count} kind="blocked" /></td></tr>)}</tbody></table> : <p className="muted">No tool call has been denied yet. Run the red team.</p>}</Card>
        <Card title="Tool calls by policy decision"><table><tbody>{data.by_decision.map((d) => <tr key={d.decision}><td><Decision value={d.decision} /></td><td className="num">{d.count}</td></tr>)}</tbody></table></Card>
      </div>
      <Card title="Recent blocked actions">
        <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}><table>
          <thead><tr><th>When</th><th>Identity</th><th>Tool</th><th>Decision</th><th>Rule</th><th>Context</th></tr></thead>
          <tbody>{data.recent_blocked.map((c) => <tr key={c.id}><td className="small">{dateTime(c.created_at)}</td><td>{c.actor}</td><td className="mono">{c.tool}</td><td><Decision value={c.decision} /></td><td className="mono small">{c.rule}</td><td>{c.tag ? <Badge>{c.tag}</Badge> : "workflow"}</td></tr>)}</tbody>
        </table></div>
      </Card>
    </div>
  );
}

export function Observability() {
  const [tab, setTab] = useState("app");
  return (
    <Page title="Observability" stage="observability" teach="observability" steps={["monitoring"]}
      sub="Three views: the application, the AI, and the controls. Application telemetry is simulated; AI and security figures come from this lab's own records.">
      <Tabs value={tab} onChange={setTab} tabs={[["app", "Application"], ["ai", "AI"], ["security", "Security"]]} />
      {tab === "app" && <AppTab />}{tab === "ai" && <AiTab />}{tab === "security" && <SecurityTab />}
    </Page>
  );
}

/* ------------------------------------------------------------------ Incident / RCA */
const PHASES = ["DETECT", "TRIAGE", "COLLECT EVIDENCE", "IDENTIFY CHANGE", "FORM HYPOTHESIS", "RECOMMEND REMEDIATION", "HUMAN APPROVAL", "RESTORE SERVICE", "DOCUMENT RCA"];

export function Incident() {
  const { run, learn, learnMode } = useLab();
  const { data: incident } = useFetch(`/api/runs/${run.id}/incident`, [run.step_index, run.status]);
  const d = incident ? incident.data : {};
  const reached = new Set((d.timeline || []).map((t) => t.phase));
  if (d.restored) reached.add("HUMAN APPROVAL");
  const ev = d.evidence;
  return (
    <Page title="Incident / RCA" stage="incident" teach="incident"
      steps={["incident_simulation", "incident_triage", "rca_analysis", "rollback_approval", "restore_service", "rca_document"]}
      sub="Restore service first. Find root cause second. Automate prevention third." right={<Simulated label="SIMULATED INCIDENT" />}>
      {!incident ? (
        <Card><NotRun what="The incident drill (scenario: the password-reset API returns HTTP 500)" /></Card>
      ) : (
        <>
          <Card title={`${incident.key} · ${incident.title}`} right={<>{incident.severity && <Badge kind="blocked">{incident.severity}</Badge>}<Badge kind={incident.status === "open" ? "blocked" : "ok"}>{incident.status}</Badge>{incident.mttr_minutes != null && <Badge kind="ok">restored in {incident.mttr_minutes} min</Badge>}</>}>
            <div className="row" style={{ gap: 4 }}>
              {PHASES.map((p, i) => (
                <span key={p} className="row" style={{ gap: 4 }}>
                  {i > 0 && <span className="faint">→</span>}
                  <Badge kind={reached.has(p) ? (p === "HUMAN APPROVAL" ? "human" : "ok") : incident.phase === p ? "ai" : "outline"}>{reached.has(p) ? "✓ " : ""}{p}</Badge>
                </span>
              ))}
            </div>
          </Card>
          {d.triage && (
            <div className="grid g2">
              <Card title="Triage" kind="ai">
                <p>{d.triage.summary}</p>
                <dl className="kv"><dt>Customer impact</dt><dd>{d.triage.customer_impact}</dd><dt>Severity</dt><dd><b>{d.severity}</b>. {d.triage.severity_reasoning}</dd>
                  <dt>Detected</dt><dd>Error rate rose from {d.detection.baseline_error_rate_pct}% to {d.detection.peak_error_rate_pct}% (threshold {d.detection.threshold_pct}%) at {time(d.detection.onset)}</dd></dl>
                <Provenance meta={d.triage._meta} />
              </Card>
              {ev && <Card title="Error rate" right={<Simulated />}>
                <LineChart points={ev.metrics.points} markers={ev.metrics.deployments} shade="incident" unit="%"
                  series={[{ key: "error_rate_pct", label: "all routes", color: "var(--blocked)" }, { key: "reset_route_error_rate_pct", label: "POST /password-reset/request", color: "var(--warn)" }]} />
              </Card>}
            </div>
          )}
          {ev && (
            <div className="grid g2">
              <Card title="Evidence: logs" right={<>{ev.redactions_in_logs > 0 && <Badge kind="ok">{ev.redactions_in_logs} secret(s) redacted before the agent saw them</Badge>}<Badge>{ev.error_count} error lines</Badge></>}>
                {ev.signatures.map((s) => <div key={s.signature} className="row between small" style={{ marginBottom: 6 }}><code>{s.signature}</code><span><b>{s.count}×</b> in {s.files.join(", ")}</span></div>)}
                <div className="code" style={{ maxHeight: 200, overflowY: "auto" }}><pre>{ev.log_sample[0] ? ev.log_sample[0].message : ""}</pre></div>
              </Card>
              <Card title="Evidence: recent production changes">
                <table><thead><tr><th>Version</th><th>When</th><th>Approved by</th><th>Notes</th></tr></thead>
                  <tbody>{ev.deployments.map((x, i) => <tr key={i}><td className="mono">{x.version}</td><td className="small">{dateTime(x.ts)}</td><td className="small">{x.approved_by}</td><td className="small muted">{x.notes}</td></tr>)}</tbody></table>
                {ev.deployments[0] && ev.deployments[0].diff && <div style={{ marginTop: 8 }}><DiffViewer diff={ev.deployments[0].diff.replace(/^--- a\/(.+)$/gm, "diff --git a/$1 b/$1\n--- a/$1")} openFirst={1} /></div>}
              </Card>
            </div>
          )}
          {d.suspects && (
            <Card title="Identify change: which release correlates with the errors?">
              <table><thead><tr><th>Release</th><th className="num">Minutes before first error</th><th>Changed files</th><th className="num">Overlap with stack trace</th><th className="num">Score</th></tr></thead>
                <tbody>{d.suspects.map((s) => <tr key={s.version}><td className="mono"><b>{s.version}</b></td><td className="num">{s.minutes_before_onset}</td><td className="small mono">{s.changed_files.join(", ") || "-"}</td><td className="num">{Math.round(s.file_overlap * 100)}%</td><td className="num"><b>{s.score}</b></td></tr>)}</tbody></table>
              <p className="small muted" style={{ marginTop: 6 }}>Score = time proximity and overlap between the files a release changed and the files in the failing stack trace. Computed by code, not by the model.</p>
            </Card>
          )}
          {d.hypotheses && (
            <Card title="Hypotheses, ranked from evidence">
              <div className="stack">{d.hypotheses.map((h) => (
                <div key={h.id} className="card flat">
                  <div className="row between"><b>{h.id} · {h.title}</b><span className="row" style={{ minWidth: 190 }}><div style={{ flex: 1 }}><Bar value={h.confidence * 100} kind={h.confidence > 0.5 ? "ok" : ""} /></div><b>{Math.round(h.confidence * 100)}%</b></span></div>
                  <div className="grid g2 small" style={{ marginTop: 6 }}>
                    <div><b style={{ color: "var(--ok)", display: "block" }}>Evidence for</b><List items={h.evidence_for} empty="none" /></div>
                    <div><b style={{ color: "var(--blocked)", display: "block" }}>Evidence against</b><List items={h.evidence_against} empty="none" /></div>
                  </div>
                </div>
              ))}</div>
            </Card>
          )}
          {d.analysis && (
            <div className="grid g2">
              <Card title="Symptom vs root cause" kind="ai">
                <dl className="kv"><dt>Symptom</dt><dd>{d.analysis.symptom}</dd><dt>Root cause</dt><dd><b>{d.analysis.root_cause}</b></dd></dl>
                <p style={{ marginTop: 8 }}>{d.analysis.narrative}</p>
                <h3>Why it was not caught</h3><List items={d.analysis.why_it_was_not_caught} />
                <Provenance meta={d.analysis._meta} />
              </Card>
              {d.recommendation && <Card title="Recommended remediation" kind="human">
                <p><b>{d.recommendation.action}</b></p><p>{d.recommendation.why}</p>
                {d.recommendation.alternatives.map((a) => <p key={a.action} className="small muted">Alternative: {a.action}. {a.trade_off}</p>)}
                <dl className="kv"><dt>AI asked to roll back</dt><dd><Decision value={d.recommendation.agent_request.decision} /> executed by AI: <b>{d.recommendation.agent_request.executed ? "yes" : "no"}</b></dd>
                  <dt>Requires</dt><dd>{d.recommendation.requires}</dd>
                  {d.restored && <><dt>Outcome</dt><dd>Approved by <b>{d.restored.approved_by}</b>, executed by <b>{d.restored.executed_by}</b>. Production is on {d.restored.version} and {d.restored.health.status}.</dd></>}</dl>
              </Card>}
            </div>
          )}
          {d.rca_document && (
            <div className="grid g2">
              <Card title="RCA document" kind="ai"><Markdown text={d.rca_document} /></Card>
              <div className="stack" style={{ alignContent: "start" }}>
                <Card title="Continuous improvement: the loop closes" kind="ok">
                  <ul><li>The RCA was added to the context index as <code>{d.context_path}</code> ({d.indexed.documents} documents, {d.indexed.chunks} chunks). Future agents will retrieve it.</li>
                    <li>Proposed evaluation fixture <code>{d.proposed_fixture.id}</code>: {d.proposed_fixture.question}</li></ul>
                </Card>
                <Card title="Prevention"><List items={d.analysis.prevention} /></Card>
              </div>
            </div>
          )}
        </>
      )}
      {learnMode && learn && (
        <Card title="RCA concepts">
          <div className="row" style={{ marginBottom: 10 }}>{learn.rca_rule.map((r, i) => <Badge key={r} kind="ai">{i + 1}. {r}</Badge>)}</div>
          <div className="grid g3">{learn.rca_concepts.map(([name, text]) => <div key={name} className="card flat"><h3>{name}</h3><p className="small" style={{ margin: "4px 0 0" }}>{text}</p></div>)}</div>
        </Card>
      )}
      <ToolCalls actors={["incident-agent", "rca-agent", "ci-pipeline"]} title="Tool calls during the incident" />
    </Page>
  );
}
