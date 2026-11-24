#!/usr/bin/env bash
# First installation on a dedicated Ubuntu VPS. HTTP is for initial testing only.
set -Eeuo pipefail
trap 'echo "Установка остановлена на строке $LINENO. Пришлите ошибку выше; пароли не нужны." >&2' ERR
if [[ $(id -u) != 0 ]]; then echo 'Запустите от root.' >&2; exit 1; fi
FORUM_IP=${1:-87.228.63.164}
if [[ ! $FORUM_IP =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then echo 'Укажите IPv4 сервера.' >&2; exit 1; fi
APP=/opt/forummm
COMMIT=23a80ac8c3e6f3acf0a01542c9db0aa612992b9a
# Do not take over a server already hosting other sites.
if [[ -d /etc/nginx/sites-enabled ]]; then
  while IFS= read -r -d '' site; do
    case $(basename "$site") in
      default|forummm) ;;
      *) echo "Найден другой сайт nginx: $site. Нужна ручная настройка." >&2; exit 1;;
    esac
  done < <(find /etc/nginx/sites-enabled -mindepth 1 -maxdepth 1 -print0)
fi
if [[ -e "$APP" ]]; then
  if [[ ! -d "$APP/.git" ]] || [[ $(git -C "$APP" rev-parse HEAD) != "$COMMIT" ]] || [[ -n $(git -C "$APP" status --porcelain) ]]; then
    echo "В $APP уже есть другая версия или локальные файлы. Ничего не перезаписываю." >&2; exit 1
  fi
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 git nginx ca-certificates
if [[ ! -e "$APP" ]]; then
  git clone https://github.com/leethoof1/ForumMM.git "$APP"
  git -C "$APP" checkout --detach "$COMMIT"
fi
if ! id forummm >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/forummm --shell /usr/sbin/nologin forummm
fi
install -d -o forummm -g forummm -m 700 /var/lib/forummm
# Keep application files root-owned, only the database directory is writable by the service.
install -m 644 "$APP/deploy/forummm.service" /etc/systemd/system/forummm.service
install -d -m 755 /etc/systemd/system/forummm.service.d
printf '[Service]\nEnvironment=FORUM_SECURE_COOKIE=0\n' > /etc/systemd/system/forummm.service.d/initial-http.conf
# Initial TEST codes only. Re-running preserves the database and existing print list.
if [[ ! -f /var/lib/forummm/initial-test-codes.csv ]]; then
  runuser -u forummm -- env FORUM_STATE_DIR=/var/lib/forummm python3 "$APP/tools/manage_codes.py" generate --per-task 2 --output /var/lib/forummm/initial-test-codes.csv
fi
systemctl daemon-reload
systemctl enable --now forummm
systemctl restart forummm
sed "s/forum.example.org/$FORUM_IP/" "$APP/deploy/nginx.conf" > /etc/nginx/sites-available/forummm
# Keep a copy of nginx's default site and its link; only disable it if enabled.
if [[ -e /etc/nginx/sites-enabled/default || -L /etc/nginx/sites-enabled/default ]]; then
  install -d -m 755 /etc/nginx/sites-disabled
  mv -n /etc/nginx/sites-enabled/default /etc/nginx/sites-disabled/default
  if [[ -e /etc/nginx/sites-enabled/default || -L /etc/nginx/sites-enabled/default ]]; then
    echo 'Не удалось безопасно отключить default nginx. Нужна ручная проверка.' >&2; exit 1
  fi
fi
if [[ -e /etc/nginx/sites-enabled/forummm || -L /etc/nginx/sites-enabled/forummm ]]; then
  if [[ $(readlink -f /etc/nginx/sites-enabled/forummm) != /etc/nginx/sites-available/forummm ]]; then
    echo 'Ссылка forummm указывает на другой сайт; нужна ручная проверка.' >&2; exit 1
  fi
else
  ln -s /etc/nginx/sites-available/forummm /etc/nginx/sites-enabled/forummm
fi
nginx -t
systemctl enable --now nginx
systemctl reload nginx
# Check behavior through nginx, not just that a process exists.
python3 - "$FORUM_IP" <<'PY'
import json, sys, time, urllib.request
ip=sys.argv[1]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(20):
    try:
        req=urllib.request.Request('http://127.0.0.1/api/state',headers={'Host':ip})
        with opener.open(req,timeout=3) as response:
            data=json.load(response)
            assert len(data['data']['tasks'])==10
            assert data['balance']==0
            assert 'HttpOnly' in response.headers['Set-Cookie']
        break
    except (OSError,AssertionError):
        if attempt==19: raise
        time.sleep(1)
print('Проверка API через nginx: OK')
PY
printf '\nСАЙТ ЗАПУЩЕН ЛОКАЛЬНО НА СЕРВЕРЕ. Откройте: http://%s/\n' "$FORUM_IP"
echo 'Для доступа с телефона администратор должен разрешить/пробросить TCP 80 к этому серверу.'
echo '20 тестовых одноразовых кодов: /var/lib/forummm/initial-test-codes.csv (не публиковать).'
echo 'Это первоначальная проверка по HTTP. До форума необходимо настроить HTTPS и убрать initial-http.conf.'
