#!/usr/bin/env bash
# Run as root on the prepared ForumMM VPS. Optional first argument: ACME contact email.
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Запустите от root'; exit 1; }
DOMAIN=mm2026.ru
CONF=/etc/nginx/sites-available/forummm
[[ -f $CONF ]] || { echo 'Конфигурация forummm не найдена'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y certbot python3-certbot-nginx curl ca-certificates
BACKUP="$CONF.before-https-$(date -u +%Y%m%dT%H%M%SZ)-$$"
cp -p "$CONF" "$BACKUP"
# Preserve proxy rules and API limits; change only this site's hostnames.
python3 - "$CONF" <<'PY'
import re,sys
from pathlib import Path
p=Path(sys.argv[1]);s=p.read_text()
s,n=re.subn(r'(?m)^(\s*)server_name\s+[^;]+;',r'\1server_name mm2026.ru www.mm2026.ru;',s)
if not n:raise SystemExit('server_name не найден. Конфигурация не изменена.')
p.write_text(s)
PY
if ! nginx -t; then cp -p "$BACKUP" "$CONF"; exit 1; fi
systemctl reload nginx
CONTACT=(--register-unsafely-without-email)
if [[ -n ${1:-} ]]; then CONTACT=(--email "$1"); fi
if ! certbot --nginx --cert-name "$DOMAIN" -d "$DOMAIN" -d "www.$DOMAIN" --redirect --non-interactive --agree-tos --keep-until-expiring "${CONTACT[@]}"; then
    echo 'Выпуск сертификата не завершён. Возвращаю предыдущую конфигурацию HTTP.' >&2
    cp -p "$BACKUP" "$CONF"
    nginx -t && systemctl reload nginx
    exit 1
fi
nginx -t
systemctl reload nginx
# Validate the actual certificate and API locally with correct hostname/SNI.
# This bypasses only proxy routing for the loopback request, never TLS verification.
CHECK=$(mktemp)
trap 'rm -f "$CHECK"' EXIT
curl --noproxy "$DOMAIN" --resolve "$DOMAIN:443:127.0.0.1" --max-time 15 -fsS "https://$DOMAIN/api/state" -o "$CHECK"
python3 - "$CHECK" <<'PY'
import json,sys
with open(sys.argv[1]) as f:d=json.load(f)
assert len(d['data']['venues'])==6
print('Сертификат и API через HTTPS: OK')
PY
OVERRIDE=/etc/systemd/system/forummm.service.d/initial-http.conf
if [[ -f $OVERRIDE ]]; then
    if ! grep -qx 'Environment=FORUM_SECURE_COOKIE=0' "$OVERRIDE"; then
        echo 'Нестандартный HTTP override. HTTPS работает, но Secure cookie требует ручной проверки.' >&2; exit 1
    fi
    mv "$OVERRIDE" "$OVERRIDE.disabled-$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
systemctl daemon-reload
systemctl restart forummm
for attempt in {1..15}; do
    if curl --noproxy "$DOMAIN" --resolve "$DOMAIN:443:127.0.0.1" --max-time 5 -fsS -D "$CHECK" "https://$DOMAIN/api/state" -o /dev/null; then break; fi
    sleep 1
done
python3 - "$CHECK" <<'PY'
import sys
from http.cookies import SimpleCookie
cookies=SimpleCookie()
for line in open(sys.argv[1]):
    if line.lower().startswith('set-cookie:'):cookies.load(line.split(':',1)[1].strip())
assert 'forum_session' in cookies and cookies['forum_session']['secure'] and cookies['forum_session']['httponly'], 'Secure cookie не подтверждена'
print('Secure и HttpOnly cookie: OK')
PY
systemctl enable --now certbot.timer
certbot renew --dry-run
printf '\nHTTPS НАСТРОЕН: https://%s/ и https://www.%s/\n' "$DOMAIN" "$DOMAIN"
echo 'HTTP перенаправляется на HTTPS. Автообновление проверено.'
echo 'Если адрес не открывается извне, проверьте проброс/доступ TCP 443 к серверу.'
echo 'При переходе с IP на домен браузер создаст новую сессию: cookie разных адресов не переносятся.'
