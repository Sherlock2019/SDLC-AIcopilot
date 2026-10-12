import { useState } from "react";
import { api } from "../api.js";
import { Actor, Badge, Bar, Card, Decision, Markdown, NotRun, Page, Provenance, Sev, Spinner, Stat, ToolCalls, money, num } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

/* ------------------------------------------------------------------ Pull requests */
export function PullRequests() {
  const { run, act, notify } = useLab();
  const { data: pr } = useFetch(`/api/runs/${run.id}/pull-request`, [run.step_index, run.status]);
  const { data: github } = useFetch("/api/github", [run.step_index]);
  const stats = pr && pr.data && pr.data.stats;
  const publish = () => act(() => api.post(`/api/runs/${run.id}/publish`).then((r) => { notify("ok", `Pull request opened: ${r.url}`); return r; }));
  return (
    <Page title="Pull Requests" stage="pull_request" teach="pull_request" steps={["pr_creation", "ci_pipeline", "pr_approval", "merge"]}
      sub="The AI packages the change with its evidence. A human approves, requests changes or rejects, and a human clicks MERGE.">
      {!pr ? <Card><NotRun what="The pull request" /></Card> : (
        <>
          <Card title={`#${pr.number} ${pr.title}`} right={<><Badge kind={pr.status === "merged" ? "ok" : pr.status === "approved" ? "human" : pr.status === "open" ? "ai" : "blocked"}>{pr.status}</Badge>{pr.data.ci && <Badge kind={pr.data.ci === "passed" ? "ok" : "blocked"}>CI {pr.data.ci}</Badge>}</>}>
            <div className="row small muted"><span className="mono">{pr.branch} → {pr.base}</span><span>opened by <b>{pr.author}</b></span>{pr.merged_by && <span>merged by <b>{pr.merged_by}</b> (human)</span>}
              {pr.external_url && <a href={pr.external_url} target="_blank" rel="noreferrer">View on GitHub</a>}</div>
          </Card>
          {stats && (
            <div className="grid g4">
              <Stat label="AI confidence" value={`${stats.confidence.value}%`} hint="computed from evidence, see formula" />
              <Stat label="Tests" value={`${stats.tests.passed} / ${stats.tests.total} passed`} hint={`coverage ${stats.coverage}%`} kind="ok" />
              <Stat label="Security" value={`${stats.security.CRITICAL || 0} critical · ${stats.security.MEDIUM || 0} medium`} hint={`${stats.security.HIGH || 0} high · ${stats.security.LOW || 0} low`} />
              <Stat label="Evaluation" value={`${stats.evaluation}%`} hint={`security score ${stats.security_score}%`} />
            </div>
          )}
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)" }}>
            <Card title="Description (drafted by the Coding Agent)" kind="ai"><Markdown text={pr.description} /></Card>
            <div className="stack" style={{ alignContent: "start" }}>
              {stats && <Card title="How AI confidence is calculated">
                <p className="small">{stats.confidence.formula}.</p>
                <dl className="kv">{Object.entries(stats.confidence.parts).flatMap(([k, v]) => [<dt key={k}>{k.replaceAll("_", " ")}</dt>, <dd key={k + "v"}>{v}</dd>])}</dl>
                <p className="small muted" style={{ marginTop: 6 }}>It is a summary of measurements, not the model's opinion of itself.</p>
              </Card>}
              <Card title="AI review comment" right={<Actor kind="ai" label="✦ comments only" />}>
                {(pr.data.comments || []).map((c, i) => <div key={i}><b className="small">{c.author}</b><pre className="small" style={{ marginTop: 4 }}>{c.body}</pre></div>)}
              </Card>
              {github && <Card title="Git integration" right={<Badge>{github.mode === "github-sandbox" ? "MODE B · GitHub sandbox" : "MODE A · local mock git"}</Badge>}>
                <p className="small">AI can: {github.allowed.join(", ").toLowerCase()}.</p>
                <p className="small"><b style={{ color: "var(--blocked)" }}>AI can never:</b> {github.never.join(", ").toLowerCase()}.</p>
                {github.mode === "github-sandbox"
                  ? <button className="btn" onClick={publish}>Open this PR in {github.repo}</button>
                  : <p className="small muted">Set GITHUB_ENABLED=true with a fine-grained token (Contents RW, Pull requests RW, Actions R) to mirror this PR into a sandbox repository. See docs/github-sandbox-setup.md.</p>}
                {github.last_error && <p className="small" style={{ color: "var(--blocked)" }}>{github.last_error}</p>}
              </Card>}
            </div>
          </div>
          <ToolCalls actors={["coding-agent", "review-agent", pr.merged_by].filter(Boolean)} title="Who touched this pull request" />
        </>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ AI review */
export function Review() {
  const { artifacts } = useLab();
  const r = artifacts.review;
  const [open, setOpen] = useState(null);
  return (
    <Page title="AI Review" stage="review" teach="review" steps={["ai_review"]}
      sub="Deterministic static rules first, model judgement second. Every finding has a severity, a location, a reason, a fix and a confidence.">
      {!r ? <Card><NotRun what="Review findings" /></Card> : (
        <>
          <div className="grid g-auto">
            {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((s) => <Stat key={s} label={s} value={r.counts[s] || 0} kind={(r.counts[s] && (s === "CRITICAL" || s === "HIGH")) ? "blocked" : ""} />)}
            <Stat label="Files reviewed" value={r.files_reviewed.length} hint={`${r.static_rule_findings} rule hits · ${r.llm_findings} model findings`} />
          </div>
          <Card title="Summary" kind="ai"><p>{r.summary}</p><Provenance meta={r._meta} /></Card>
          <Card title="Findings" right={<span className="small muted">click a finding for details</span>}>
            <div className="table-wrap"><table>
              <thead><tr><th>ID</th><th>Severity</th><th>File : line</th><th>Finding</th><th>Source</th><th>Confidence</th></tr></thead>
              <tbody>{r.findings.map((f) => (
                <tr key={f.id} onClick={() => setOpen(open === f.id ? null : f.id)} style={{ cursor: "pointer" }}>
                  <td className="mono">{f.id}</td><td><Sev level={f.severity} /></td><td className="mono small">{f.file}:{f.line}</td>
                  <td><b>{f.title}</b>
                    {open === f.id && <dl className="kv" style={{ marginTop: 8 }}>
                      <dt>Why it matters</dt><dd>{f.why}</dd><dt>Suggested fix</dt><dd>{f.fix}</dd><dt>Category</dt><dd>{f.category}</dd>
                      {f.reviewer_note && <><dt>Note</dt><dd style={{ color: "var(--warn)" }}>{f.reviewer_note}</dd></>}
                    </dl>}</td>
                  <td><Badge kind={f.source === "llm" ? "ai" : "system"}>{f.source === "llm" ? "model" : `rule ${f.rule}`}</Badge></td>
                  <td style={{ width: 120 }}><div className="row small" style={{ gap: 6 }}><div style={{ flex: 1 }}><Bar value={f.confidence * 100} kind={f.confidence < 0.5 ? "blocked" : ""} /></div>{Math.round(f.confidence * 100)}%</div></td>
                </tr>
              ))}</tbody>
            </table></div>
            <p className="small muted" style={{ marginTop: 8 }}>Low-confidence findings stay visible on purpose. One of them is a false positive: a reviewer who trusts every AI finding is as much at risk as one who reads none.</p>
          </Card>
          <ToolCalls actors={["review-agent"]} />
        </>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Evaluation */
function ResultsTable({ results }) {
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Fixture</th><th>Category</th><th>Requirement and question</th><th>Expected</th><th>Actual</th><th>Evidence</th></tr></thead>
      <tbody>{results.map((r) => (
        <tr key={r.id}><td className="mono small">{r.id}</td><td><Badge>{r.category_label}</Badge></td>
          <td>{r.requirement}<div className="small muted">{r.question}</div></td>
          <td><Decision value={r.expected} /></td><td><Decision value={r.actual} /></td><td className="small muted" style={{ maxWidth: 330 }}>{r.detail}</td></tr>
      ))}</tbody>
    </table></div>
  );
}

export function Evaluation() {
  const { artifacts, notify } = useLab();
  const e = artifacts.evaluation;
  const [compare, setCompare] = useState(null);
  const [loading, setLoading] = useState(false);
  const [promptfoo, setPromptfoo] = useState(null);
  const [detail, setDetail] = useState(null);
  const runCompare = () => { setLoading(true); api.get("/api/evals/compare").then(setCompare).catch((x) => notify("error", x.message)).finally(() => setLoading(false)); };
  return (
    <Page title="Evaluation" stage="evaluation" teach="evaluation" steps={["evaluation"]}
      sub="Reusable fixtures turn AI quality into a number. Behaviour checks run an independent reference test-suite against the generated code.">
      {e ? (
        <>
          <div className="grid g4">
            <Stat label="Overall score" value={`${e.score}%`} hint={`gate: above ${e.threshold}% · ${e.gate_passed ? "passed" : "FAILED"}`} kind={e.gate_passed ? "ok" : "blocked"} />
            <Stat label="Security score" value={`${e.security_score}%`} /><Stat label="Accuracy" value={`${e.accuracy}%`} hint="all non-security categories" />
            <Stat label="Fixtures" value={`${e.passed} / ${e.total}`} hint={`${num(e.tokens)} tokens · ${money(e.cost_usd)}`} />
          </div>
          <Card title="Score by category">
            <div className="grid g3">{e.by_category.map((c) => (
              <div key={c.category}><div className="row between small"><span>{c.label}</span><b>{c.passed}/{c.total}</b></div><Bar value={c.score} kind={c.score < 80 ? "blocked" : "ok"} /></div>
            ))}</div>
          </Card>
          <Card title={`Fixtures · ${e.variant}`}><ResultsTable results={e.results} /></Card>
        </>
      ) : <Card><NotRun what="This run's evaluation" /></Card>}

      <Card title="Compare prompts and models" right={<button className="btn primary" disabled={loading} onClick={runCompare}>{loading ? <><Spinner /> Running 4 variants…</> : "Run comparison"}</button>}>
        <p className="muted small">Prompt v1 is a naive prompt with no retrieved context. Prompt v2 is grounded in policy. Model A is larger, Model B smaller and cheaper. The harness generates output for each combination, runs the evaluators and the reference tests, and reports what it measured.</p>
        {compare && (
          <>
            <div className="table-wrap"><table>
              <thead><tr><th>Variant</th><th className="num">Overall</th><th className="num">Security</th><th className="num">Accuracy</th><th className="num">Latency</th><th className="num">Tokens</th><th className="num">Cost</th><th>Gate &gt; {compare.threshold}%</th><th></th></tr></thead>
              <tbody>{compare.variants.map((v) => (
                <tr key={v.id}><td><b>{v.label}</b></td>
                  <td className="num"><b>{v.score}%</b><div style={{ width: 90, marginLeft: "auto" }}><Bar value={v.score} kind={v.gate_passed ? "ok" : "blocked"} /></div></td>
                  <td className="num">{v.security_score}%</td><td className="num">{v.accuracy}%</td><td className="num">{(v.latency_ms / 1000).toFixed(1)}s</td>
                  <td className="num">{num(v.tokens)}</td><td className="num">{money(v.cost_usd)}</td>
                  <td><Decision value={v.gate_passed ? "PASS" : "FAIL"} /></td>
                  <td><button className="btn sm" onClick={() => setDetail(detail === v.id ? null : v.id)}>{v.failed_cases.length} failed</button></td></tr>
              ))}</tbody>
            </table></div>
            <p className="small muted" style={{ marginTop: 8 }}>{compare.note} Latency is modelled for the mock models.</p>
            {detail && <div style={{ marginTop: 10 }}><h3 style={{ marginBottom: 6 }}>Failed fixtures · {compare.variants.find((v) => v.id === detail).label}</h3>
              <ResultsTable results={compare.variants.find((v) => v.id === detail).failed_cases} /></div>}
          </>
        )}
      </Card>
      <Card title="Framework compatibility" right={<button className="btn sm" onClick={() => api.get("/api/evals/promptfoo").then((d) => setPromptfoo(d.yaml))}>Export as Promptfoo config</button>}>
        <p className="small muted">Fixtures live in one YAML file and evaluators are plain Python functions. Adapters export the suite to Promptfoo and build DeepEval test cases. Neither framework is required to run the lab, and neither adapter is exercised by CI.</p>
        {promptfoo && <div className="code" style={{ maxHeight: 300, overflowY: "auto" }}><pre>{promptfoo}</pre></div>}
      </Card>
      <ToolCalls actors={["evaluation-agent"]} />
    </Page>
  );
}
