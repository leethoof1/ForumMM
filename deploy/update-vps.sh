#!/usr/bin/env bash
# Run as root: bash update-vps.sh FULL_COMMIT /root/forum-codes.csv
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Нужен root'; exit 1; }
TARGET=${1:?Укажите полный SHA версии}
CSV=${2:-/var/lib/forummm/forum-words.csv}
if [[ -z ${2:-} && ! -f $CSV ]]; then CSV=/var/lib/forummm/forum-codes.csv; fi
MODE=${3:-import}
RESET=${4:-}
PARTNERS=${5:-}
if [[ -n $PARTNERS && ! -f $PARTNERS ]]; then echo "Не найден файл партнёров: $PARTNERS"; exit 1; fi
[[ -z $RESET || $RESET == reset ]] || { echo 'Четвёртый аргумент: reset или пусто'; exit 1; }
[[ $MODE == import || $MODE == replace ]] || { echo 'Режим: import или replace'; exit 1; }
DEST=/var/lib/forummm/forum-codes.csv
COMMAND=import-pool
if [[ $(readlink -f "$CSV") == /var/lib/forummm/forum-words.csv ]]; then DEST=/var/lib/forummm/forum-words.csv; fi
if [[ $MODE == replace ]]; then DEST=/var/lib/forummm/forum-words.csv; COMMAND=replace-pool; fi
[[ $TARGET =~ ^[a-f0-9]{40}$ ]] || { echo 'Неверный SHA'; exit 1; }
[[ -f $CSV ]] || { echo "Файл кодов не найден: $CSV"; exit 1; }
# QR rendering is required on the presentation screen.
if ! python3 -c 'import qrcode' >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3-qrcode
fi
APP=/opt/forummm
[[ -z $(git -C "$APP" status --porcelain) ]] || { echo 'В приложении есть изменения, обновление остановлено'; exit 1; }
# Fetch and validate before stopping the site.
git -C "$APP" fetch origin main
git -C "$APP" cat-file -e "$TARGET^{commit}"
OLD=$(git -C "$APP" rev-parse HEAD)
BACKUP=/var/lib/forummm/backup-$(date -u +%Y%m%dT%H%M%SZ)-$$.sqlite3
systemctl stop forummm
rollback() {
    FAILURE=$?
    trap - ERR
    git -C "$APP" checkout --detach "$OLD"
    if [[ -n ${POLL_PROXY_BACKUP:-} && -f $POLL_PROXY_BACKUP ]]; then
        cp -p "$POLL_PROXY_BACKUP" /etc/nginx/sites-available/forummm
        nginx -t && systemctl reload nginx
    fi
    # start is a no-op if the failed new build is already running; restart is required.
    systemctl restart forummm
    echo "Обновление остановлено. Предыдущая версия: $OLD. Бэкап БД: $BACKUP" >&2
    exit "$FAILURE"
}
trap rollback ERR
python3 - "$BACKUP" <<'PY'
import sqlite3,sys,os
os.umask(0o077)
with sqlite3.connect('/var/lib/forummm/progress.sqlite3') as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
PY
git -C "$APP" checkout --detach "$TARGET"
# Copy the private print file, never put it in the repository or web root.
if [[ $(readlink -f "$CSV") != "$DEST" ]]; then
    if [[ -e "$DEST" ]]; then
        cmp "$CSV" "$DEST" || { echo 'Другой файл кодов уже существует. Нужна ручная проверка.'; false; }
    else
        install -o forummm -g forummm -m 600 "$CSV" "$DEST"
    fi
fi
runuser -u forummm -- env FORUM_STATE_DIR=/var/lib/forummm python3 "$APP/tools/manage_codes.py" "$COMMAND" "$DEST"
# Validate the staged private file before replacing the earlier partner list.
PARTNER_DEST=/var/lib/forummm/partner-words.csv
PARTNER_SOURCE=${PARTNERS:-$PARTNER_DEST}
if [[ -f $PARTNER_SOURCE ]]; then
    PARTNER_STAGE=/var/lib/forummm/.partner-import-$$.csv
    install -o forummm -g forummm -m 600 "$PARTNER_SOURCE" "$PARTNER_STAGE"
    runuser -u forummm -- env FORUM_STATE_DIR=/var/lib/forummm python3 "$APP/tools/manage_codes.py" import-partners "$PARTNER_STAGE"
    if [[ -f $PARTNER_DEST ]] && ! cmp -s "$PARTNER_SOURCE" "$PARTNER_DEST"; then
        cp -p "$PARTNER_DEST" "$PARTNER_DEST.before-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    fi
    install -o forummm -g forummm -m 600 "$PARTNER_STAGE" "$PARTNER_DEST"
    rm "$PARTNER_STAGE"
fi
# The loopback backend trusts X-Real-IP only from local nginx.
grep -Eq 'proxy_set_header[[:space:]]+X-Real-IP[[:space:]]+\$remote_addr;' /etc/nginx/sites-available/forummm || { echo 'Нужен X-Real-IP от nginx'; false; }
install -d -m 755 /etc/systemd/system/forummm.service.d
if [[ ! -f /etc/systemd/system/forummm.service.d/ip-guard.conf ]]; then
    printf '[Service]\nEnvironment=FORUM_TRUST_PROXY=1\nEnvironment=FORUM_IP_GUARD=1\n' > /etc/systemd/system/forummm.service.d/ip-guard.conf
fi
grep -qx 'Environment=FORUM_TRUST_PROXY=1' /etc/systemd/system/forummm.service.d/ip-guard.conf || { echo 'Проверьте доверенный proxy в ip-guard.conf'; false; }
if [[ $RESET == reset ]]; then
    runuser -u forummm -- env FORUM_STATE_DIR=/var/lib/forummm python3 "$APP/tools/reset_progress.py" --confirm RESET-PROGRESS
fi
POLL_PROXY_BACKUP=/etc/nginx/sites-available/forummm.before-poll-$(date -u +%Y%m%dT%H%M%SZ)-$$
cp -p /etc/nginx/sites-available/forummm "$POLL_PROXY_BACKUP"
python3 "$APP/tools/configure_poll_proxy.py" /etc/nginx/sites-available/forummm
if ! nginx -t; then cp -p "$POLL_PROXY_BACKUP" /etc/nginx/sites-available/forummm; false; fi
systemctl daemon-reload
systemctl start forummm
systemctl reload nginx
python3 "$APP/tools/check_readiness.py"
trap - ERR
echo "Обновлено. Бэкап БД: $BACKUP"
echo 'Выдача: организатор вводит код на телефоне участника. Закрытый код: /var/lib/forummm/delivery-code.txt (не присылайте в чат).'
echo 'Закрытые ссылки голосования: /var/lib/forummm/poll-links.json — не присылайте их в чат.'
echo 'Обязательно HTTPS до выдачи настоящего мерча. Баллы и история сохранены.'

python3 - <<'PY'
import json
from pathlib import Path
links=json.loads(Path('/var/lib/forummm/poll-links.json').read_text())
print('Участникам: '+links['vote'])
print('На экран: '+links['results'])
print('Ведущему (не публиковать): '+links['control'])
PY
