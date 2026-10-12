#!/usr/bin/env bash
# AI-SDLC Champion Lab - one-command launcher for a laptop or an AWS EC2 instance.
#
#   ./start.sh                 do everything: install what is missing, build, start in the
#                              background, print URLs (survives logout and reboot)
#   ./start.sh stop            stop the stack (data is kept; no restart after reboot)
#   ./start.sh restart         stop, rebuild and start
#   ./start.sh status          show containers and URLs
#   ./start.sh logs [service]  follow logs (backend | frontend | db)
#   ./start.sh test            run the lab's test-suite inside the backend image
#   ./start.sh reset           stop and delete all lab data (database + sandbox)
#   ./start.sh install         only install Docker, Compose and buildx, then exit
#
# What "everything" means for a plain `./start.sh`:
#   1. installs Docker and Docker Compose if they are missing (Amazon Linux, Ubuntu, Debian; uses sudo)
#   2. starts the Docker daemon if it is not running
#   3. works even before your user is in the `docker` group (falls back to sudo docker)
#   4. adds a 2 GB swap file on small instances so the UI build does not run out of memory
#   5. creates .env from .env.example if there is none (mock AI, no keys needed)
#   6. picks free ports if 3000 / 8000 are taken (override with UI_PORT / API_PORT)
#   7. builds the images, starts the stack, waits until it is healthy
#   8. prints the local URLs and, on EC2, the public-IP URL
#
# Skip the system changes (steps 1-4) with:  LAB_NO_INSTALL=1 ./start.sh

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

BUILD_LOG="$PWD/.lab-build.log"
DOCKER=(docker)
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

can_sudo() { [ -z "$SUDO" ] || command -v sudo >/dev/null 2>&1; }
compose()  { "${DOCKER[@]}" compose "$@"; }

# --- 1. Docker ----------------------------------------------------------------------------------
PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
BUILDX_VERSION=v0.19.3   # docker compose needs buildx >= 0.17 to build images

install_compose_plugin() {
  $SUDO mkdir -p "$PLUGIN_DIR"
  $SUDO curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
    -o "$PLUGIN_DIR/docker-compose"
  $SUDO chmod +x "$PLUGIN_DIR/docker-compose"
}

install_buildx_plugin() {
  local arch
  case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) arch="$(uname -m)" ;; esac
  $SUDO mkdir -p "$PLUGIN_DIR"
  $SUDO curl -fsSL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-${arch}" \
    -o "$PLUGIN_DIR/docker-buildx"
  $SUDO chmod +x "$PLUGIN_DIR/docker-buildx"
}

buildx_ok() {  # true if buildx is installed and at least 0.17
  local version major minor
  version="$(docker buildx version 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+' | head -1 | tr -d v)"
  [ -n "$version" ] || return 1
  major="${version%%.*}"; minor="${version#*.}"
  [ "$major" -gt 0 ] || [ "$minor" -ge 17 ]
}

install_docker() {
  [ "$(uname -s)" = "Linux" ] || die "Docker is not installed. Install Docker Desktop, start it, and run ./start.sh again."
  [ -r /etc/os-release ] || die "Unknown Linux distribution. Install Docker manually: https://docs.docker.com/engine/install/"
  can_sudo || die "Docker is missing and sudo is not available to install it."
  . /etc/os-release
  say "Installing Docker (${PRETTY_NAME:-$ID})..."
  case "${ID:-}" in
    amzn|rhel|fedora|centos|rocky|almalinux)
      # Not "curl": Amazon Linux 2023 ships curl-minimal, and asking for curl conflicts with it.
      $SUDO dnf install -y docker git >/dev/null 2>&1 || $SUDO yum install -y docker git >/dev/null \
        || die "Could not install Docker with dnf/yum." ;;
    ubuntu|debian)
      $SUDO apt-get update -qq
      DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq docker.io git curl ca-certificates >/dev/null \
        || die "Could not install Docker with apt." ;;
    *) die "Unsupported distribution '${ID:-unknown}'. Install Docker manually: https://docs.docker.com/engine/install/" ;;
  esac
  $SUDO usermod -aG docker "$(id -un)" 2>/dev/null || true
  info "Docker installed. (You were added to the 'docker' group; it applies at your next login.)"
}

# Compose and buildx are client-side plugins: they can be checked and installed without the daemon.
ensure_plugins() {
  if ! docker compose version >/dev/null 2>&1; then
    [ -n "${LAB_NO_INSTALL:-}" ] && die "Docker Compose v2 is not installed (LAB_NO_INSTALL is set)."
    can_sudo || die "Docker Compose v2 is missing and sudo is not available to install it."
    say "Installing the Docker Compose plugin..."
    install_compose_plugin
    docker compose version >/dev/null 2>&1 || die "Could not install Docker Compose. See https://docs.docker.com/compose/install/"
  fi
  if ! buildx_ok; then
    [ -n "${LAB_NO_INSTALL:-}" ] && die "Docker buildx 0.17+ is not installed (LAB_NO_INSTALL is set)."
    can_sudo || die "Docker buildx 0.17+ is missing and sudo is not available to install it."
    say "Installing the Docker buildx plugin (${BUILDX_VERSION})..."
    install_buildx_plugin
    buildx_ok || die "Could not install Docker buildx. See https://github.com/docker/buildx#installing"
  fi
}

install_only() {
  command -v docker >/dev/null 2>&1 || install_docker
  command -v curl >/dev/null 2>&1 || die "curl is required to install the Docker plugins."
  ensure_plugins
  info "$(docker --version)"
  info "$(docker compose version)"
  info "$(docker buildx version)"
}

warn_firewall() {
  if command -v ufw >/dev/null 2>&1 && $SUDO -n ufw status 2>/dev/null | grep -q "Status: active"; then
    warn "ufw is active on this host: allow the UI port with  sudo ufw allow ${UI_PORT}/tcp"
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    warn "firewalld is running: allow the UI port with  sudo firewall-cmd --add-port=${UI_PORT}/tcp"
  fi
  return 0
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    [ -n "${LAB_NO_INSTALL:-}" ] && die "Docker is not installed (LAB_NO_INSTALL is set)."
    install_docker
  fi
  ensure_plugins
  # Daemon running?
  if ! docker info >/dev/null 2>&1 && ! $SUDO docker info >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1 && can_sudo && [ -z "${LAB_NO_INSTALL:-}" ]; then
      say "Starting the Docker daemon..."
      $SUDO systemctl enable --now docker >/dev/null 2>&1 || $SUDO service docker start >/dev/null 2>&1 || true
      for _ in $(seq 1 15); do $SUDO docker info >/dev/null 2>&1 && break; sleep 1; done
    fi
  fi
  # Usable as this user, or only through sudo (fresh install, group not applied yet)?
  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  elif [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER=(sudo -E docker)
    info "Using 'sudo docker' for this session (docker group not active yet)."
  else
    die "Docker is installed but the daemon is not reachable. On a laptop, start Docker Desktop. On Linux: sudo systemctl start docker"
  fi
}

# --- 4. memory ----------------------------------------------------------------------------------
ensure_memory() {
  [ -r /proc/meminfo ] || return 0
  local ram swap
  ram="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
  swap="$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)"
  if [ "$ram" -lt 1900 ] && [ "$swap" -lt 1000 ]; then
    if [ -n "${LAB_NO_INSTALL:-}" ] || ! can_sudo || [ -e /swapfile ]; then
      warn "Only ${ram} MB RAM and ${swap} MB swap: the UI build may run out of memory. Use a t3.small or larger."
      return 0
    fi
    say "Small instance (${ram} MB RAM): adding a 2 GB swap file so the build can finish..."
    $SUDO fallocate -l 2G /swapfile 2>/dev/null || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    $SUDO chmod 600 /swapfile && $SUDO mkswap /swapfile >/dev/null && $SUDO swapon /swapfile \
      || warn "Could not enable swap; continuing without it."
  fi
  local free_mb; free_mb="$(df -Pm . | awk 'NR==2 {print $4}')"
  [ "${free_mb:-9999}" -lt 4000 ] && warn "Only ${free_mb} MB of disk is free. The images need about 4 GB."
  return 0
}

# --- 5. configuration ---------------------------------------------------------------------------
ensure_env() {
  if [ ! -f .env ] && [ -f .env.example ]; then
    # Keep only the safe defaults: mock AI, no GitHub, compose-provided database URL.
    printf '# Created by start.sh. Mock AI, no keys needed. See .env.example for every option.\nMOCK_AI=true\nAI_PROVIDER=mock\nGITHUB_ENABLED=false\n' > .env
    info "Created .env with mock-AI defaults."
  fi
}

# --- 6. ports -----------------------------------------------------------------------------------
port_busy() {
  if command -v ss >/dev/null 2>&1; then ss -ltn 2>/dev/null | grep -qE "[:.]$1[[:space:]]"
  elif command -v lsof >/dev/null 2>&1; then lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; fi
}

own_port() { compose port "$1" "$2" 2>/dev/null | sed 's/.*://'; }

pick_port() {  # pick_port <wanted> <service> <container-port>
  local port="$1" mine
  mine="$(own_port "$2" "$3" || true)"       # a port our own running container holds is not "busy"
  [ -n "$mine" ] && { echo "$mine"; return; }
  while port_busy "$port"; do port=$((port + 1)); done
  echo "$port"
}

load_ports() {
  local wanted_ui="${UI_PORT:-}" wanted_api="${API_PORT:-}"
  [ -f .lab-ports ] && . ./.lab-ports
  export UI_PORT="${wanted_ui:-${UI_PORT:-3000}}" API_PORT="${wanted_api:-${API_PORT:-8000}}"
}

# --- 8. addresses -------------------------------------------------------------------------------
public_ip() {
  # EC2 instance metadata (IMDSv2). Prints nothing when not on EC2 or when there is no public IP.
  local token
  token="$(curl -fsS -m 1 -X PUT http://169.254.169.254/latest/api/token \
           -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  [ -n "$token" ] && curl -fsS -m 1 -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true
}

urls() {
  local ip; ip="$(public_ip)"
  echo
  say "AI-SDLC Champion Lab is running"
  echo "  UI        http://localhost:${UI_PORT}"
  echo "  API       http://localhost:${API_PORT}"
  echo "  API docs  http://localhost:${API_PORT}/docs"
  if [ -n "$ip" ]; then
    echo
    say "AWS EC2 public address"
    echo "  UI        http://${ip}:${UI_PORT}"
    echo "  API docs  http://${ip}:${API_PORT}/docs"
    echo
    warn_firewall
    warn "One thing this script cannot do for you: the EC2 security group."
    warn "  Allow inbound TCP ${UI_PORT} from YOUR IP ONLY (add ${API_PORT} only if you want the API docs)."
    warn "  The lab has no login: anyone who can reach the port can use it and reset it."
    warn "  Never open it to 0.0.0.0/0, and run ./start.sh stop after the presentation."
  else
    local lan; lan="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    [ -n "$lan" ] && echo "  Network   http://${lan}:${UI_PORT}"
  fi
  echo
  echo "  Mode      mock AI (no API key needed). Edit .env to use a real provider."
  echo "  Demo      click START GUIDED DEMO, or follow docs/demo-script.md"
  echo "  Stop      ./start.sh stop        Logs  ./start.sh logs"
}

# --- commands -----------------------------------------------------------------------------------
start() {
  say "AI-SDLC Champion Lab - preparing this machine"
  command -v curl >/dev/null 2>&1 || die "curl is required. Install it and run ./start.sh again."
  ensure_docker
  [ -z "${LAB_NO_INSTALL:-}" ] && ensure_memory
  ensure_env
  load_ports
  UI_PORT="$(pick_port "$UI_PORT" frontend 3000)"
  API_PORT="$(pick_port "$API_PORT" backend 8000)"
  export UI_PORT API_PORT
  printf 'UI_PORT=%s\nAPI_PORT=%s\n' "$UI_PORT" "$API_PORT" > .lab-ports
  info "Ports: UI ${UI_PORT}, API ${API_PORT}"

  say "Building images in the background (first run takes a few minutes; full output: ${BUILD_LOG})..."
  if ! compose build >"$BUILD_LOG" 2>&1; then
    tail -25 "$BUILD_LOG"
    die "Build failed. Full output: ${BUILD_LOG}"
  fi
  say "Starting containers in the background..."
  if compose up -d >>"$BUILD_LOG" 2>&1 && wait_healthy 90; then running; return 0; fi

  # Self-heal once: a stale Docker network (for example after an interrupted run) leaves the
  # API unable to reach the database. Recreating containers and network fixes it; data volumes are kept.
  warn "Not healthy yet. Recreating the containers and network once (your data is kept)..."
  compose down --remove-orphans >>"$BUILD_LOG" 2>&1 || true
  if compose up -d >>"$BUILD_LOG" 2>&1 && wait_healthy 120; then running; return 0; fi

  echo
  compose ps || true
  compose logs --tail=30 backend || true
  die "The lab did not become healthy. Inspect with: ./start.sh logs   (or restart Docker: sudo systemctl restart docker)"
}

running() {
  urls
  echo
  say "Running in the background."
  echo "  You can close this terminal or SSH session; the lab keeps running."
  echo "  It also restarts automatically after a reboot, until you run ./start.sh stop."
}

wait_healthy() {  # wait_healthy <attempts of 2 s>
  printf 'Waiting for the lab to become healthy'
  for _ in $(seq 1 "$1"); do
    if curl -fsS -m 3 "http://localhost:${UI_PORT}/api/meta" >/dev/null 2>&1; then
      echo " ready."
      return 0
    fi
    printf '.'
    sleep 2
  done
  echo
  return 1
}

case "${1:-start}" in
  start|up)       start ;;
  install)        install_only ;;
  restart)        ensure_docker; load_ports; compose down; start ;;
  stop|down)      ensure_docker; load_ports; compose down; say "Stopped. Data is kept. Start again with ./start.sh" ;;
  status)         ensure_docker; load_ports; compose ps; urls ;;
  logs)           ensure_docker; load_ports; compose logs -f --tail=100 ${2:+"$2"} ;;
  test)           ensure_docker; load_ports
                  "${DOCKER[@]}" build -q -f backend/Dockerfile -t ai-sdlc-lab-test . >/dev/null
                  "${DOCKER[@]}" run --rm -e LAB_DATA_DIR=/tmp/lab -v "$PWD/backend/tests:/srv/backend/tests:ro" \
                    ai-sdlc-lab-test python -m pytest ;;
  reset)          ensure_docker; load_ports; compose down -v; rm -f .lab-ports; say "Stopped and all lab data deleted." ;;
  -h|--help|help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)              die "Unknown command '$1'. Try: ./start.sh help" ;;
esac
