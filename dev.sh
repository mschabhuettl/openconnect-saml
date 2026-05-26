#!/usr/bin/env bash
# ==============================================================================
# dev.sh — tmux-Launcher für die (autonome) Arbeit an openconnect-saml
#
#   ./dev.sh            startet/attached die tmux-Session "openconnect"
#   ./dev.sh <name>     nutzt einen anderen Session-Namen
#
# Layout:
#   ┌───────────────┬───────────────┐
#   │               │  test / run   │   (Pane 1: bereit für `make dev` / `make test`)
#   │    claude     ├───────────────┤
#   │  (Pane 0)     │  git status   │   (Pane 2)
#   └───────────────┴───────────────┘
#
# tmux-Basics:  abdocken = Strg-b d  ·  andocken = tmux attach -t openconnect
# ==============================================================================
set -euo pipefail

SESSION="${1:-openconnect}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Schon vorhanden? -> nur andocken (bzw. innerhalb tmux umschalten).
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' läuft bereits — docke an…"
  if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$SESSION"; else exec tmux attach -t "$SESSION"; fi
fi

# Neue Session (detached), Fenster "dev", Pane 0 im Projektverzeichnis.
tmux new-session -d -s "$SESSION" -n dev -c "$PROJECT_DIR"

# Rechte Spalte abspalten (Pane 1), dann unten teilen (Pane 2).
tmux split-window -h -t "$SESSION:dev"   -c "$PROJECT_DIR"
tmux split-window -v -t "$SESSION:dev.1" -c "$PROJECT_DIR"

# Pane 1: Hinweis für Setup/Tests (uv-basiert; benötigt `uv` im PATH).
tmux send-keys -t "$SESSION:dev.1" 'echo "▶ Setup/Tests:  make dev   (uv sync --dev)   ·   make test   ·   make lint"' C-m
# Pane 2: aktueller Git-Stand.
tmux send-keys -t "$SESSION:dev.2" 'git status -sb' C-m

# Pane 0: Claude starten (Wrapper aus ~/.zshrc → YOLO/Bypass-Modus) und fokussieren.
tmux send-keys -t "$SESSION:dev.0" 'claude' C-m
tmux select-pane -t "$SESSION:dev.0"

# Andocken (oder umschalten, falls bereits in tmux).
if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$SESSION"; else exec tmux attach -t "$SESSION"; fi
