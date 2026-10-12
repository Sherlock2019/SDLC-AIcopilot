import { useMemo, useState } from "react";
import { api } from "../api.js";
import { Actor, Badge, Card, Decision, Page, Sev, Spinner, Stat, Tabs } from "../components.jsx";
import { useFetch, useLab } from "../store.jsx";

const COLUMNS = ["AGENT", "MCP SERVER", "TOOL", "API", "RESOURCE", "ACTION", "CONNECTED SYSTEM", "REACHED ACTION", "REACHED ACTION"];
const NODE_COLOR = { agent: "var(--ai)", server: "var(--system)", tool: "var(--human)", api: "var(--system)", resource: "var(--system)", action: "var(--text)", system: "var(--warn)" };
const STATUS = { declared: ["ok", "declared"], gated: ["human", "needs human approval"], contained: ["ok", "contained by a control"], unexpected: ["blocked", "UNEXPECTED"], not_reachable: ["ok", "not reachable"] };

function CapabilityGraph({ graph }) {
  const layout = useMemo(() => {
    const out = {};
    graph.edges.forEach((e) => { (out[e.from] = out[e.from] || []).push(e.to); });
    const depth = {};
    const start = graph.nodes.find((n) => n.type === "agent").id;
    const queue = [start];
    depth[start] = 0;
    while (queue.length) {
      const id = queue.shift();
      (out[id] || []).forEach((to) => { if (depth[to] === undefined) { depth[to] = depth[id] + 1; queue.push(to); } });
    }
    const columns = {};
    graph.nodes.forEach((n) => { const d = depth[n.id] ?? 0; (columns[d] = columns[d] || []).push(n); });
    const W = 136, H = 30, GX = 157, GY = 40, TOP = 26;
    const rows = Math.max(...Object.values(columns).map((c) => c.length));
    const pos = {};
    Object.entries(columns).forEach(([d, nodes]) => {
      nodes.sort((a, b) => (b.flagged ? 1 : 0) - (a.flagged ? 1 : 0) || a.label.localeCompare(b.label));
      const offset = ((rows - nodes.length) * GY) / 2;
      nodes.forEach((n, i) => { pos[n.id] = { x: 8 + Number(d) * GX, y: TOP + offset + i * GY }; });
    });
    return { pos, W, H, GX, width: Object.keys(columns).length * GX, height: TOP + rows * GY + 6, depths: Object.keys(columns).map(Number) };
  }, [graph]);
  const { pos, W, H } = layout;
  const short = (text) => (text.length > 20 ? `${text.slice(0, 19)}…` : text);
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width="100%" style={{ minWidth: 980, maxWidth: layout.width * 1.15 }} role="img" aria-label="Capability graph from agent to reachable actions">
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--border-strong)" /></marker>
          <marker id="arr-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--blocked)" /></marker>
        </defs>
        {layout.depths.map((d) => <text key={d} x={8 + d * layout.GX} y={13} fontSize="10.5" fontWeight="700" fill="var(--faint)" letterSpacing=".06em">{COLUMNS[d] || "REACHED"}</text>)}
        {graph.edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to];
          if (!a || !b) return null;
          const same = Math.abs(a.x - b.x) < 1;
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = same ? b.x + W : b.x, y2 = b.y + H / 2;
          const d = same ? `M${x1},${y1} C${x1 + 34},${y1} ${x2 + 34},${y2} ${x2 + 2},${y2}` : `M${x1},${y1} C${x1 + 30},${y1} ${x2 - 30},${y2} ${x2 - 2},${y2}`;
          const control = e.control && e.control.type;
          const color = e.flagged ? "var(--blocked)" : control === "blocks" ? "var(--ok)" : control === "approval" ? "var(--human)" : e.accepted_risk ? "var(--warn)" : "var(--border-strong)";
          const mx = same ? x1 + 26 : (x1 + x2) / 2, my = (y1 + y2) / 2;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke={color} strokeWidth={e.flagged ? 2.4 : 1.3} strokeDasharray={control ? "5 4" : e.kind === "link" && !e.flagged ? "2 3" : "0"}
                markerEnd={`url(#${e.flagged ? "arr-red" : "arr"})`}><title>{e.why || ""}{e.control ? ` Control: ${e.control.name}` : ""}</title></path>
              {control && <g><circle cx={mx} cy={my} r="8" fill="var(--surface)" stroke={color} /><text x={mx} y={my + 3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill={color}>{control === "blocks" ? "✕" : "H"}</text><title>{e.control.name}</title></g>}
            </g>
          );
        })}
        {graph.nodes.map((n) => {
          const p = pos[n.id];
          if (!p) return null;
          const critical = n.type === "action" && n.sensitivity === "critical";
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`}>
              <rect width={W} height={H} rx="7" fill={n.flagged ? "var(--blocked-bg)" : "var(--surface)"} stroke={n.flagged ? "var(--blocked)" : NODE_COLOR[n.type]} strokeWidth={n.flagged || n.type === "agent" ? 2 : 1.1} />
              <text x={W / 2} y={H / 2 + 4} textAnchor="middle" fontSize="11.5" fontWeight={n.type === "agent" || critical ? 700 : 500} fill={n.flagged ? "var(--blocked)" : "var(--text)"}>{short(n.label)}</text>
              <title>{n.label}{n.description ? ` - ${n.description}` : ""}{n.sensitivity ? ` (sensitivity: ${n.sensitivity})` : ""}</title>
            </g>
          );
        })}
      </svg>
      <div className="row small muted" style={{ marginTop: 6 }}>
        <span><b style={{ color: "var(--blocked)" }}>━━</b> unexpected path</span>
        <span><b style={{ color: "var(--ok)" }}>╌✕╌</b> cut by a technical control</span>
        <span><b style={{ color: "var(--human)" }}>╌H╌</b> continues only after human approval</span>
        <span><b>┈┈</b> indirect link between systems</span>
        <span><b style={{ color: "var(--warn)" }}>┈┈</b> accepted risk</span>
        <span>Hover any node or edge for details.</span>
      </div>
    </div>
  );
}

function CapabilityTab() {
  const lab = useLab();
  const [agent, setAgent] = useState("coding-agent");
  const [version, setVersion] = useState(0);
  const { data: overview } = useFetch("/api/security/capability", [version]);
  const { data: report } = useFetch(`/api/security/capability/${agent}`, [version]);
  const { data: policies } = useFetch("/api/security/policies", [version]);
  const apply = (name) => lab.act(async () => {
    const result = await api.post("/api/security/scenario", { name });
    lab.notify(name === "recommended" ? "ok" : "info", name === "recommended"
      ? `Recommended policy applied. Critical paths: ${result.before.critical} → ${result.after.critical}.` : "Unsafe configuration loaded for the demonstration.");
    setVersion((v) => v + 1);
    return result;
  });
  if (!report || !policies || !overview) return <Card><Spinner /> Computing reachability…</Card>;
  const unsafe = policies.scenario === "unsafe";
  const critical = report.findings.filter((f) => f.severity === "CRITICAL");
  return (
    <div className="stack">
      {unsafe ? (
        <Card kind="blocked" title="The Coding Agent is over-privileged" right={<button className="btn danger" disabled={lab.busy} onClick={() => apply("recommended")}>APPLY RECOMMENDED POLICY</button>}>
          <p>Its configuration was inherited from an early pilot. It still <b>denies</b> production.deploy, main.merge and secrets.read, so it looks safe in a permissions review. Three extra grants (<code>repo.write</code>, <code>github.workflow.write</code>, <code>deployment.trigger</code>) make production reachable anyway.</p>
          <p className="small muted" style={{ margin: 0 }}>Nothing bad has happened, which is exactly why nobody noticed. The security stage of the workflow refuses to continue while this path exists.</p>
        </Card>
      ) : (
        <Card kind="ok" title="Least privilege is in force" right={<button className="btn sm" disabled={lab.busy} onClick={() => apply("unsafe")}>Load the unsafe configuration again</button>}>
          <p style={{ margin: 0 }}>The Coding Agent can read the repository, write to feature branches, run tests and open pull requests. No path to production exists. Change it back to watch the path reappear.</p>
        </Card>
      )}
      <div className="grid g4">
        <Stat label="Declared capabilities" value={report.declared.length} hint="tools the policy grants" />
        <Stat label="Actually reachable actions" value={report.reachable_actions.length} hint="computed over the graph" />
        <Stat label="Unexpected paths" value={report.findings.length} kind={critical.length ? "blocked" : ""} hint={`${critical.length} critical`} />
        <Stat label="Agents with a critical path" value={overview.filter((o) => o.summary.critical).length} hint={`of ${overview.length} identities audited`} kind={overview.some((o) => o.summary.critical) ? "blocked" : "ok"} />
      </div>
      <Card title="Capability graph" right={
        <select className="input" style={{ width: 240 }} aria-label="Agent" value={agent} onChange={(e) => setAgent(e.target.value)}>
          {overview.map((o) => <option key={o.agent} value={o.agent}>{o.display_name}{o.summary.critical ? " · CRITICAL" : ""}</option>)}
        </select>}>
        <p className="small muted">Policy source: <code>{report.policy_source}</code></p>
        <CapabilityGraph graph={report.graph} />
      </Card>
      {report.findings.map((f, i) => (
        <Card key={i} kind={f.severity === "CRITICAL" ? "blocked" : "warn"} title={f.title} right={<><Sev level={f.severity} />{f.explicitly_denied && <Badge kind="blocked">policy says DENY, graph says reachable</Badge>}</>}>
          <dl className="kv">
            <dt>Agent</dt><dd>{f.agent}</dd>
            <dt>Unexpected path</dt><dd><div className="row" style={{ gap: 4 }}>{f.path.map((p, j) => <span key={j} className="row" style={{ gap: 4 }}>{j > 0 && <span className="faint">→</span>}<Badge kind={j === f.path.length - 1 ? "blocked" : "outline"}>{p}</Badge></span>)}</div></dd>
            <dt>Why it works</dt><dd><ul>{f.why.map((w) => <li key={w}>{w}</li>)}</ul></dd>
            <dt>Recommendation</dt><dd><ul>{f.recommendation.map((r) => <li key={r}>{r}</li>)}</ul></dd>
            {f.accepted_risk && <><dt>Accepted risk</dt><dd>{f.accepted_risk}</dd></>}
          </dl>
        </Card>
      ))}
      <div className="grid g2">
        <Card title="Declared capability vs actual reachable capability">
          <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}><table>
            <thead><tr><th>Reachable action</th><th>How</th><th>Verdict</th></tr></thead>
            <tbody>{report.reach.map((r, i) => (
              <tr key={i}><td className="mono">{r.action}<div><Badge kind={r.sensitivity === "critical" ? "blocked" : "outline"}>{r.sensitivity}</Badge></div></td>
                <td className="small muted">{r.transitive ? r.path.slice(2).join(" → ") : `direct grant of ${r.entry_tool}`}{r.controls.map((c, j) => <div key={j} style={{ color: "var(--ok)" }}>Control: {c.name}</div>)}</td>
                <td><Badge kind={STATUS[r.status][0]}>{STATUS[r.status][1]}</Badge></td></tr>
            ))}</tbody>
          </table></div>
        </Card>
        <Card title="Forbidden actions: does the promise hold?">
          <table><thead><tr><th>Policy forbids</th><th>Graph says</th><th></th></tr></thead>
            <tbody>{report.forbidden_check.map((c) => (
              <tr key={c.action}><td className="mono">{c.action}</td><td><Badge kind={STATUS[c.reachable_as][0]}>{STATUS[c.reachable_as][1]}</Badge></td><td>{c.ok ? "✓" : "✗"}</td></tr>
            ))}</tbody></table>
        </Card>
      </div>
    </div>
  );
}

function PoliciesTab() {
  const { data } = useFetch("/api/security/policies");
  const [selected, setSelected] = useState("coding-agent");
  if (!data) return null;
  const policy = data.agents.find((a) => a.agent === selected);
  return (
    <div className="grid" style={{ gridTemplateColumns: "250px minmax(0, 1fr)" }}>
      <Card title="Identities">
        <div className="stack" style={{ gap: 4 }}>
          {data.agents.map((a) => <button key={a.agent} className={`btn sm ${a.agent === selected ? "primary" : "ghost"}`} style={{ justifyContent: "flex-start" }} onClick={() => setSelected(a.agent)}>{a.display_name}</button>)}
          <button className={`btn sm ${selected === "global" ? "primary" : "ghost"}`} style={{ justifyContent: "flex-start" }} onClick={() => setSelected("global")}>Global rules and invariants</button>
        </div>
      </Card>
      <div className="stack">
        {selected === "global" ? <Card title="policies/global.yaml"><div className="code"><pre>{data.global_yaml}</pre></div></Card> : (
          <>
            <Card title={policy.display_name} right={<Badge>{policy.source}</Badge>}>
              <p>{policy.purpose}</p>
              <div className="grid g3">
                <div><h3 style={{ color: "var(--ok)" }}>ALLOW</h3><div className="chip-list">{policy.allowed.map((t) => <Badge key={t} kind="ok">{t}</Badge>)}</div></div>
                <div><h3 style={{ color: "var(--human)" }}>REQUIRE_APPROVAL</h3><div className="chip-list">{policy.require_approval.length ? policy.require_approval.map((t) => <Badge key={t} kind="human">{t}</Badge>) : <span className="muted small">none</span>}</div></div>
                <div><h3 style={{ color: "var(--blocked)" }}>DENY</h3><div className="chip-list">{policy.denied.map((t) => <Badge key={t} kind="blocked">{t}</Badge>)}</div></div>
              </div>
              <p className="small muted" style={{ marginTop: 10 }}>Anything not listed is denied (default deny). Network: {String(policy.network)}. Secrets: {policy.secrets ? "yes" : "no"}.</p>
            </Card>
            <Card title="YAML (the enforced artefact)"><div className="code"><pre>{policy.yaml}</pre></div></Card>
          </>
        )}
        <Card title="How a decision is made">
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li><b>Kill switch</b>: if on, every tool execution is blocked.</li>
            <li><b>Invariants</b>: merge, secrets, IAM, policy changes and approvals can never be granted to an AI agent, whatever a policy file says.</li>
            <li><b>DENY</b> in the agent's policy.</li><li><b>REQUIRE_APPROVAL</b>: a named human with the right role must approve; the pipeline identity executes.</li>
            <li><b>ALLOW</b>, then branch and path constraints are checked.</li><li><b>Default deny</b> for everything else.</li>
          </ol>
        </Card>
      </div>
    </div>
  );
}

function RedTeamTab() {
  const lab = useLab();
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const run = () => { setRunning(true); api.post("/api/security/redteam").then(setReport).catch((e) => lab.notify("error", e.message)).finally(() => { setRunning(false); lab.refresh(); }); };
  return (
    <div className="stack">
      <Card kind="warn" title="SAFE RED-TEAM MODE" right={<button className="btn danger" disabled={running} onClick={run}>{running ? <><Spinner /> Attacking…</> : "Run all scenarios"}</button>}>
        <p style={{ margin: 0 }}>Scope: mock systems, the local sandbox and fake APIs only. Nothing here touches real infrastructure. Each scenario assumes the worst case, that the model was fully talked into the attack and really calls the tools, then checks whether the controls hold.</p>
      </Card>
      {report && (
        <>
          <div className="grid g4">
            <Stat label="Scenarios blocked" value={`${report.passed} / ${report.total}`} kind={report.passed === report.total ? "ok" : "blocked"} />
            <Stat label="Tool calls attempted" value={report.attempts} /><Stat label="Attempts stopped" value={report.blocked_attempts} />
            <Stat label="Scope" value={<span style={{ fontSize: 14 }}>{report.scope}</span>} />
          </div>
          {report.results.map((r) => (
            <Card key={r.id} kind={r.passed ? "ok" : "blocked"} title={r.name} right={<><span className="small muted">expected</span><Decision value={r.expected} /><span className="small muted">result</span><Decision value={r.outcome} /></>}>
              <p className="quote" style={{ borderColor: "var(--blocked)" }}>“{r.attack}”</p>
              <dl className="kv" style={{ marginTop: 8 }}>
                <dt>Which policy blocked it</dt><dd className="mono">{r.blocked_by || "nothing blocked it"}</dd>
                <dt>Tool it would need</dt><dd className="mono">{r.tool_required}</dd>
                <dt>Why human approval</dt><dd>{r.why_human_approval}</dd>
                <dt>What happened</dt><dd>{r.explanation}</dd>
                {r.paths && r.paths.length > 0 && <><dt>Open paths</dt><dd>{r.paths.map((p, i) => <div key={i} className="small mono">{p.join(" → ")}</div>)}</dd></>}
              </dl>
              <div className="table-wrap" style={{ marginTop: 8 }}><table>
                <thead><tr><th>Identity</th><th>Attempted tool</th><th>Decision</th><th>Rule</th><th>Executed</th></tr></thead>
                <tbody>{r.attempts.map((a, i) => <tr key={i}><td>{a.agent}</td><td className="mono">{a.tool}</td><td><Decision value={a.decision} /></td><td className="mono small">{a.rule}</td>
                  <td>{a.executed ? (a.redactions ? `yes, ${a.redactions} secret(s) redacted from the result` : <b style={{ color: "var(--blocked)" }}>yes</b>) : "no"}</td></tr>)}</tbody>
              </table></div>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

function InjectionTab() {
  const { data } = useFetch("/api/security/injection-demo");
  if (!data) return null;
  const flagged = new Set(data.findings.map((f) => f.line));
  return (
    <div className="grid g2">
      <Card title={`Hostile fixture: ${data.source}`} right={<Badge kind="warn">untrusted source</Badge>}>
        <div className="code">{data.text.split("\n").map((line, i) => (
          <pre key={i} style={flagged.has(i + 1) ? { background: "var(--blocked-bg)", color: "var(--blocked)", fontWeight: 600 } : undefined}>{line || " "}</pre>
        ))}</div>
      </Card>
      <div className="stack" style={{ alignContent: "start" }}>
        <Card kind="blocked" title={data.verdict} right={<Actor kind="blocked" />}>
          <dl className="kv"><dt>Source</dt><dd className="mono">{data.source}</dd><dt>Action</dt><dd>{data.action}</dd><dt>Reason</dt><dd>{data.reason}</dd>
            <dt>Risk score</dt><dd>{data.risk}</dd><dt>Reached a prompt?</dt><dd><b>{data.reached_prompt ? "YES" : "No. The chunk was quarantined at retrieval."}</b></dd></dl>
        </Card>
        <Card title="Signals detected">
          <table><tbody>{data.findings.map((f, i) => <tr key={i}><td><Badge kind="blocked">{f.label}</Badge></td><td className="small muted">line {f.line}</td><td className="num">{Math.round(f.confidence * 100)}%</td></tr>)}</tbody></table>
        </Card>
        <Card title="Why detection is not the defence">
          <p className="small" style={{ margin: 0 }}>Pattern matching catches known phrasing and misses new phrasing. The real defence is structural: retrieved text is wrapped as data, it cannot change an agent's permissions, and the tools this attack needs (secrets.read, network.fetch, production.deploy) are denied whether or not the injection is noticed. Run the red team to see that.</p>
        </Card>
      </div>
    </div>
  );
}

function SecretsTab() {
  const { data } = useFetch("/api/security/secrets-demo");
  if (!data) return null;
  return (
    <div className="stack">
      <Card kind="warn"><b>{data.note}</b> Fake values: FAKE_DB_PASSWORD, FAKE_AWS_KEY, FAKE_GITHUB_TOKEN. No real credential exists anywhere in this repository.</Card>
      {data.surfaces.map((s) => (
        <Card key={s.surface} title={`Secrets in ${s.label.toLowerCase()}`} right={<><Badge>{s.source}</Badge><Badge kind="blocked">{s.findings.length} detected</Badge></>}>
          <div className="grid g2">
            <div><h3 className="muted">As found</h3><div className="code"><pre>{s.original}</pre></div></div>
            <div><h3 style={{ color: "var(--ok)" }}>What an agent or log reader sees</h3><div className="code"><pre>{s.redacted}</pre></div></div>
          </div>
          <div className="chip-list" style={{ marginTop: 8 }}>{s.findings.map((f, i) => <Badge key={i} kind="blocked">{f.label} · line {f.line} · entropy {f.entropy}</Badge>)}</div>
        </Card>
      ))}
      <Card title="Sandbox environment"><p className="small">The complete environment of the process that runs generated code:</p><div className="chip-list">{data.sandbox_env_keys.map((k) => <Badge key={k}>{k}</Badge>)}</div></Card>
    </div>
  );
}

function FindingsTab() {
  const { run, artifacts } = useLab();
  const { data } = useFetch(`/api/security/findings?run_id=${run.id}`, [run.step_index, run.status]);
  const sec = artifacts.security;
  return (
    <div className="stack">
      {sec && (
        <Card kind={sec.gate.passed ? "ok" : "blocked"} title={sec.gate.passed ? "Security gate passed" : "Security gate failed"}>
          {sec.gate.passed ? <p style={{ margin: 0 }}>{sec.files_scanned} files scanned. No critical vulnerability, no credential in the diff, no unexpected critical path for any of {sec.capability.agents_audited} agents.</p>
            : <ul>{sec.gate.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
        </Card>
      )}
      <Card title="Security findings">
        {data && data.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Severity</th><th>Source</th><th>Finding</th><th>Recommendation</th><th>Status</th></tr></thead>
            <tbody>{data.map((f) => (
              <tr key={f.id}><td><Sev level={f.severity} /></td><td><Badge>{f.source}</Badge>{f.simulated && <Badge kind="warn">seeded</Badge>}</td>
                <td><b>{f.title}</b><div className="small muted">{f.detail}{f.file ? ` (${f.file}${f.line ? `:${f.line}` : ""})` : ""}</div></td>
                <td className="small">{f.recommendation}</td><td><Badge kind={f.status === "open" ? "blocked" : "outline"}>{f.status}</Badge></td></tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">No findings recorded yet.</p>}
      </Card>
    </div>
  );
}

export function Security() {
  const [tab, setTab] = useState("capability");
  return (
    <Page title="Security" stage="security" teach="security" steps={["security_review"]}
      sub="Before asking what an AI agent can do, verify what it is actually able to reach.">
      <Tabs value={tab} onChange={setTab} tabs={[["capability", "Capability & escape paths"], ["policies", "Policies"], ["redteam", "Red team"], ["injection", "Prompt injection"], ["secrets", "Secrets"], ["findings", "Findings"]]} />
      {tab === "capability" && <CapabilityTab />}
      {tab === "policies" && <PoliciesTab />}
      {tab === "redteam" && <RedTeamTab />}
      {tab === "injection" && <InjectionTab />}
      {tab === "secrets" && <SecretsTab />}
      {tab === "findings" && <FindingsTab />}
    </Page>
  );
}
