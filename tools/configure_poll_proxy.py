"""Add a separate polling limit without replacing existing TLS configuration."""
from pathlib import Path
import re
import sys
ZONE='limit_req_zone $binary_remote_addr zone=forum_poll:10m rate=250r/s;\n'
LOCATION='''
    # FORUM_POLL_LOCATION
    location ^~ /api/poll/ {
        limit_req zone=forum_poll burst=1000 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
'''
def configure(path):
    path=Path(path);text=path.read_text()
    if 'FORUM_POLL_LOCATION' in text:return
    if '/api/poll/' in text or 'zone=forum_poll' in text:
        raise ValueError('Уже есть другая конфигурация голосования; нужна ручная проверка')
    patched,n=re.subn(r'(?m)^(\s*server\s*\{)',lambda m:m.group(1)+LOCATION,text)
    if not n:raise ValueError('server block не найден')
    path.write_text(ZONE+patched)
if __name__=='__main__':configure(sys.argv[1])
