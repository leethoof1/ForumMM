#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Запустите от root на сервере форума'; exit 1; }
if ! python3 -c 'import aiohttp' >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3-aiohttp
fi
ulimit -n 8192
umask 077
python3 /opt/forummm/tools/load_capacity.py --output "/var/lib/forummm/load-report-$(date -u +%Y%m%dT%H%M%SZ).json"
