#!/usr/bin/env bash
# AI-SDLC Champion Lab launcher. Works on a laptop and on an AWS EC2 instance.
#
#   ./start.sh                 build and start, then print the URLs
#   ./start.sh stop            stop the stack (data is kept)
#   ./start.sh status          show containers and URLs
#   ./start.sh logs [service]  follow logs
#   ./start.sh reset           stop and delete all lab data (database + sandbox)
#   ./start.sh install-docker  install Docker + Compose on Amazon Linux or Ubuntu (uses sudo)
#
# Ports: UI_PORT (default 3000) and API_PORT (default 8000). If a port is busy the next free
# one is used. The UI talks to the API through its own origin, so nothing needs to know the
# machine's IP address: open http://<public-ip>:<UI_PORT> and it works.

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then docker-compose "$@"
  else die "Docker Compose is not installed. Run: ./start.sh install-docker"; fi
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. Run: ./start.sh install-docker"
  docker info >/dev/null 2>&1 || die "Docker is installed but not usable by $(whoami). Start it (sudo systemctl start docker) and make sure you are in the 'docker' group (log out and in again after install-docker)."
}

install_docker() {
  [ -r /etc/os-release ] || die "Unknown operating system. Install Docker manually: https://docs.docker.com/engine/install/"
  . /etc/os-release
  case "${ID:-}" in
    amzn)
      sudo dnf install -y docker git
      sudo mkdir -p /usr/local/lib/docker/cli-plugins
      sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
      sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose ;;
    ubuntu|debian)
      sudo apt-get update
      sudo apt-get install -y docker.io docker-compose-v2 git || sudo apt-get install -y docker.io docker-compose-plugin git ;;
    *) die "Unsupported distribution '${ID:-unknown}'. Install Docker manually: https://docs.docker.com/engine/install/" ;;
  esac
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$(whoami)"
  say "Docker installed. Log out and back in (so the 'docker' group applies), then run ./start.sh"
}

port_busy() {
  if command -v ss >/dev/null 2>&1; then ss -ltn 2>/dev/null | grep -qE "[:.]$1[[:space:]]"
  else (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; fi
}

# Ports already published by this project's own containers are not "busy".
own_port() { compose port "$1" "$2" 2>/dev/null | sed 's/.*://' ; }

pick_port() {  # pick_port <wanted> <service> <container-port>
  local port="$1" mine
  mine="$(own_port "$2" "$3" || true)"
  [ -n "$mine" ] && { echo "$mine"; return; }
  while port_busy "$port"; do port=$((port + 1)); done
  echo "$port"
}

public_ip() {
  # EC2 instance metadata (IMDSv2). Returns nothing when not on EC2 or when there is no public IP.
  local token
  token="$(curl -fsS -m 1 -X PUT http://169.254.169.254/latest/api/token \
           -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  [ -n "$token" ] && curl -fsS -m 1 -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true
}

load_ports() {
  [ -f .lab-ports ] && . ./.lab-ports
  export UI_PORT="${UI_PORT:-3000}" API_PORT="${API_PORT:-8000}"
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
    warn "Security group: allow inbound TCP ${UI_PORT} (and ${API_PORT} only if you want the API docs) from YOUR IP ONLY."
    warn "This is a demo with no login: anyone who can reach the port can use it and reset it."
    warn "Do not open it to 0.0.0.0/0. Stop it after the presentation: ./start.sh stop"
  else
    local lan; lan="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -n "$lan" ] && echo "  Network   http://${lan}:${UI_PORT}"
  fi
  echo
  echo "  Mode      MOCK_AI=${MOCK_AI:-true} (no API key needed)"
  echo "  Stop      ./start.sh stop      Logs  ./start.sh logs"
}

start() {
  require_docker
  load_ports
  UI_PORT="$(pick_port "$UI_PORT" frontend 3000)"
  API_PORT="$(pick_port "$API_PORT" backend 8000)"
  export UI_PORT API_PORT
  printf 'UI_PORT=%s\nAPI_PORT=%s\n' "$UI_PORT" "$API_PORT" > .lab-ports

  say "Building and starting (first run takes a few minutes)..."
  compose up -d --build

  printf 'Waiting for the lab to become healthy'
  for _ in $(seq 1 90); do
    if curl -fsS -m 3 "http://localhost:${UI_PORT}/api/meta" >/dev/null 2>&1; then
      echo " ready."
      urls
      return 0
    fi
    printf '.'
    sleep 2
  done
  echo
  compose ps
  die "The lab did not become healthy in time. Inspect with: ./start.sh logs"
}

case "${1:-start}" in
  start|up)        start ;;
  stop|down)       load_ports; compose down; say "Stopped. Data is kept. Start again with ./start.sh" ;;
  status)          load_ports; compose ps; urls ;;
  logs)            load_ports; compose logs -f --tail=100 ${2:+"$2"} ;;
  reset)           load_ports; compose down -v; rm -f .lab-ports; say "Stopped and all lab data deleted." ;;
  install-docker)  install_docker ;;
  -h|--help|help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)               die "Unknown command '$1'. Try: ./start.sh help" ;;
esac
