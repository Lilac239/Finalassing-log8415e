#!/bin/bash
set -e

# Demo cleanup (lab): stop and delete the infrastructure + local temporary files.

PYTHON_BIN="python"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
  PYTHON_BIN="python3"
fi

echo "[CLEAN] Stopping and terminating AWS instances..."
"$PYTHON_BIN" scripts/cleanup.py

echo "[CLEAN] Removing local temporary files..."
rm -f scripts/manager_ip.txt || true
rm -f scripts/worker_ips.txt || true
rm -f scripts/cluster_info.json || true
rm -f scripts/manager_private_ip.txt || true
rm -f scripts/master_log_file.txt || true
rm -f scripts/master_log_pos.txt || true
rm -f scripts/gatekeeper_ip.txt || true
rm -f scripts/proxy_ip.txt || true
rm -f temp_status.txt || true
echo "[CLEAN] Done."