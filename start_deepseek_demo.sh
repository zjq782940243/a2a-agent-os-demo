#!/bin/sh
set -eu

DEMO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOOLS_ROOT=$(CDPATH= cd -- "$DEMO_ROOT/../tools" && pwd)

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  printf '%s\n' 'DEEPSEEK_API_KEY is required and is intentionally not stored in this project.' >&2
  exit 1
fi

export PATH="$TOOLS_ROOT/node/bin:$PATH"
export A2A_RUNTIME="${A2A_RUNTIME:-pi}"
export PI_BIN="${PI_BIN:-$TOOLS_ROOT/pi-runtime/node_modules/.bin/pi}"
export PI_MODEL="${PI_MODEL:-deepseek/deepseek-v4-flash}"

cd "$DEMO_ROOT"
exec python3 -u start_demo.py
