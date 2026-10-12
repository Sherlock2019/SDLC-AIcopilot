import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useFetch, useLab } from "./store.jsx";

/* ---------- formatting ---------- */
export const money = (v, digits = 4) => (v == null ? "-" : `$${Number(v).toFixed(digits)}`);
export const num = (v) => (v == null ? "-" : Number(v).toLocaleString());
export const time = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "-");
export const dateTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-");

/* ---------- primitives ---------- */
export const Badge = ({ kind = "outline", children, title }) => <span className={`badge b-${kind}`} title={title}>{children}</span>;

const ACTORS = {
  ai: ["ai", "✦ AI action"], human: ["human", "● Human action"], system: ["system", "⚙ Automated system"],
  blocked: ["blocked", "⛔ Blocked action"], approval: ["human", "● Human approval"], human_action: ["human", "● Human action"],
};
export const Actor = ({ kind, label }) => {
  const [style, text] = ACTORS[kind] || ACTORS.system;
  return <Badge kind={style}>{label || text}</Badge>;
};
export const Legend = () => (
  <div className="legend" aria-label="Legend">
    <Actor kind="ai" /><Actor kind="human" /><Actor kind="system" /><Actor kind="blocked" />
  </div>
);

const SEV = { CRITICAL: "blocked", HIGH: "blocked", MEDIUM: "warn", LOW: "system", INFO: "outline" };
export const Sev = ({ level }) => <Badge kind={SEV[level] || "outline"}>{level}</Badge>;

const DECISION = {
  ALLOW: "ok", DENY: "blocked", REQUIRE_APPROVAL: "human", BLOCKED_KILL_SWITCH: "blocked", DRY_RUN: "warn",
  PASS: "ok", FAIL: "blocked", BLOCKED: "ok", VULNERABLE: "blocked",
};
export const Decision = ({ value }) => <Badge kind={DECISION[value] || "outline"}>{value}</Badge>;

export const Card = ({ title, kind = "", right, children, className = "" }) => (
  <section className={`card ${kind} ${className}`}>
    {(title || right) && (
      <div className="row between" style={{ marginBottom: 10 }}>
        <h2>{title}</h2>
        <div className="row">{right}</div>
      </div>
    )}
    {children}
  </section>
);

export const Stat = ({ label, value, hint, kind }) => (
  <div className={`card stat ${kind || ""}`}>
    <span className="label">{label}</span>
    <span className="value">{value}</span>
    {hint && <span className="hint">{hint}</span>}
  </div>
);

export const Bar = ({ value, max = 100, kind = "" }) => (
  <div className={`bar ${kind}`} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
    <i style={{ width: `${Math.max(0, Math.min(100, (100 * value) / (max || 1)))}%` }} />
  </div>
);

export const List = ({ items, empty = "None" }) =>
  items && items.length ? <ul>{items.map((item, i) => <li key={i}>{typeof item === "string" ? item : item.text || JSON.stringify(item)}</li>)}</ul> : <span className="muted">{empty}</span>;

export const Empty = ({ children }) => <div className="empty">{children}</div>;
export const Spinner = () => <span className="spin" aria-label="Working" />;
export const Simulated = ({ label = "SIMULATED" }) => <Badge kind="warn" title="Illustrative data, not a measurement">{label}</Badge>;

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([key, label]) => (
        <button key={key} role="tab" aria-selected={value === key} className={value === key ? "on" : ""} onClick={() => onChange(key)}>{label}</button>
      ))}
    </div>
  );
}

/* ---------- provenance: who produced this, with which model, at what cost ---------- */
export function Provenance({ meta }) {
  if (!meta) return null;
  return (
    <div className="row small muted" style={{ marginTop: 10 }}>
      <Badge kind="ai">{meta.agent_name}</Badge>
      <span>{meta.provider} / {meta.model}</span>
      <span>prompt {meta.prompt_version}</span>
      <span>{num(meta.tokens_in)} in + {num(meta.tokens_out)} out tokens</span>
      <span>{money(meta.cost_usd)}</span>
      {meta.scripted && <Badge kind="warn" title="MOCK_AI=true: this text is a deterministic script, not a live model call">scripted mock answer</Badge>}
      {(meta.notes || []).map((note, i) => <Badge key={i} kind="warn">{note}</Badge>)}
    </div>
  );
}

/* ---------- Learn Mode ---------- */
export function LearnPanel({ stage }) {
  const { learn, learnMode } = useLab();
  if (!learnMode || !learn || !learn.stages[stage]) return null;
  const data = learn.stages[stage];
  const render = (key) => {
    const value = data[key];
    if (key === "what_tools_can_ai_use") {
      return value.length ? (
        <div className="chip-list">
          {value.map((t) => <Badge key={t.tool} kind={t.mode === "allowed" ? "ok" : "human"} title={t.mode}>{t.tool}</Badge>)}
          {data.denied_examples.slice(0, 4).map((t) => <Badge key={t} kind="blocked" title="denied">{t}</Badge>)}
        </div>
      ) : "None. This stage is ordinary automation.";
    }
    return Array.isArray(value) ? <List items={value} /> : value;
  };
  return (
    <section className="learn" aria-label="Learn Mode">
      <h3>Learn Mode · {data.title}</h3>
      <div className="grid g4">
        {learn.questions.map(([key, label]) => (
          <div className="q" key={key}><b>{label}</b>{render(key)}</div>
        ))}
      </div>
    </section>
  );
}

export function TeachMe({ topic }) {
  const { learn } = useLab();
  const [open, setOpen] = useState(false);
  const [level, setLevel] = useState("beginner");
  const data = learn && learn.teach[topic];
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!data) return null;
  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>Teach Me</button>
      {open && (
        <>
          <div className="drawer-back" onClick={() => setOpen(false)} />
          <aside className="drawer" role="dialog" aria-label={`Teach Me: ${data.title}`}>
            <div className="row between"><h1>{data.title}</h1><button className="btn sm" onClick={() => setOpen(false)}>Close</button></div>
            <Tabs tabs={[["beginner", "Beginner"], ["engineer", "Engineer"], ["architect", "Architect"]]} value={level} onChange={setLevel} />
            <p style={{ fontSize: 15, lineHeight: 1.6 }}>{data[level]}</p>
            <div className="card flat stack">
              {learn && [0, 1, 2].map((i) => <div className="quote" key={i}>{["AI should increase engineering capability, not silently increase engineering risk.", "Before asking what an AI agent can do, verify what it is actually able to reach.", "AI proposes. Humans remain accountable."][i]}</div>)}
            </div>
            <Link to="/learn" onClick={() => setOpen(false)}>Open the full curriculum</Link>
          </aside>
        </>
      )}
    </>
  );
}

/* ---------- approvals ---------- */
export function ApprovalCard({ approval, options }) {
  const { decide, busy, me, meta } = useLab();
  const [comment, setComment] = useState("");
  const [option, setOption] = useState(approval.payload && approval.payload.recommended);
  const permitted = me && (me.roles || []).includes(approval.required_role);
  const holders = (meta ? meta.users : []).filter((u) => u.roles.includes(approval.required_role)).map((u) => u.id);
  return (
    <section className="card human" aria-label="Human approval required">
      <div className="row between">
        <h2>Human approval required · {approval.title}</h2>
        <Actor kind="human" label={`Needs role: ${approval.required_role}`} />
      </div>
      <p style={{ marginTop: 8 }}>{approval.summary}</p>
      <p className="small muted">Requested by <b>{approval.requested_by}</b>. The workflow cannot continue until a human decides. The decision is written to the audit log with your name.</p>
      {options && (
        <div className="row" style={{ margin: "8px 0" }} role="radiogroup" aria-label="Architecture option">
          {options.map((o) => (
            <label key={o.key} className={`btn sm ${option === o.key ? "human" : ""}`}>
              <input type="radio" name="option" checked={option === o.key} onChange={() => setOption(o.key)} style={{ display: "none" }} />
              Option {o.key} · {o.name}{approval.payload.recommended === o.key ? " (AI recommends)" : ""}
            </label>
          ))}
        </div>
      )}
      <label className="field">Comment (optional, required for changes)
        <textarea className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why are you deciding this way?" />
      </label>
      {!permitted && <p className="small" style={{ color: "var(--blocked)", marginTop: 8 }}>
        You are signed in as <b>{me && me.id}</b>, who does not hold the <b>{approval.required_role}</b> role. Try it: the server will refuse. Users with this role: {holders.join(", ")}.
      </p>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn human" disabled={busy} onClick={() => decide(approval.id, "approve", comment, options ? option : "")}>APPROVE</button>
        <button className="btn" disabled={busy || !comment.trim()} onClick={() => decide(approval.id, "request_changes", comment)}>REQUEST CHANGES</button>
        <button className="btn danger" disabled={busy} onClick={() => decide(approval.id, "reject", comment)}>REJECT</button>
      </div>
    </section>
  );
}

export function StepControl({ keys, options }) {
  const { run, advance, dryRun, fastForward, busy, flags } = useLab();
  if (!run) return null;
  const mine = run.steps.filter((s) => keys.includes(s.key));
  const current = run.current_step;
  if (run.status === "rejected") return <div className="card blocked"><b>Run rejected.</b> {run.blocked_reason}</div>;
  if (!mine.length) return null;
  const active = current && keys.includes(current.key) ? current : null;
  if (!active) {
    const first = mine[0];
    if (run.step_index > mine[mine.length - 1].index || run.status === "completed") {
      return <div className="row"><Badge kind="ok">✓ {mine.length > 1 ? "These steps are" : "This step is"} complete</Badge></div>;
    }
    return (
      <div className="card flat row between">
        <span className="muted">This stage has not run yet. The run is at step {run.step_index + 1} of {run.total_steps}: <b>{current ? current.title : "-"}</b>.</span>
        <button className="btn" disabled={busy} onClick={() => fastForward(first.key)}>{busy ? <Spinner /> : null} Fast-forward to this stage</button>
      </div>
    );
  }
  if (run.status === "blocked") {
    return (
      <div className="card blocked stack">
        <div className="row between"><h2>⛔ Step blocked · {active.title}</h2><Actor kind="blocked" /></div>
        <p>{run.blocked_reason}</p>
        <div className="row">
          {/path|capabilit|privilege/i.test(run.blocked_reason) && <Link className="btn danger" to="/security">Open the Capability Auditor</Link>}
          <button className="btn" disabled={busy} onClick={advance}>{busy ? <Spinner /> : null} Retry step</button>
        </div>
      </div>
    );
  }
  if (active.kind === "approval") {
    return run.pending_approval ? <ApprovalCard approval={run.pending_approval} options={active.key === "architecture_approval" ? options : null} /> : null;
  }
  const human = active.kind === "human_action";
  const label = { merge: "MERGE", incident_simulation: "SIMULATE INCIDENT" }[active.key] || `Run step: ${active.title}`;
  return (
    <div className={`card ${human ? "human" : active.kind}`}>
      <div className="row between">
        <div>
          <div className="row"><Actor kind={active.kind} />{active.agent && <Badge>{active.agent}</Badge>}<b>Next: {active.title}</b></div>
          <p className="muted small" style={{ margin: "6px 0 0" }}>{active.description}</p>
        </div>
        <div className="row">
          {!human && <button className="btn" disabled={busy} onClick={dryRun}>Dry run</button>}
          <button className={`btn ${human ? "human" : "primary"}`} disabled={busy} onClick={advance}>
            {busy ? <Spinner /> : null} {flags.dry_run && !human ? "Simulate (dry-run mode)" : label}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- page frame ---------- */
export function Page({ title, sub, stage, teach, steps, options, children, right }) {
  return (
    <div className="page">
      <header className="page-head">
        <div style={{ flex: 1 }}>
          <h1>{title}</h1>
          {sub && <p className="sub">{sub}</p>}
        </div>
        <div className="row">{right}{teach && <TeachMe topic={teach} />}</div>
      </header>
      {stage && <LearnPanel stage={stage} />}
      {steps && <StepControl keys={steps} options={options} />}
      {children}
    </div>
  );
}

/* ---------- tool calls made by an agent in this run ---------- */
export function ToolCalls({ actors, title = "Tool calls (through the policy gateway)" }) {
  const { run } = useLab();
  const { data } = useFetch(run ? `/api/runs/${run.id}/tool-calls` : null, [run && run.updated_at, run && run.step_index]);
  const rows = (data || []).filter((c) => !actors || actors.includes(c.actor));
  if (!rows.length) return null;
  return (
    <Card title={title} right={<span className="small muted">{rows.length} calls · every one is in the audit log</span>}>
      <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}>
        <table>
          <thead><tr><th>Identity</th><th>Tool</th><th>Input</th><th>Policy decision</th><th>Rule</th><th>Result</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>{c.actor}</td><td className="mono">{c.tool}</td>
                <td className="small muted" style={{ maxWidth: 280 }}>{c.args_summary}</td>
                <td><Decision value={c.decision} /></td><td className="small mono">{c.rule}</td>
                <td className="small">{c.ok ? "executed" : c.executed ? "failed" : "not executed"}{c.redactions ? ` · ${c.redactions} secret(s) redacted` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ---------- diff viewer ---------- */
function parseDiff(text) {
  const files = [];
  let file = null, oldLine = 0, newLine = 0;
  for (const raw of (text || "").split("\n")) {
    if (raw.startsWith("diff --git")) { file = { path: raw.split(" b/").pop(), lines: [], add: 0, del: 0, isNew: false }; files.push(file); continue; }
    if (!file) continue;
    if (raw.startsWith("new file")) { file.isNew = true; continue; }
    if (raw.startsWith("index ") || raw.startsWith("--- ") || raw.startsWith("+++ ") || raw.startsWith("\\")) continue;
    if (raw.startsWith("@@")) {
      const m = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(raw);
      if (m) { oldLine = Number(m[1]); newLine = Number(m[2]); }
      file.lines.push({ kind: "hunk", text: raw });
    } else if (raw.startsWith("+")) { file.lines.push({ kind: "add", b: newLine++, text: raw.slice(1) }); file.add++; }
    else if (raw.startsWith("-")) { file.lines.push({ kind: "del", a: oldLine++, text: raw.slice(1) }); file.del++; }
    else { file.lines.push({ kind: "ctx", a: oldLine++, b: newLine++, text: raw.slice(1) }); }
  }
  return files;
}

export function DiffViewer({ diff, openFirst = 1 }) {
  const files = useMemo(() => parseDiff(diff), [diff]);
  if (!files.length) return <Empty>No diff yet.</Empty>;
  return (
    <div className="stack">
      {files.map((file, index) => (
        <details className="diff" key={file.path} open={index < openFirst}>
          <summary>
            <Badge kind={file.isNew ? "ok" : "system"}>{file.isNew ? "new file" : "modified"}</Badge>
            <b>{file.path}</b><span className="add-n">+{file.add}</span><span className="del-n">-{file.del}</span>
          </summary>
          <div className="lines">
            {file.lines.map((line, i) => (
              <div key={i} className={`ln ${line.kind}`}>
                <span className="n">{line.a || ""}</span><span className="n">{line.b || ""}</span>
                <span>{line.kind === "add" ? "+ " : line.kind === "del" ? "- " : line.kind === "hunk" ? "" : "  "}{line.text}</span>
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

/* ---------- mermaid ---------- */
export function Mermaid({ chart }) {
  const ref = useRef(null);
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!chart) return undefined;
    import("mermaid").then(async ({ default: mermaid }) => {
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral", flowchart: { htmlLabels: true, curve: "basis" } });
      try {
        const { svg } = await mermaid.render(`m${id}`, chart);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    });
    return () => { cancelled = true; };
  }, [chart, id]);
  if (failed) return <div className="code"><pre>{chart}</pre></div>;
  return <div className="mermaid-box" ref={ref} role="img" aria-label="Diagram" />;
}

/* ---------- tiny markdown (headings, lists, bold, code) ---------- */
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part.startsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : part);
}
export function Markdown({ text }) {
  const blocks = [];
  let list = null;
  (text || "").split("\n").forEach((line, i) => {
    if (line.startsWith("- ")) { if (!list) { list = []; blocks.push({ list }); } list.push(line.slice(2)); return; }
    list = null;
    if (line.startsWith("# ")) blocks.push(<h2 key={i} style={{ fontSize: 16 }}>{inline(line.slice(2))}</h2>);
    else if (line.startsWith("## ")) blocks.push(<h2 key={i}>{inline(line.slice(3))}</h2>);
    else if (line.trim() === "---") blocks.push(<hr key={i} />);
    else if (line.trim()) blocks.push(<p key={i}>{inline(line)}</p>);
  });
  return <div className="md">{blocks.map((b, i) => (b.list ? <ul key={`l${i}`}>{b.list.map((item, j) => <li key={j}>{inline(item)}</li>)}</ul> : b))}</div>;
}

/* ---------- line chart ---------- */
export function LineChart({ points, series, height = 170, markers = [], unit = "", shade }) {
  const width = 640, pad = { l: 44, r: 12, t: 10, b: 22 };
  if (!points || !points.length) return <Empty>No data.</Empty>;
  const max = Math.max(1e-9, ...series.flatMap((s) => points.map((p) => p[s.key]))) * 1.12;
  const x = (i) => pad.l + (i * (width - pad.l - pad.r)) / Math.max(1, points.length - 1);
  const y = (v) => height - pad.b - (v / max) * (height - pad.t - pad.b);
  const t0 = new Date(points[0].ts).getTime(), t1 = new Date(points[points.length - 1].ts).getTime();
  const xt = (iso) => pad.l + ((new Date(iso).getTime() - t0) / Math.max(1, t1 - t0)) * (width - pad.l - pad.r);
  const ticks = [0, 0.5, 1].map((f) => f * max);
  const label = (v) => (v >= 100 ? Math.round(v) : v.toFixed(v < 10 ? 1 : 0));
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label={series.map((s) => s.label).join(", ")}>
        {shade && points.map((p, i) => p[shade] && i < points.length - 1 ? <rect key={i} x={x(i)} y={pad.t} width={x(i + 1) - x(i)} height={height - pad.t - pad.b} fill="var(--blocked-bg)" /> : null)}
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeDasharray={i ? "3 4" : "0"} />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="10.5" fill="var(--faint)">{label(v)}{unit}</text>
          </g>
        ))}
        {markers.filter((m) => new Date(m.ts).getTime() >= t0).map((m, i) => (
          <g key={i}>
            <line x1={xt(m.ts)} x2={xt(m.ts)} y1={pad.t} y2={height - pad.b} stroke={m.kind === "rollback" ? "var(--ok)" : "var(--human)"} strokeDasharray="4 3" />
            <text x={xt(m.ts) + 4} y={pad.t + 10} fontSize="10.5" fill="var(--muted)">{m.kind === "rollback" ? "rollback " : "deploy "}{m.version}</text>
          </g>
        ))}
        {series.map((s) => (
          <polyline key={s.key} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round"
            points={points.map((p, i) => `${x(i).toFixed(1)},${y(p[s.key]).toFixed(1)}`).join(" ")} />
        ))}
        <text x={pad.l} y={height - 5} fontSize="10.5" fill="var(--faint)">{time(points[0].ts)}</text>
        <text x={width - pad.r} y={height - 5} fontSize="10.5" fill="var(--faint)" textAnchor="end">{time(points[points.length - 1].ts)}</text>
      </svg>
      <figcaption className="row small muted">
        {series.map((s) => <span key={s.key} className="row" style={{ gap: 5 }}><i style={{ width: 12, height: 3, background: s.color, display: "inline-block", borderRadius: 2 }} />{s.label}</span>)}
        {shade && <span className="row" style={{ gap: 5 }}><i style={{ width: 12, height: 9, background: "var(--blocked-bg)", display: "inline-block", border: "1px solid var(--blocked)" }} />incident window</span>}
      </figcaption>
    </figure>
  );
}

/* ---------- dry-run plan drawer ---------- */
export function PlanDrawer() {
  const { plan, setPlan } = useLab();
  if (!plan) return null;
  return (
    <>
      <div className="drawer-back" onClick={() => setPlan(null)} />
      <aside className="drawer" role="dialog" aria-label="Dry run plan">
        <div className="row between"><h1>Dry run · {plan.title}</h1><button className="btn sm" onClick={() => setPlan(null)}>Close</button></div>
        <div className="card warn"><b>{plan.message}</b><p className="small" style={{ margin: "4px 0 0" }}>This is what the step would do. Each planned call was sent to the real policy engine, so the decisions below are real. No tool ran and the workflow did not advance.</p></div>
        {plan.plan.map((p, i) => (
          <div className="card flat" key={i}>
            <div className="row between"><span className="mono"><b>{p.identity}</b> → {p.tool}</span><Decision value={p.decision === "DRY_RUN" ? "DRY_RUN" : p.decision} /></div>
            <p style={{ margin: "6px 0 2px" }}>{p.would}</p>
            <span className="small muted">Policy verdict: {p.verdict} · rule <code>{p.rule}</code></span>
          </div>
        ))}
      </aside>
    </>
  );
}

export const NotRun = ({ what }) => <Empty>{what} appears here once the step has run.</Empty>;
