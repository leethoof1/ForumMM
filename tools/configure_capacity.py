"""Small nginx capacity changes; do not replace TLS or API write protections."""
from pathlib import Path
import re,sys
READ_ZONE='limit_req_zone $binary_remote_addr zone=forum_reads:10m rate=100r/s;\n'
LOCATIONS='''
    # FORUM_CAPACITY_LOCATIONS
    location = /api/state {
        limit_req zone=forum_reads burst=1000 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location ~ ^/(app\\.js|poll\\.js|staff\\.js|style\\.css|logo\\.svg|district\\.svg|logo\\.png)$ {
        root /opt/forummm/public;
        try_files $uri =404;
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
'''
def site(text):
    if 'FORUM_CAPACITY_LOCATIONS' in text:return text
    if 'zone=forum_reads' in text or re.search(r'location\s*=\s*/api/state',text):
        raise ValueError('Уже есть нестандартная настройка чтения /api/state')
    changed,n=re.subn(r'(?m)^(\s*server\s*\{)',lambda m:m.group(1)+LOCATIONS,text)
    if not n:raise ValueError('server block не найден')
    return READ_ZONE+changed

def global_config(text):
    found=False
    def connections(m):
        nonlocal found
        found=True;return 'worker_connections '+str(max(4096,int(m.group(1))))+';'
    text=re.sub(r'worker_connections\s+(\d+)\s*;',connections,text)
    if not found:raise ValueError('worker_connections не найден')
    if re.search(r'(?m)^\s*worker_rlimit_nofile\s+',text):
        text=re.sub(r'(?m)^(\s*worker_rlimit_nofile\s+)(\d+)(\s*;)',lambda m:m.group(1)+str(max(16384,int(m.group(2))))+m.group(3),text)
    else:text='worker_rlimit_nofile 16384;\n'+text
    return text

if __name__=='__main__':
    path=Path(sys.argv[1]);global_path=Path(sys.argv[2])
    a=site(path.read_text());b=global_config(global_path.read_text())
    path.write_text(a);global_path.write_text(b)
    print('Чтение отделено от списаний; статика nginx; worker_connections не ниже 4096.')
