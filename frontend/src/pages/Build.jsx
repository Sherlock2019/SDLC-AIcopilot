import { useState } from "react";
import { api } from "../api.js";
import { Actor, Badge, Bar, Card, DiffViewer, List, Mermaid, NotRun, Page, Provenance, Stat, Tabs, ToolCalls } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

/* ------------------------------------------------------------------ Requirements */
export function Requirements() {
  const { artifacts, run } = useLab();
  const data = artifacts.requirement_analysis;
  const a = data && data.analysis;
  const cite = (ids) => (ids || []).map((id) => <Badge key={id} kind="ai" title="Retrieved source">{id}</Badge>);
  return (
    <Page title="Requirements" stage="requirements" teach="requirements" steps={["requirement_analysis", "requirement_approval"]}
      sub="The Requirement Agent turns a one-line request into a reviewable, grounded analysis. A human approves it before any design starts.">
      <Card title="Business requirement" right={<Actor kind="human" label="● Entered by a human" />}>
        <p style={{ fontSize: 16 }}>“{run.requirement_text}”</p>
        {data && data.input_injection_flags.length > 0 && (
          <div className="card warn small"><b>Note:</b> the request text itself matches prompt-injection patterns ({data.input_injection_flags.map((f) => f.label).join("; ")}). It is treated as a request to analyse, never as an instruction that changes permissions.</div>
        )}
      </Card>
      {!a ? <Card><NotRun what="The requirement analysis" /></Card> : (
        <>
          {(data.feedback || []).length > 0 && <Card kind="human" title="Human feedback applied to this draft"><List items={data.feedback.map((f) => `${f.by}: ${f.comment}`)} /></Card>}
          <div className="grid g2">
            <Card title="Business objective" kind="ai"><p>{a.business_objective}</p></Card>
            <Card title="User story" kind="ai">
              <p>As a <b>{a.user_story.as_a}</b>,<br />I want <b>{a.user_story.i_want}</b><br />so that <b>{a.user_story.so_that}</b>.</p>
            </Card>
          </div>
          {(a.conflicts || []).map((c, i) => (
            <Card key={i} kind="warn" title="Conflict between the request and policy, surfaced for the human">
              <p>{c.text}</p><div className="row">{c.rules.map((r) => <Badge key={r}>{r}</Badge>)}{cite(c.citations)}</div>
            </Card>
          ))}
          <Card title="Acceptance criteria" right={<span className="small muted">{a.acceptance_criteria.filter((c) => c.citations.length).length} of {a.acceptance_criteria.length} grounded in a retrieved source</span>}>
            <div className="table-wrap"><table>
              <thead><tr><th>ID</th><th>Criterion</th><th>Rule</th><th>Source</th></tr></thead>
              <tbody>{a.acceptance_criteria.map((c) => (
                <tr key={c.id}><td className="mono">{c.id}</td><td>{c.text}</td>
                  <td><div className="chip-list">{c.rules.map((r) => <Badge key={r}>{r}</Badge>)}</div></td>
                  <td><div className="chip-list">{c.citations.length ? cite(c.citations) : <Badge kind="blocked">ungrounded</Badge>}</div></td></tr>
              ))}</tbody>
            </table></div>
          </Card>
          <div className="grid g2">
            <Card title="Security requirements">
              <ul>{a.security_requirements.map((s, i) => <li key={i}>{s.text} <span className="chip-list" style={{ display: "inline-flex" }}>{(s.rules || []).map((r) => <Badge key={r}>{r}</Badge>)}{cite(s.citations)}</span></li>)}</ul>
            </Card>
            <Card title="Questions for the human" kind="human"><List items={a.questions} empty="No open questions. Be suspicious of an analysis with none." /></Card>
            <Card title="Assumptions"><List items={a.assumptions} /></Card>
            <Card title="Dependencies"><List items={a.dependencies} /></Card>
            <Card title="Data requirements"><List items={a.data_requirements} /></Card>
            <Card title="Success metrics"><List items={a.success_metrics} /></Card>
          </div>
          <Card title="Potential edge cases"><div className="chip-list">{a.edge_cases.map((e) => <Badge key={e}>{e}</Badge>)}</div></Card>
          <Card title="Sources the agent was shown" right={<span className="small muted">{data.retrieval.used_tokens} of {data.retrieval.max_tokens} context tokens</span>}>
            <div className="chip-list">{data.citations.map((c) => <Badge key={c.id} kind="ai" title={c.heading}>{c.id} · {c.source}</Badge>)}</div>
            {a.notice && <p className="small" style={{ marginTop: 8, color: "var(--warn)" }}>{a.notice}</p>}
            <Provenance meta={a._meta} />
          </Card>
        </>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Context */
function RetrievalView({ r }) {
  const [open, setOpen] = useState(null);
  return (
    <div className="stack">
      <div className="grid g4">
        <Stat label="Context budget" value={`${r.used_tokens.toLocaleString()} / ${r.max_tokens.toLocaleString()}`} hint={`${r.budget_used_pct}% of the token budget used`} />
        <Stat label="Selected chunks" value={r.candidates.filter((c) => c.status === "selected").length} hint={`of ${r.candidates.length} candidates`} />
        <Stat label="Saved by compression" value={`${r.tokens_saved_by_compression} tokens`} hint="extractive, query-aware" />
        <Stat label="Quarantined" value={r.quarantined.length} hint="prompt-injection attempts" kind={r.quarantined.length ? "blocked" : ""} />
      </div>
      <Card title={`MAX CONTEXT: ${r.max_tokens.toLocaleString()} tokens`}>
        <Bar value={r.used_tokens} max={r.max_tokens} />
        <div className="grid g2" style={{ marginTop: 12 }}>
          <div><h3 style={{ color: "var(--ok)" }}>Selected</h3>
            {r.by_source.filter((s) => s.selected_chunks).map((s) => <div key={s.source} className="row between small"><span className="mono">{s.source}</span><b>{s.selected_tokens}</b></div>)}
          </div>
          <div><h3 style={{ color: "var(--blocked)" }}>Rejected</h3>
            {r.by_source.filter((s) => !s.selected_chunks).map((s) => <div key={s.source} className="row between small"><span className="mono">{s.source}</span><span className="muted">{s.reasons[0]}</span></div>)}
            {!r.by_source.some((s) => !s.selected_chunks) && <span className="muted small">No source was rejected entirely.</span>}
          </div>
        </div>
        <div className="row small muted" style={{ marginTop: 12 }}>
          {r.pipeline.map((p, i) => <span key={p.stage}>{i ? "→ " : ""}<b>{p.count}</b> {p.stage.toLowerCase()}</span>)}
        </div>
      </Card>
      {r.quarantined.map((q, i) => (
        <Card key={i} kind="blocked" title="Prompt injection detected" right={<Actor kind="blocked" />}>
          <dl className="kv"><dt>Source</dt><dd className="mono">{q.source}</dd><dt>Action</dt><dd>Instruction ignored. Chunk quarantined before it could reach a prompt.</dd><dt>Reason</dt><dd>{q.reason}</dd>
            <dt>Signals</dt><dd><div className="chip-list">{q.findings.map((f, j) => <Badge key={j} kind="blocked" title={f.excerpt}>{f.label}</Badge>)}</div></dd></dl>
        </Card>
      ))}
      <Card title="Retrieved chunks" right={<span className="small muted">score = 0.78 × cosine + 0.16 × keyword overlap + document-type prior</span>}>
        <div className="table-wrap"><table>
          <thead><tr><th>#</th><th>Source</th><th>Type</th><th className="num">Relevance</th><th className="num">Tokens</th><th>Status</th><th>Reason</th></tr></thead>
          <tbody>{r.candidates.map((c) => (
            <tr key={c.id} className={c.status === "rejected" ? "rejected" : ""} onClick={() => setOpen(open === c.id ? null : c.id)} style={{ cursor: "pointer" }}>
              <td>{c.citation || c.rank}</td>
              <td><span className="mono">{c.source}</span><div className="small muted">{c.heading}</div>
                {open === c.id && <div className="code" style={{ marginTop: 6 }}><pre>{c.status === "selected" ? c.compressed_text : c.text}</pre></div>}</td>
              <td><Badge>{c.doc_type}</Badge>{c.trust === "untrusted" && <Badge kind="warn">untrusted</Badge>}{c.doc_status === "deprecated" && <Badge kind="warn">deprecated</Badge>}</td>
              <td className="num">{c.score.toFixed(3)}<div style={{ width: 70, marginLeft: "auto" }}><Bar value={c.score} max={0.8} kind={c.status === "selected" ? "ok" : ""} /></div></td>
              <td className="num">{c.status === "selected" && c.compressed_tokens < c.tokens ? <>{c.tokens} → <b>{c.compressed_tokens}</b></> : c.tokens}</td>
              <td><Badge kind={c.status === "selected" ? "ok" : /injection/.test(c.reason) ? "blocked" : "outline"}>{c.status}</Badge></td>
              <td className="small">{c.reason}</td>
            </tr>
          ))}</tbody>
        </table></div>
        <p className="small muted" style={{ marginTop: 8 }}>Click a row to read the chunk. Selected chunks show the compressed text the model receives.</p>
      </Card>
    </div>
  );
}

export function ContextEngine() {
  const { artifacts, learn, learnMode, notify } = useLab();
  const { data: stats } = useFetch("/api/context/stats", [artifacts.incident && artifacts.improvement]);
  const [tab, setTab] = useState("run");
  const [query, setQuery] = useState("How long is a password reset token valid, and what must never be logged?");
  const [budget, setBudget] = useState(8000);
  const [types, setTypes] = useState([]);
  const [deprecated, setDeprecated] = useState(false);
  const [result, setResult] = useState(null);
  const search = () => api.post("/api/context/search", { query, max_tokens: Number(budget), doc_types: types, include_deprecated: deprecated }).then(setResult).catch((e) => notify("error", e.message));
  const allTypes = stats ? [...new Set(stats.sources.map((s) => s.type))] : [];
  return (
    <Page title="Context Engine" stage="context" teach="context" steps={["context_retrieval"]}
      sub="Ingestion, chunking, embeddings, vector search, metadata filters, ranking, compression and token budgeting. Every decision is visible.">
      <Tabs tabs={[["run", "This run's retrieval"], ["explore", "Explore retrieval"], ["index", "Index"]]} value={tab} onChange={setTab} />
      {tab === "run" && (artifacts.context ? (
        <>
          <Card title="User question (built from the approved requirement)"><p className="mono small">{artifacts.context.query}</p></Card>
          <RetrievalView r={artifacts.context} />
        </>
      ) : <Card><NotRun what="The retrieval trace for this run" /></Card>)}
      {tab === "explore" && (
        <>
          <Card title="Ask the context repository">
            <label className="field">Question<input className="input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} /></label>
            <div className="row" style={{ marginTop: 10, gap: 18 }}>
              <label className="field" style={{ minWidth: 260 }}>Context budget: {Number(budget).toLocaleString()} tokens
                <input type="range" min="200" max="8000" step="100" value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
              <div className="field">Document types
                <div className="row">{allTypes.map((t) => (
                  <label key={t} className="row small" style={{ gap: 4 }}><input type="checkbox" checked={types.includes(t)} onChange={(e) => setTypes(e.target.checked ? [...types, t] : types.filter((x) => x !== t))} />{t}</label>
                ))}</div></div>
              <label className="row small"><input type="checkbox" checked={deprecated} onChange={(e) => setDeprecated(e.target.checked)} />Include deprecated documents</label>
              <button className="btn primary" onClick={search}>Retrieve</button>
            </div>
            <p className="small muted" style={{ marginTop: 8 }}>Try a small budget to see chunks rejected for budget, or search “support ticket email never arrives” to see the hostile document quarantined.</p>
          </Card>
          {result && <RetrievalView r={result} />}
        </>
      )}
      {tab === "index" && stats && (
        <>
          <div className="grid g4">
            <Stat label="Documents" value={stats.documents} /><Stat label="Chunks" value={stats.chunks} hint={`about ${stats.chunk_tokens} tokens, ${stats.overlap_tokens} overlap`} />
            <Stat label="Indexed tokens" value={stats.tokens.toLocaleString()} /><Stat label="Embedder" value={<span style={{ fontSize: 15 }}>{stats.embedder}</span>} hint={`${stats.dimensions} dimensions, local, no API key`} />
          </div>
          <Card title="Context repository">
            <div className="table-wrap"><table>
              <thead><tr><th>Source</th><th>Type</th><th>Status</th><th>Trust</th><th>Owner</th><th className="num">Chunks</th><th className="num">Tokens</th></tr></thead>
              <tbody>{stats.sources.map((s) => (
                <tr key={s.path}><td className="mono">{s.path}</td><td><Badge>{s.type}</Badge></td>
                  <td><Badge kind={s.status === "deprecated" ? "warn" : "ok"}>{s.status}</Badge></td>
                  <td><Badge kind={s.trust === "untrusted" ? "blocked" : "outline"}>{s.trust}</Badge></td><td>{s.owner}</td>
                  <td className="num">{s.chunks}</td><td className="num">{s.tokens}</td></tr>
              ))}</tbody>
            </table></div>
          </Card>
        </>
      )}
      {learnMode && learn && (
        <Card title="Concepts">
          <div className="grid g3">{learn.context_concepts.map(([name, text]) => <div key={name} className="card flat"><h3>{name}</h3><p className="small" style={{ margin: "4px 0 0" }}>{text}</p></div>)}</div>
        </Card>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Architecture */
export function Architecture() {
  const { artifacts } = useLab();
  const p = artifacts.architecture;
  const scoreRow = (label, value, text) => (
    <div><div className="row between small"><span className="muted">{label}</span><b>{text}</b></div><Bar value={value} max={5} kind={value >= 4 ? "blocked" : value <= 2 ? "ok" : ""} /></div>
  );
  return (
    <Page title="Architecture" stage="architecture" teach="architecture" steps={["architecture_design", "architecture_approval"]} options={p && p.options}
      sub="The Architecture Agent proposes three options with trade-offs. A human architect chooses.">
      {!p ? <Card><NotRun what="The architecture proposal" /></Card> : (
        <>
          <Card title="Solution proposal" kind="ai"><p>{p.solution_proposal}</p>{p.notice && <p className="small" style={{ color: "var(--warn)" }}>{p.notice}</p>}<Provenance meta={p._meta} /></Card>
          <div className="grid g3">
            {p.options.map((o) => (
              <Card key={o.key} kind={p.selected === o.key ? "human" : ""} title={`OPTION ${o.key} · ${o.name}`}
                right={<>{p.recommended === o.key && <Badge kind="ai">AI recommends</Badge>}{p.selected === o.key && <Badge kind="human">Chosen by {p.approved_by}</Badge>}</>}>
                <p>{o.summary}</p>
                <div className="stack" style={{ margin: "10px 0" }}>
                  {scoreRow("Complexity", o.scores.complexity, o.complexity)}{scoreRow("Risk", o.scores.risk, o.risk)}
                  {scoreRow("Cost", o.scores.cost, o.cost)}{scoreRow("Delivery effort", o.scores.effort, o.effort)}
                </div>
                <h3>Benefits</h3><List items={o.benefits} />
                <h3 style={{ marginTop: 8 }}>Drawbacks</h3><List items={o.drawbacks} />
                <div className="chip-list" style={{ marginTop: 8 }}>
                  {o.policy_gaps.length ? o.policy_gaps.map((g) => <Badge key={g} kind="blocked">violates {g}</Badge>) : <Badge kind="ok">no policy gap</Badge>}
                </div>
              </Card>
            ))}
          </div>
          <Card title="Architecture diagram (Mermaid, generated by the agent)"><Mermaid chart={p.mermaid} /></Card>
          <div className="grid g2">
            {[["Components affected", "components_affected"], ["API changes", "api_changes"], ["Database changes", "database_changes"], ["Security model", "security_model"],
              ["Logging", "logging"], ["Monitoring", "monitoring"], ["Deployment changes", "deployment_changes"], ["Dependencies", "dependencies"]].map(([label, key]) => (
              <Card key={key} title={label}><List items={p.details[key]} /></Card>
            ))}
          </div>
        </>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Code */
export function Code() {
  const { artifacts, run } = useLab();
  const c = artifacts.code;
  const { data: git } = useFetch(c ? `/api/runs/${run.id}/git` : null, [run.step_index]);
  return (
    <Page title="Code" stage="code" teach="code" steps={["code_generation"]}
      sub="The Coding Agent implements the approved option on a feature branch. Its output is validated before it is written, and it cannot touch main.">
      {!c ? <Card><NotRun what="The proposed code change" /></Card> : c.rejected ? (
        <Card kind="blocked" title="Generated code was rejected by output validation"><ul>{c.validation.map((v) => <li key={v.check}>{v.ok ? "✓" : "✗"} {v.check} {v.detail}</li>)}</ul></Card>
      ) : (
        <>
          <div className="grid g4">
            <Stat label="Branch" value={<span className="mono" style={{ fontSize: 13 }}>{c.branch}</span>} hint={`from ${c.base} · commit ${c.commit}`} />
            <Stat label="Files changed" value={c.files.length} hint={`${c.files.filter((f) => f.status === "added").length} new, ${c.files.filter((f) => f.status === "modified").length} modified`} />
            <Stat label="Lines" value={<><span className="add-n">+{c.files.reduce((s, f) => s + f.additions, 0)}</span> <span className="del-n">-{c.files.reduce((s, f) => s + f.deletions, 0)}</span></>} />
            <Stat label="Commits on main by AI" value="0" hint="main is write-protected for every agent" kind="ok" />
          </div>
          {(c.notes || []).map((n) => <Card key={n} kind="warn"><span className="small">{n}</span></Card>)}
          <div className="grid g2">
            <Card title="Reasoning summary" kind="ai"><List items={c.reasoning_summary} /><Provenance meta={c._meta} /></Card>
            <div className="stack">
              <Card title="Potential risks, stated by the agent"><List items={c.risks} /></Card>
              <Card title="Dependencies"><List items={c.dependencies} empty="No new dependency (ARCH-1)." /></Card>
            </div>
          </div>
          <Card title="Model output validation" right={<Badge kind="system">LLM output is untrusted input</Badge>}>
            <div className="grid g2">{c.validation.map((v) => <div key={v.check} className="row small"><Badge kind={v.ok ? "ok" : "blocked"}>{v.ok ? "pass" : "fail"}</Badge>{v.check}</div>)}</div>
          </Card>
          <Card title="Git-style diff" right={<span className="small muted">{c.base}...{c.branch}</span>}>
            <div className="chip-list" style={{ marginBottom: 10 }}>{c.files.map((f) => <Badge key={f.path} kind={f.status === "added" ? "ok" : "system"}>{f.path} +{f.additions}</Badge>)}</div>
            <DiffViewer diff={c.diff} openFirst={2} />
          </Card>
          {git && <Card title="History of main (local mock git)" right={<Badge kind="ok">protected branch</Badge>}>
            <table><tbody>{git.log.map((l) => <tr key={l.sha}><td className="mono">{l.sha}</td><td>{l.subject}</td><td className="muted">{l.author}</td></tr>)}</tbody></table>
          </Card>}
          <ToolCalls actors={["coding-agent"]} />
        </>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------------ Tests */
export function Tests() {
  const { artifacts } = useLab();
  const t = artifacts.tests;
  const [filter, setFilter] = useState("all");
  if (!t || t.rejected) {
    return <Page title="Tests" stage="tests" teach="tests" steps={["test_generation"]} sub="Unit, API, integration, negative and security tests, generated and then executed in a sandbox.">
      <Card><NotRun what="Test results" /></Card></Page>;
  }
  const { before, after } = t;
  const categories = ["unit", "api", "integration", "negative", "security"];
  const shown = after.tests.filter((x) => filter === "all" || x.category === filter);
  return (
    <Page title="Tests" stage="tests" teach="tests" steps={["test_generation"]}
      sub="Unit, API, integration, negative and security tests, generated and then executed in a sandbox. These numbers are measured, not reported by a model.">
      <div className="grid g4">
        <div className="card stat"><span className="label">Tests before → after</span><div className="delta"><span className="from">{before.total}</span><span className="to">{after.total}</span></div><span className="hint">{after.total - before.total} generated by the Test Agent</span></div>
        <div className="card stat"><span className="label">Coverage before → after</span><div className="delta"><span className="from">{before.coverage}%</span><span className="to">{after.coverage}%</span></div><Bar value={after.coverage} kind="ok" /></div>
        <Stat label="Passed" value={`${after.passed} / ${after.total}`} hint={`${after.duration_s}s in the sandbox`} kind={after.failed ? "blocked" : "ok"} />
        <Stat label="Failures" value={after.failed} hint={after.failed ? "see below" : "none"} kind={after.failed ? "blocked" : ""} />
      </div>
      <div className="grid g2">
        <Card title="Tests by category">
          <table><thead><tr><th>Category</th><th className="num">Passed</th><th className="num">Total</th><th></th></tr></thead>
            <tbody>{categories.map((cat) => { const b = after.by_category[cat] || { passed: 0, total: 0 }; return (
              <tr key={cat}><td><Badge kind={cat === "security" ? "blocked" : "outline"}>{cat}</Badge></td><td className="num">{b.passed}</td><td className="num">{b.total}</td><td style={{ width: 120 }}><Bar value={b.passed} max={b.total || 1} kind="ok" /></td></tr>); })}</tbody></table>
        </Card>
        <Card title="Test strategy" kind="ai"><List items={t.strategy} /><Provenance meta={t._meta} /></Card>
      </div>
      {after.failures.length > 0 && <Card kind="blocked" title="Failures"><ul>{after.failures.map((f) => <li key={f.name}><b>{f.name}</b> <span className="small">{f.message}</span></li>)}</ul></Card>}
      <Card title="Executed tests" right={<Tabs tabs={[["all", "All"], ...categories.map((c) => [c, c])]} value={filter} onChange={setFilter} />}>
        <div className="table-wrap" style={{ maxHeight: 380, overflowY: "auto" }}><table>
          <thead><tr><th>Test</th><th>File</th><th>Category</th><th>Result</th><th className="num">Time</th></tr></thead>
          <tbody>{shown.map((x) => (
            <tr key={x.classname + x.name}><td className="mono">{x.name}</td><td className="small muted">{x.file}</td><td><Badge>{x.category}</Badge></td>
              <td><Badge kind={x.status === "passed" ? "ok" : "blocked"}>{x.status}</Badge></td><td className="num">{(x.time * 1000).toFixed(0)} ms</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
      <div className="grid g2">
        <Card title="Coverage by file">
          <table><tbody>{after.coverage_files.map((f) => <tr key={f.path}><td className="mono">{f.path}</td><td className="num">{f.coverage}%</td><td style={{ width: 110 }}><Bar value={f.coverage} kind="ok" /></td></tr>)}</tbody></table>
        </Card>
        <Card title="Sandbox" right={<Badge kind="system">isolation: {after.sandbox.isolation}</Badge>}>
          <p className="small">Generated code never runs inside the lab's own process. It runs in a subprocess on a clean export of the branch, with a timeout of {after.sandbox.timeout_s}s and this complete environment:</p>
          <div className="chip-list">{after.sandbox.env_keys.map((k) => <Badge key={k}>{k}</Badge>)}</div>
          <p className="small muted" style={{ marginTop: 8 }}>No API keys, no database URL, no tokens. Known limit: network egress is not blocked by a subprocess; the capability auditor reports that as an accepted risk.</p>
        </Card>
      </div>
      <ToolCalls actors={["test-agent"]} />
    </Page>
  );
}
