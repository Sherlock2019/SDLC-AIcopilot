#!/usr/bin/env bash
# AI-SDLC Champion Lab - one-command launcher for a laptop or an AWS EC2 instance.
#
#   ./start.sh                 do everything: install what is missing, build, start, print URLs
#   ./start.sh stop            stop the stack (data is kept)
#   ./start.sh restart         stop, rebuild and start
#   ./start.sh status          show containers and URLs
#   ./start.sh logs [service]  follow logs (backend | frontend | db)
#   ./start.sh test            run the lab's test-suite inside the backend image
#   ./start.sh reset           stop and delete all lab data (database + sandbox)
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

DOCKER=(docker)
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

can_sudo() { [ -z "$SUDO" ] || command -v sudo >/dev/null 2>&1; }
compose()  { "${DOCKER[@]}" compose "$@"; }

# --- 1. Docker ----------------------------------------------------------------------------------
install_compose_plugin() {
  local arch; arch="$(uname -m)"
  $SUDO mkdir -p /usr/local/lib/docker/cli-plugins
  $SUDO curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${arch}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  $SUDO chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
}

install_docker() {
  [ "$(uname -s)" = "Linux" ] || die "Docker is not installed. Install Docker Desktop, start it, and run ./start.sh again."
  [ -r /etc/os-release ] || die "Unknown Linux distribution. Install Docker manually: https://docs.docker.com/engine/install/"
  can_sudo || die "Docker is missing and sudo is not available to install it."
  . /etc/os-release
  say "Installing Docker (${PRETTY_NAME:-$ID})..."
  case "${ID:-}" in
    amzn|rhel|fedora|centos|rocky|almalinux)
      $SUDO dnf install -y docker git curl >/dev/null 2>&1 || $SUDO yum install -y docker git curl >/dev/null ;;
    ubuntu|debian)
      $SUDO apt-get update -qq
      DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq docker.io git curl >/dev/null ;;
    *) die "Unsupported distribution '${ID:-unknown}'. Install Docker manually: https://docs.docker.com/engine/install/" ;;
  esac
  $SUDO usermod -aG docker "$(id -un)" 2>/dev/null || true
  info "Docker installed. (You were added to the 'docker' group; it applies at your next login.)"
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    [ -n "${LAB_NO_INSTALL:-}" ] && die "Docker is not installed (LAB_NO_INSTALL is set)."
    install_docker
  fi
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
  # Compose v2 plugin
  if ! "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    [ -n "${LAB_NO_INSTALL:-}" ] && die "Docker Compose v2 is not installed (LAB_NO_INSTALL is set)."
    can_sudo || die "Docker Compose v2 is missing and sudo is not available to install it."
    say "Installing the Docker Compose plugin..."
    if [ -r /etc/os-release ] && grep -qiE '^ID=(ubuntu|debian)' /etc/os-release; then
      DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq docker-compose-v2 >/dev/null 2>&1 \
        || DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 \
        || install_compose_plugin
    else
      install_compose_plugin
    fi
    "${DOCKER[@]}" compose version >/dev/null 2>&1 || die "Could not install Docker Compose. See https://docs.docker.com/compose/install/"
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

  say "Building and starting (the first run takes a few minutes)..."
  compose up -d --build

  printf 'Waiting for the lab to become healthy'
  for _ in $(seq 1 120); do
    if curl -fsS -m 3 "http://localhost:${UI_PORT}/api/meta" >/dev/null 2>&1; then
      echo " ready."
      urls
      return 0
    fi
    printf '.'
    sleep 2
  done
  echo
  compose ps || true
  compose logs --tail=30 backend || true
  die "The lab did not become healthy in time. Inspect with: ./start.sh logs"
}

case "${1:-start}" in
  start|up)       start ;;
  restart)        ensure_docker; load_ports; compose down; start ;;
  stop|down)      ensure_docker; load_ports; compose down; say "Stopped. Data is kept. Start again with ./start.sh" ;;
  status)         ensure_docker; load_ports; compose ps; urls ;;
  logs)           ensure_docker; load_ports; compose logs -f --tail=100 ${2:+"$2"} ;;
  test)           ensure_docker; load_ports
                  "${DOCKER[@]}" build -q -f backend/Dockerfile -t ai-sdlc-lab-test . >/dev/null
                  "${DOCKER[@]}" run --rm -e LAB_DATA_DIR=/tmp/lab -v "$PWD/backend/tests:/srv/backend/tests:ro" \
                    ai-sdlc-lab-test python -m pytest ;;
  reset)          ensure_docker; load_ports; compose down -v; rm -f .lab-ports; say "Stopped and all lab data deleted." ;;
  -h|--help|help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)              die "Unknown command '$1'. Try: ./start.sh help" ;;
esac
