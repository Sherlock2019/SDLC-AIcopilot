#!/usr/bin/env bash
# AI-SDLC Champion Lab - LIGHT launcher. No Docker, no Postgres, no Node on the server.
# One Python process on one port serves the UI, the API and the API docs (SQLite storage).
# Runs on a t3.micro. For the full Docker stack use ./start-docker.sh.
#
#   ./start.sh                 install what is missing, start in the background, print URLs
#   ./start.sh stop            stop (data is kept)
#   ./start.sh restart         stop and start
#   ./start.sh status          is it running? which URL?
#   ./start.sh logs            follow the application log
#   ./start.sh test            run the lab's test-suite
#   ./start.sh reset           stop and delete all lab data
#   ./start.sh boot            also start automatically after a reboot (adds a @reboot crontab line)
#
# Port: PORT (default 4000; the next free port is used if it is taken).
# Needs: curl. git and tar are installed automatically on Amazon Linux / Ubuntu if missing.

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
STATE="$ROOT/.lab"
VENV="$STATE/venv"
PIDFILE="$STATE/app.pid"
LOG="$STATE/app.log"
PORTFILE="$STATE/port"
PYTHON_VERSION=3.12
mkdir -p "$STATE"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# --- prerequisites ------------------------------------------------------------------------------
ensure_tools() {
  command -v curl >/dev/null 2>&1 || die "curl is required. Install it and run ./start.sh again."
  local missing=() tool
  for tool in git tar gzip; do command -v "$tool" >/dev/null 2>&1 || missing+=("$tool"); done
  if [ "${#missing[@]}" -gt 0 ]; then
    say "Installing ${missing[*]}..."
    if command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y -q "${missing[@]}" >/dev/null
    elif command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -qq && $SUDO apt-get install -y -qq "${missing[@]}" >/dev/null
    else die "Please install: ${missing[*]}"; fi
  fi
  if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (fast Python installer, user-local, no sudo)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "Could not install uv. See https://docs.astral.sh/uv/"
    command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH. Open a new shell and run ./start.sh again."
  fi
}

ensure_venv() {
  local stamp="$STATE/requirements.sha"
  local want; want="$(sha256sum backend/requirements-light.txt | cut -d' ' -f1)"
  if [ ! -x "$VENV/bin/python" ]; then
    say "Creating the Python ${PYTHON_VERSION} environment (uv downloads Python if this OS has an older one)..."
    uv venv -q --python "$PYTHON_VERSION" "$VENV" || die "Could not create the Python environment."
  fi
  if [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
    say "Installing Python dependencies..."
    uv pip install -q --python "$VENV/bin/python" -r backend/requirements-light.txt || die "Dependency install failed."
    echo "$want" > "$stamp"
  fi
  [ -f frontend/dist/index.html ] || die "frontend/dist is missing. Run: git pull   (the built UI is committed to the repository)"
}

ensure_memory() {
  [ -r /proc/meminfo ] || return 0
  local ram swap
  ram="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
  swap="$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)"
  if [ "$ram" -lt 900 ] && [ "$swap" -lt 500 ] && [ ! -e /swapfile ] && command -v sudo >/dev/null 2>&1; then
    say "Very small instance (${ram} MB RAM): adding a 1 GB swap file..."
    { $SUDO fallocate -l 1G /swapfile || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none; } 2>/dev/null
    $SUDO chmod 600 /swapfile && $SUDO mkswap /swapfile >/dev/null && $SUDO swapon /swapfile || warn "Could not enable swap."
  fi
  return 0
}

# --- process ------------------------------------------------------------------------------------
running_pid() {
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

port_busy() {
  if command -v ss >/dev/null 2>&1; then ss -ltn 2>/dev/null | grep -qE "[:.]$1[[:space:]]"
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; fi
}

pick_port() {
  local port="${PORT:-4000}"
  while port_busy "$port"; do port=$((port + 1)); done
  echo "$port"
}

public_ip() {
  local token
  token="$(curl -fsS -m 1 -X PUT http://169.254.169.254/latest/api/token \
           -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  [ -n "$token" ] && curl -fsS -m 1 -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true
}

urls() {
  local port ip lan; port="$(cat "$PORTFILE")"; ip="$(public_ip)"
  echo
  say "AI-SDLC Champion Lab is running (light mode, pid $(running_pid))"
  echo "  UI        http://localhost:${port}"
  echo "  API docs  http://localhost:${port}/docs"
  if [ -n "$ip" ]; then
    echo
    say "AWS EC2 public address"
    echo "  UI        http://${ip}:${port}"
    echo "  API docs  http://${ip}:${port}/docs"
    echo
    warn "Security group: allow inbound TCP ${port} from YOUR IP ONLY. The lab has no login."
    warn "Never open it to 0.0.0.0/0. Stop it after the presentation: ./start.sh stop"
  else
    lan="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    [ -n "$lan" ] && echo "  Network   http://${lan}:${port}"
  fi
  echo
  echo "  Runs in the background: you can close this terminal or SSH session."
  echo "  Stop  ./start.sh stop     Logs  ./start.sh logs     Start after reboot  ./start.sh boot"
}

start() {
  if [ -n "$(running_pid)" ]; then urls; return 0; fi
  say "AI-SDLC Champion Lab (light) - preparing"
  ensure_tools
  ensure_memory
  ensure_venv
  local port; port="$(pick_port)"
  echo "$port" > "$PORTFILE"
  say "Starting on port ${port} in the background..."
  (
    cd backend
    LAB_DATA_DIR="$STATE/data" MOCK_AI="${MOCK_AI:-true}" GITHUB_ENABLED="${GITHUB_ENABLED:-false}" \
      nohup "$VENV/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "$port" >>"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
  )
  printf 'Waiting for the lab to become healthy'
  for _ in $(seq 1 60); do
    if curl -fsS -m 2 "http://localhost:${port}/api/meta" >/dev/null 2>&1; then
      echo " ready."; urls; return 0
    fi
    [ -z "$(running_pid)" ] && { echo; tail -25 "$LOG"; die "The lab exited during start-up. Full log: $LOG"; }
    printf '.'; sleep 1
  done
  echo; tail -25 "$LOG"; die "The lab did not become healthy in time. Full log: $LOG"
}

stop() {
  local pid; pid="$(running_pid || true)"
  if [ -z "$pid" ]; then say "Not running."; rm -f "$PIDFILE"; return 0; fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PIDFILE"
  say "Stopped. Data is kept. Start again with ./start.sh"
}

boot() {
  command -v crontab >/dev/null 2>&1 || die "crontab is not available on this machine."
  local line="@reboot cd '$ROOT' && ./start.sh >> '$LOG' 2>&1"
  ( crontab -l 2>/dev/null | grep -vF "$ROOT" || true; echo "$line" ) | crontab -
  say "The lab will start automatically after a reboot. Undo with: crontab -e"
}

case "${1:-start}" in
  start|up)       start ;;
  stop|down)      stop ;;
  restart)        stop; start ;;
  status)         if [ -n "$(running_pid)" ]; then urls; else say "Not running. Start with ./start.sh"; fi ;;
  logs)           touch "$LOG"; tail -n 100 -f "$LOG" ;;
  test)           ensure_tools; ensure_venv
                  uv pip install -q --python "$VENV/bin/python" -r backend/requirements.txt
                  (cd backend && "$VENV/bin/python" -m pytest) ;;
  reset)          stop; rm -rf "$STATE/data" "$LOG"; say "All lab data deleted." ;;
  boot)           boot ;;
  -h|--help|help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)              die "Unknown command '$1'. Try: ./start.sh help" ;;
esac
