"""Offline reset of forum tests. Stop the service first; retains code words and poll votes."""
import argparse
import os
from pathlib import Path
import secrets
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

def reset():
    backup=server.STATE/('before-reset-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+secrets.token_hex(3)+'.sqlite3')
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    with server.connect() as db, server.sqlite3.connect(backup) as target:
        db.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for table in ['exchanges','completed','code_uses','ip_codes','session_products','ip_products','attempts','delivery_attempts','ip_attempts']:
            db.execute('DELETE FROM '+table)
        db.execute('UPDATE sessions SET balance=0')
        db.execute('UPDATE redeem_codes SET used_by=NULL,used_at=NULL')
    print('Прогресс, обмены, резервы, IP-ограничения и расход кодов обнулены.')
    print('Кодовые слова, их лимиты, активные партии и голоса опроса сохранены.')
    print('Резервная копия:',backup)
    return backup

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--confirm',required=True);args=p.parse_args()
    if args.confirm!='RESET-PROGRESS':p.error('Нужно явное --confirm RESET-PROGRESS')
    server.initialize();reset()
