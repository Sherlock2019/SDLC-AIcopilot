const BASE = import.meta.env.VITE_API_URL || "";

let currentUser = localStorage.getItem("lab.user") || "dana";

export function setApiUser(user) {
  currentUser = user;
  localStorage.setItem("lab.user", user);
}

export function getApiUser() {
  return currentUser;
}

async function request(method, path, body) {
  const response = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", "X-User": currentUser },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
};
