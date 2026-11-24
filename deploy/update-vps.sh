#!/usr/bin/env bash
# Run as root: bash update-vps.sh FULL_COMMIT /root/forum-codes.csv
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Нужен root'; exit 1; }
TARGET=${1:?Укажите полный SHA версии}
CSV=${2:?Укажите путь к CSV с кодами}
[[ $TARGET =~ ^[a-f0-9]{40}$ ]] || { echo 'Неверный SHA'; exit 1; }
[[ -f $CSV ]] || { echo "Файл кодов не найден: $CSV"; exit 1; }
APP=/opt/forummm
[[ -z $(git -C "$APP" status --porcelain) ]] || { echo 'В приложении есть изменения, обновление остановлено'; exit 1; }
# Fetch and validate before stopping the site.
git -C "$APP" fetch origin main
git -C "$APP" cat-file -e "$TARGET^{commit}"
OLD=$(git -C "$APP" rev-parse HEAD)
BACKUP=/var/lib/forummm/backup-$(date -u +%Y%m%dT%H%M%SZ)-$$.sqlite3
systemctl stop forummm
trap 'git -C "$APP" checkout --detach "$OLD"; systemctl start forummm; echo "Обновление остановлено. Предыдущая версия: $OLD. Бэкап БД: $BACKUP" >&2' ERR
python3 - "$BACKUP" <<'PY'
import sqlite3,sys,os
os.umask(0o077)
with sqlite3.connect('/var/lib/forummm/progress.sqlite3') as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
PY
git -C "$APP" checkout --detach "$TARGET"
# Copy the private print file, never put it in the repository or web root.
if [[ $(readlink -f "$CSV") != /var/lib/forummm/forum-codes.csv ]]; then
    if [[ -e /var/lib/forummm/forum-codes.csv ]]; then
        cmp "$CSV" /var/lib/forummm/forum-codes.csv || { echo 'Другой файл кодов уже существует. Нужна ручная проверка.'; false; }
    else
        install -o forummm -g forummm -m 600 "$CSV" /var/lib/forummm/forum-codes.csv
    fi
fi
runuser -u forummm -- env FORUM_STATE_DIR=/var/lib/forummm python3 "$APP/tools/manage_codes.py" import-pool /var/lib/forummm/forum-codes.csv
systemctl start forummm
python3 - <<'PY'
import urllib.request,json,time
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(15):
    try:
        d=json.load(opener.open('http://127.0.0.1:8090/api/state',timeout=3))
        assert len(d['data']['venues'])==6
        assert not any(e['id']=='volunteer-contest' for e in d['data']['events'])
        assert 'redeemed' in d
        break
    except (OSError,AssertionError):
        if i==14:raise
        time.sleep(1)
print('Новая программа и база кодов: OK')
PY
trap - ERR
echo "Обновлено. Бэкап БД: $BACKUP"
echo 'Выдача: организатор вводит код на телефоне участника. Закрытый код: /var/lib/forummm/delivery-code.txt (не присылайте в чат).'
echo 'Обязательно HTTPS до выдачи настоящего мерча. Баллы и история сохранены.'
