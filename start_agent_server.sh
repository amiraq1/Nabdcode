#!/data/data/com.termux/files/usr/bin/bash

set -Eeuo pipefail

############################################
# Nabd Agent OS
# llama.cpp Server Launcher (Enhanced)
############################################

GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

MODEL_PATH="${MODEL_PATH:-$HOME/smart-agent/models/Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf}"

# Default: look in CMake build path first
LLAMA_SERVER="${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"

PORT="${PORT:-8080}"

CTX="${CTX:-4096}"

# Default to 4 threads to utilize performance cores
# and avoid overloading with weak cores.
THREADS="${THREADS:-4}"

LOG_DIR="$HOME/.nabd/logs"

LOG_FILE="$LOG_DIR/llama-server.log"

mkdir -p "$LOG_DIR"

############################################

log() {
    printf "%b%s%b\n" "$BLUE" "$1" "$NC"
}

warn() {
    printf "%b%s%b\n" "$YELLOW" "$1" "$NC"
}

fail() {
    printf "%b%s%b\n" "$RED" "$1" "$NC"
    exit 1
}

############################################

log "Starting local llama.cpp server..."

############################################
# Locate executable
############################################

if [[ ! -x "$LLAMA_SERVER" ]]; then

    if [[ -x "$HOME/llama.cpp/llama-server" ]]; then
        LLAMA_SERVER="$HOME/llama.cpp/llama-server"
    elif command -v llama-server >/dev/null 2>&1; then
        LLAMA_SERVER="$(command -v llama-server)"
    else
        fail "llama-server not found."
    fi

fi

############################################
# Verify model
############################################

[[ -f "$MODEL_PATH" ]] || fail "Model not found: $MODEL_PATH"

############################################
# Check port
############################################

if command -v ss >/dev/null 2>&1; then

    if ss -ltn | grep -q ":${PORT} "; then
        fail "Port ${PORT} already in use."
    fi

fi

############################################
# Shutdown handler
############################################

cleanup() {
    echo
    warn "Stopping llama.cpp server gracefully..."
}

# Trap now efficiently captures shutdown signal
trap cleanup INT TERM

############################################

log "Model      : $MODEL_PATH"
log "Threads    : $THREADS"
log "Context    : $CTX"
log "Port       : $PORT"
log "Binary     : $LLAMA_SERVER"

echo

############################################
# Launch
############################################

# Removed exec, using tee to print logs to terminal and save to file simultaneously
"$LLAMA_SERVER" \
    -m "$MODEL_PATH" \
    -c "$CTX" \
    -t "$THREADS" \
    --port "$PORT" \
    --cont-batching \
    --embedding \
    2>&1 | tee -a "$LOG_FILE"
