import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Badge, PlanDrawer, Spinner } from "./components.jsx";
import { Architecture, Code, ContextEngine, Requirements, Tests } from "./pages/Build.jsx";
import { ArchitectureDiagram, Governance, Learn, Productivity } from "./pages/Govern.jsx";
import { Dashboard, Journey } from "./pages/Overview.jsx";
import { CiCd, Deployment, Incident, Observability } from "./pages/Ship.jsx";
import { Evaluation, PullRequests, Review } from "./pages/Verify.jsx";
import { Security } from "./pages/Security.jsx";
import { useLab } from "./store.jsx";

const NAV = [
  ["Overview", [["/", "Dashboard"], ["/journey", "SDLC Journey"]]],
  ["Build", [["/requirements", "Requirements"], ["/context", "Context Engine"], ["/architecture", "Architecture"], ["/code", "Code"], ["/tests", "Tests"]]],
  ["Verify", [["/pull-requests", "Pull Requests"], ["/review", "AI Review"], ["/security", "Security"], ["/evaluation", "Evaluation"]]],
  ["Ship", [["/cicd", "CI/CD"], ["/deployment", "Deployment"]]],
  ["Operate", [["/observability", "Observability"], ["/incident", "Incident / RCA"]]],
  ["Govern", [["/governance", "Governance"], ["/productivity", "Productivity"]]],
  ["Learn", [["/learn", "Learn"], ["/architecture-diagram", "Architecture Diagram"]]],
];

function pageStatus(run, path) {
  if (!run) return "";
  const steps = run.steps.filter((s) => s.page === path);
  if (!steps.length) return "";
  if (steps.some((s) => s.status === "blocked")) return "blocked";
  if (steps.some((s) => s.status === "waiting")) return "waiting";
  if (steps.some((s) => s.status === "current")) return "current";
  return steps.every((s) => s.status === "done") ? "done" : "";
}

function Sidebar() {
  const { run, meta } = useLab();
  return (
    <nav className="nav" aria-label="Main">
      <div className="brand">
        <b>AI-SDLC Champion Lab</b>
        <span>{meta ? meta.subtitle : ""}</span>
      </div>
      {NAV.map(([group, links]) => (
        <div key={group}>
          <h4>{group}</h4>
          {links.map(([path, label]) => (
            <NavLink key={path} to={path} end={path === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <i className={`dot ${pageStatus(run, path)}`} />{label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

function Topbar() {
  const lab = useLab();
  const { run, runs, meta, flags, user, users, learnMode, busy } = lab;
  const statusKind = { blocked: "blocked", waiting_approval: "human", completed: "ok", rejected: "blocked" }[run ? run.status : ""] || "ai";
  return (
    <header className="topbar">
      <select className="input" style={{ width: 210 }} aria-label="Workflow run" value={run ? run.id : ""} onChange={(e) => lab.selectRun(Number(e.target.value))}>
        {runs.map((r) => <option key={r.id} value={r.id}>#{r.id} {r.title}{r.simulated ? " (seeded history)" : ""}</option>)}
      </select>
      {run && <Badge kind={statusKind}>{run.state.replaceAll("_", " ")}</Badge>}
      {run && <span className="small muted">step {Math.min(run.step_index + 1, run.total_steps)} / {run.total_steps}</span>}
      {busy && <Spinner />}
      <span className="spacer" />
      {meta && <Badge kind={meta.mock_ai ? "warn" : "ok"} title="The whole lab runs without API keys">{meta.mock_ai ? "MOCK AI" : `AI: ${meta.provider}`}</Badge>}
      {meta && <Badge title="Git integration mode">{meta.github_mode === "github-sandbox" ? "GitHub sandbox" : "Local mock git"}</Badge>}
      <label className="switch"><input type="checkbox" checked={learnMode} onChange={(e) => lab.setLearnMode(e.target.checked)} />Learn Mode</label>
      <label className="switch warn" title="Show what the AI would do without executing anything">
        <input type="checkbox" checked={!!flags.dry_run} onChange={(e) => lab.setFlags({ dry_run: e.target.checked })} />Dry run
      </label>
      <button className={`btn sm ${flags.kill_switch ? "" : "danger"}`} onClick={() => lab.setFlags({ kill_switch: !flags.kill_switch })}
        title="Disable all AI tool execution">{flags.kill_switch ? "Re-enable AI tools" : "KILL SWITCH"}</button>
      <select className="input" style={{ width: 150 }} aria-label="Acting as" value={user} onChange={(e) => lab.setUser(e.target.value)}>
        {users.map((u) => <option key={u.id} value={u.id}>{u.name.split(" ")[0]} · {u.title.split(" (")[0]}</option>)}
      </select>
    </header>
  );
}

function GuideBar() {
  const lab = useLab();
  const navigate = useNavigate();
  const location = useLocation();
  const { run, guided, busy } = lab;
  if (!guided || !run) return null;
  const step = run.current_step;
  const go = (path) => location.pathname !== path && navigate(path);
  let title, text, action;
  if (run.status === "completed" || !step) {
    title = "Guided demo complete";
    text = "One feature went from request to RCA. Every AI action was policy-checked; every decision was human.";
    action = <button className="btn primary" onClick={() => navigate("/productivity")}>See the productivity dashboard</button>;
  } else if (run.status === "blocked") {
    title = `Step ${step.index + 1} blocked: ${step.title}`;
    text = run.blocked_reason;
    action = <>
      <button className="btn danger" onClick={() => navigate("/security")}>Open the Capability Auditor</button>
      <button className="btn" disabled={busy} onClick={() => { go(step.page); lab.advance(); }}>Retry</button>
    </>;
  } else if (step.kind === "approval") {
    title = `Step ${step.index + 1} of ${run.total_steps}: ${step.title}`;
    text = `Waiting for a human with the '${step.required_role}' role. ${step.description}`;
    action = <>
      <button className="btn" onClick={() => go(step.page)}>Review</button>
      <button className="btn human" disabled={busy || !run.pending_approval} onClick={() => { go(step.page); lab.decide(run.pending_approval.id, "approve", "Approved in guided demo", ""); }}>Approve as {lab.user}</button>
    </>;
  } else {
    const human = step.kind === "human_action";
    title = `Step ${step.index + 1} of ${run.total_steps}: ${step.title}`;
    text = step.description;
    action = <>
      <button className="btn" onClick={() => go(step.page)}>Open page</button>
      <button className={`btn ${human ? "human" : "primary"}`} disabled={busy} onClick={() => { go(step.page); lab.advance(); }}>
        {busy ? <Spinner /> : null} {human ? ({ merge: "MERGE", incident_simulation: "SIMULATE INCIDENT" }[step.key]) : "Run this step"}
      </button>
    </>;
  }
  return (
    <div className="guide" role="region" aria-label="Guided demo">
      <Badge kind="ai">GUIDED DEMO</Badge>
      <div className="txt"><b>{title}</b><span title={text}>{text}</span></div>
      {action}
      <button className="btn ghost sm" onClick={() => lab.setGuided(false)}>Exit</button>
    </div>
  );
}

export default function App() {
  const { meta, run, error, flags, toast, dismissToast } = useLab();
  if (error && !meta) {
    return <div style={{ padding: 40 }}><h1>Cannot reach the API</h1><p className="muted">{error}</p>
      <p>Start it with <code>docker compose up</code> or <code>make dev</code>. The UI expects the API on port 8000.</p></div>;
  }
  if (!meta || !run) return <div style={{ padding: 40 }}><Spinner /> Loading the lab…</div>;
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        {flags.kill_switch && <div className="banner kill" role="alert">⛔ {meta.kill_switch_message} <span style={{ fontWeight: 400 }}>Agents may analyze and explain. They may not execute tools.</span></div>}
        {flags.dry_run && <div className="banner dry">DRY RUN / SIMULATION MODE · steps show what the AI would do. No action is executed.</div>}
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/journey" element={<Journey />} />
            <Route path="/requirements" element={<Requirements />} />
            <Route path="/context" element={<ContextEngine />} />
            <Route path="/architecture" element={<Architecture />} />
            <Route path="/code" element={<Code />} />
            <Route path="/tests" element={<Tests />} />
            <Route path="/pull-requests" element={<PullRequests />} />
            <Route path="/review" element={<Review />} />
            <Route path="/security" element={<Security />} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="/cicd" element={<CiCd />} />
            <Route path="/deployment" element={<Deployment />} />
            <Route path="/observability" element={<Observability />} />
            <Route path="/incident" element={<Incident />} />
            <Route path="/governance" element={<Governance />} />
            <Route path="/productivity" element={<Productivity />} />
            <Route path="/learn" element={<Learn />} />
            <Route path="/architecture-diagram" element={<ArchitectureDiagram />} />
            <Route path="*" element={<Dashboard />} />
          </Routes>
        </main>
      </div>
      <GuideBar />
      <PlanDrawer />
      {toast && <div className={`toast ${toast.kind}`} role="status"><span style={{ flex: 1 }}>{toast.text}</span><button className="btn ghost sm" onClick={dismissToast}>✕</button></div>}
    </div>
  );
}
