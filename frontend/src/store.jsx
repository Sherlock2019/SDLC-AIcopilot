import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, getApiUser, setApiUser } from "./api.js";

const LabContext = createContext(null);
export const useLab = () => useContext(LabContext);

const stored = (key, fallback) => {
  const raw = localStorage.getItem(key);
  return raw === null ? fallback : raw === "true" ? true : raw === "false" ? false : raw;
};

export function LabProvider({ children }) {
  const [meta, setMeta] = useState(null);
  const [learn, setLearn] = useState(null);
  const [run, setRun] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(Number(stored("lab.run", 1)));
  const [user, setUserState] = useState(getApiUser());
  const [learnMode, setLearnModeState] = useState(stored("lab.learn", true));
  const [guided, setGuidedState] = useState(stored("lab.guided", false));
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const toastTimer = useRef();

  const notify = useCallback((kind, text) => {
    clearTimeout(toastTimer.current);
    setToast({ kind, text });
    toastTimer.current = setTimeout(() => setToast(null), kind === "error" ? 9000 : 5000);
  }, []);

  const refresh = useCallback(async (id = runId) => {
    const [nextMeta, nextRuns] = await Promise.all([api.get("/api/meta"), api.get("/api/runs")]);
    setMeta(nextMeta);
    setRuns(nextRuns);
    try {
      setRun(await api.get(`/api/runs/${id}`));
    } catch {
      setRunId(1);
      setRun(await api.get("/api/runs/1"));
    }
  }, [runId]);

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    api.get("/api/learn").then(setLearn).catch(() => {});
  }, [refresh]);

  const act = useCallback(async (fn, okText) => {
    setBusy(true);
    try {
      const result = await fn();
      await refresh();
      if (result && result.status === "blocked") notify("error", `Blocked: ${result.reason}`);
      else if (result && result.executed === false && result.plan) setPlan(result);
      else if (okText) notify("ok", okText);
      return result;
    } catch (e) {
      notify("error", e.message);
      await refresh().catch(() => {});
      return null;
    } finally {
      setBusy(false);
    }
  }, [refresh, notify]);

  const value = useMemo(() => ({
    meta, learn, run, runs, runId, user, learnMode, guided, busy, toast, plan, error, notify, refresh, act,
    users: meta ? meta.users : [],
    me: meta ? meta.users.find((u) => u.id === user) : null,
    flags: meta ? meta.flags : {},
    artifacts: run ? run.artifacts : {},
    stepOf: (key) => (run ? run.steps.find((s) => s.key === key) : null),
    setPlan,
    dismissToast: () => setToast(null),
    setUser: (id) => { setApiUser(id); setUserState(id); notify("info", `Now acting as ${id}.`); },
    setLearnMode: (on) => { localStorage.setItem("lab.learn", on); setLearnModeState(on); },
    setGuided: (on) => { localStorage.setItem("lab.guided", on); setGuidedState(on); },
    selectRun: (id) => { localStorage.setItem("lab.run", id); setRunId(id); },
    advance: () => act(() => api.post(`/api/runs/${runId}/advance`)),
    dryRun: () => act(() => api.post(`/api/runs/${runId}/dry-run`)),
    fastForward: (until) => act(async () => {
      const result = await api.post(`/api/runs/${runId}/fast-forward`, { until });
      const last = result.log[result.log.length - 1];
      if (last && last.status === "blocked") return { status: "blocked", reason: last.reason };
      if (last && last.status === "needs_other_role") throw new Error(last.reason);
      return result;
    }),
    decide: (approvalId, decision, comment, option) =>
      act(() => api.post(`/api/approvals/${approvalId}/decide`, { decision, comment, option }),
        decision === "approve" ? "Approved and recorded in the audit log." : "Decision recorded."),
    setFlags: (flags) => act(() => api.post("/api/flags", flags)),
    createRun: async (requirement, promptVersion) => {
      const created = await act(() => api.post("/api/runs", { requirement, prompt_version: promptVersion }), "Run created.");
      if (created) { localStorage.setItem("lab.run", created.id); setRunId(created.id); }
      return created;
    },
    resetDemo: async () => {
      await act(() => api.post("/api/demo/reset"), "Demo reset to its initial state.");
      localStorage.setItem("lab.run", 1);
      setRunId(1);
    },
  }), [meta, learn, run, runs, runId, user, learnMode, guided, busy, toast, plan, error, notify, refresh, act]);

  return <LabContext.Provider value={value}>{children}</LabContext.Provider>;
}

export function useFetch(path, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const reload = useCallback(() => {
    if (!path) return Promise.resolve();
    return api.get(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [path]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload, ...deps]);
  return { data, error, reload };
}
