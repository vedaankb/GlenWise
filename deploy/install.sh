#!/usr/bin/env bash
# GleanWise installer for macOS and Linux. No Docker required.
#
#   deploy/install.sh                 install and start at login
#   deploy/install.sh --uninstall     stop and remove the service (your data is kept)
#   deploy/install.sh --uninstall --purge   also delete all data, including saved keys
#
# Options: --data-dir DIR  --port N  --no-service  --no-searxng  --with-browser  --skip-models  -h
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${GLEANWISE_DATA_DIR:-$HOME/.gleanwise}"
PORT="${GLEANWISE_PORT:-8787}"
# SearXNG has no release tags; this commit was verified to work with deploy/searxng/settings.yml.
SEARXNG_REF="${GLEANWISE_SEARXNG_REF:-4e2c1ea7f468c9d1b16206e9d4079999a2eb0627}"
DO_SERVICE=1 DO_SEARXNG=1 DO_BROWSER=0 DO_MODELS=1 UNINSTALL=0 PURGE=0

say() { printf '==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="${2:?--data-dir needs a value}"; shift 2 ;;
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --no-service) DO_SERVICE=0; shift ;;
    --no-searxng) DO_SEARXNG=0; shift ;;
    --with-browser) DO_BROWSER=1; shift ;;
    --skip-models) DO_MODELS=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge) PURGE=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

case "$DATA_DIR" in /*) ;; *) DATA_DIR="$PWD/$DATA_DIR" ;; esac
[[ "$PORT" =~ ^[0-9]+$ ]] || die "--port must be a number"

OS="$(uname -s)"
PLIST="$HOME/Library/LaunchAgents/com.gleanwise.core.plist"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/gleanwise-core.service"
CORE_DIR="$ROOT/services/core"
VENV="$DATA_DIR/venv" # kept outside the source tree so a developer checkout is never modified
BIN="$VENV/bin/gleanwise"

render() { # render TEMPLATE OUTPUT
  sed -e "s|@BIN@|$BIN|g" -e "s|@DATA_DIR@|$DATA_DIR|g" -e "s|@PORT@|$PORT|g" -e "s|@ROOT@|$ROOT|g" "$1" >"$2"
}

stop_service() {
  if [[ "$OS" == "Darwin" && -f "$PLIST" ]]; then
    launchctl bootout "gui/$(id -u)/com.gleanwise.core" 2>/dev/null || true
  elif [[ "$OS" == "Linux" && -f "$UNIT" ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now gleanwise-core.service 2>/dev/null || true
  fi
}

if [[ $UNINSTALL -eq 1 ]]; then
  say "Stopping GleanWise"
  stop_service
  rm -f "$PLIST" "$UNIT"
  command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload 2>/dev/null || true
  pkill -f "$DATA_DIR/searxng/venv/bin/python" 2>/dev/null || true
  if [[ $PURGE -eq 1 ]]; then
    [[ -n "$DATA_DIR" && "$DATA_DIR" != "/" && "$DATA_DIR" != "$HOME" ]] || die "Refusing to delete '$DATA_DIR'"
    say "Deleting $DATA_DIR (threads, cache, saved keys, downloaded models)"
    rm -rf "$DATA_DIR"
  else
    say "Kept your data in $DATA_DIR (add --purge to delete it)"
  fi
  say "Uninstalled. The source folder $ROOT was not touched."
  exit 0
fi

say "Installing GleanWise"
echo "    source: $ROOT"
echo "    data:   $DATA_DIR"
echo "    port:   $PORT"

mkdir -p "$DATA_DIR/logs"
chmod 700 "$DATA_DIR"

# --- uv (Python environment manager) ---------------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (Python package manager)"
  command -v curl >/dev/null 2>&1 || die "curl is required to install uv. Install it, or install uv yourself: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv did not install correctly."
fi

# --- core ------------------------------------------------------------------------------------
say "Setting up the core service"
(cd "$CORE_DIR" && UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --no-dev)
[[ -x "$BIN" ]] || die "Expected $BIN after 'uv sync'."
if [[ $DO_BROWSER -eq 1 ]]; then
  say "Installing the optional headless browser for JavaScript-heavy pages"
  "$VENV/bin/playwright" install chromium || warn "Browser install failed; pages that need JavaScript will be skipped."
fi

# --- web UI ----------------------------------------------------------------------------------
if [[ ! -f "$ROOT/apps/web/dist/index.html" ]]; then
  say "Building the web app"
  command -v node >/dev/null 2>&1 || die "Node.js 20+ is needed once to build the web app: https://nodejs.org/"
  if ! command -v pnpm >/dev/null 2>&1; then
    command -v corepack >/dev/null 2>&1 && corepack enable pnpm 2>/dev/null || true
    command -v pnpm >/dev/null 2>&1 || npm install -g pnpm@9 >/dev/null 2>&1 || die "Could not get pnpm. Install it: https://pnpm.io/installation"
  fi
  (cd "$ROOT" && pnpm install --frozen-lockfile && pnpm run build)
fi
[[ -f "$ROOT/apps/web/dist/index.html" ]] || die "The web app did not build."

# --- SearXNG (private search backend, run as a child process of the core) ---------------------
if [[ $DO_SEARXNG -eq 1 ]]; then
  SX="$DATA_DIR/searxng"
  if [[ -x "$SX/venv/bin/python" && -f "$SX/.ref" && "$(cat "$SX/.ref")" == "$SEARXNG_REF" ]]; then
    say "SearXNG already installed"
  else
    command -v git >/dev/null 2>&1 || die "git is required to fetch SearXNG. Re-run with --no-searxng to use your own search server."
    say "Installing SearXNG (private search, no Docker)"
    rm -rf "$SX/src" "$SX/venv"
    mkdir -p "$SX"
    git init -q "$SX/src"
    git -C "$SX/src" fetch -q --depth 1 https://github.com/searxng/searxng.git "$SEARXNG_REF"
    git -C "$SX/src" checkout -q FETCH_HEAD
    uv venv -q --python 3.12 "$SX/venv"
    uv pip install -q --python "$SX/venv/bin/python" -r "$SX/src/requirements.txt" pyyaml setuptools wheel
    uv pip install -q --python "$SX/venv/bin/python" --no-build-isolation --no-deps "$SX/src"
    echo "$SEARXNG_REF" >"$SX/.ref"
  fi
  # The core generates a per-machine secret key at first start (never a shared default).
fi

# --- models ----------------------------------------------------------------------------------
if [[ $DO_MODELS -eq 1 ]]; then
  say "Downloading the small local search models (one time, ~100 MB)"
  GLEANWISE_DATA_DIR="$DATA_DIR" "$BIN" prefetch || warn "Model download failed. The first search will retry it; you can run '$BIN prefetch' later."
fi

# --- service ---------------------------------------------------------------------------------
wait_ready() {
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/readyz" 2>/dev/null || curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/readyz" 2>/dev/null | grep -q 503; then
      return 0
    fi
    sleep 1
  done
  return 1
}

if [[ $DO_SERVICE -eq 1 ]]; then
  stop_service
  if [[ "$OS" == "Darwin" ]]; then
    mkdir -p "$(dirname "$PLIST")"
    render "$ROOT/deploy/launchd/com.gleanwise.core.plist.template" "$PLIST"
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    say "Started at login (launchd: com.gleanwise.core)"
  elif [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    mkdir -p "$UNIT_DIR"
    render "$ROOT/deploy/systemd/gleanwise-core.service" "$UNIT"
    systemctl --user daemon-reload
    systemctl --user enable --now gleanwise-core.service
    say "Started at login (systemd user service: gleanwise-core)"
    command -v loginctl >/dev/null 2>&1 && warn "To keep it running when you are logged out: loginctl enable-linger $USER"
  else
    warn "No supported service manager found. Start it yourself with:"
    echo "    GLEANWISE_DATA_DIR='$DATA_DIR' GLEANWISE_PORT=$PORT '$BIN' serve"
    DO_SERVICE=0
  fi
fi

if [[ $DO_SERVICE -eq 1 ]]; then
  say "Waiting for the service"
  if wait_ready; then
    echo
    echo "GleanWise is running:  http://127.0.0.1:$PORT"
    echo "Open it and the setup guide will ask for a language model and key."
  else
    warn "The service did not answer within 60 seconds. Logs: $DATA_DIR/logs/core.log"
    warn "Run '$BIN doctor' for a diagnosis."
    exit 1
  fi
else
  echo
  echo "Installed. Start it with:  GLEANWISE_DATA_DIR='$DATA_DIR' GLEANWISE_PORT=$PORT '$BIN' serve"
fi
echo "Check health any time:    GLEANWISE_DATA_DIR='$DATA_DIR' '$BIN' doctor"
echo "Uninstall:                $ROOT/deploy/install.sh --uninstall"
