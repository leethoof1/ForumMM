"""Offline code administration. Run on the server, never expose as a public API."""
import argparse
import csv
import os
from pathlib import Path
import secrets
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


def generate(count, task_ids, output):
    if count < 1 or count > 10000:
        raise ValueError('Количество на задание: 1–10000')
    tasks={t['id']:t for t in server.catalog()['tasks']}
    if any(t not in tasks for t in task_ids):
        raise ValueError('Неизвестное задание')
    output=Path(output).resolve()
    try:
        output.relative_to(server.ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError('CSV со словами должен находиться ВНЕ репозитория')
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    batch=secrets.token_hex(8)
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Exclusive creation: never overwrite an earlier print list.
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w',newline='',encoding='utf-8-sig') as f:
                writer=csv.writer(f);writer.writerow(['batch','task_id','task','code'])
                for task in task_ids:
                    for _ in range(count):
                        # 80 random bits; normalized matching only ignores case and edge whitespace.
                        raw=secrets.token_hex(10).upper()
                        code='-'.join(raw[i:i+5] for i in range(0,len(raw),5))
                        db.execute('INSERT INTO redeem_codes(digest,task,batch,created) VALUES(?,?,?,?)',
                            (server.code_digest(code),task,batch,int(time.time())))
                        writer.writerow([batch,task,tasks[task]['title'],code])
                f.flush();os.fsync(f.fileno())
            db.commit()
        except BaseException:
            db.rollback();output.unlink(missing_ok=True);raise
    print(f'Партия {batch}: создано {count*len(task_ids)} кодов. CSV: {output}')


def pool(output):
    output=Path(output).resolve()
    if output.is_relative_to(server.ROOT.resolve()):
        raise ValueError('CSV должен находиться вне репозитория')
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    batch=secrets.token_hex(8)
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['number','code','max_uses','batch'])
                i=0
                for amount,limit in [(5,600),(15,100),(80,10)]:
                    for _ in range(amount):
                        i+=1;code='MM-'+secrets.token_hex(8).upper()
                        db.execute("INSERT INTO redeem_codes(digest,task,batch,created,max_uses) VALUES(?,'*',?,?,?)",(server.code_digest(code),batch,int(time.time()),limit))
                        w.writerow([i,code,limit,batch])
                f.flush();os.fsync(f.fileno())
            db.commit()
        except BaseException:
            db.rollback();output.unlink(missing_ok=True);raise
    print(f'Партия {batch}: 100 кодов, 5300 начислений. CSV: {output}')

def import_pool(source, replace=False):
    with Path(source).open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    if len(rows)!=100 or len({server.code_digest(r['code']) for r in rows})!=100:
        raise ValueError('Ожидается 100 уникальных кодов')
    if len({r['batch'] for r in rows})!=1 or any(not r['code'].strip() or len(r['code'])>100 for r in rows):
        raise ValueError('Ожидается одна партия с непустыми кодами до 100 символов')
    from collections import Counter
    if Counter(int(r['max_uses']) for r in rows)!={600:5,100:15,10:80}:
        raise ValueError('Ожидаются лимиты: 5×600, 15×100, 80×10')
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for r in rows:
            digest=server.code_digest(r['code']);old=db.execute('SELECT * FROM redeem_codes WHERE digest=?',(digest,)).fetchone()
            if old:
                if old['task']!='*' or old['batch']!=r['batch'] or old['max_uses']!=int(r['max_uses']):
                    raise ValueError('Конфликт кода с существующей партией')
            else: db.execute("INSERT INTO redeem_codes(digest,task,batch,created,max_uses) VALUES(?,'*',?,?,?)",(digest,r['batch'],int(time.time()),int(r['max_uses'])))
        if replace:
            db.execute("UPDATE redeem_codes SET active=0 WHERE batch<>?",(rows[0]['batch'],))
            db.execute("UPDATE redeem_codes SET active=1 WHERE task='*' AND batch=?",(rows[0]['batch'],))
    print('100 кодов импортированы. Повторный импорт сохраняет погашения.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    g=sub.add_parser('generate');g.add_argument('--per-task',type=int,required=True)
    g.add_argument('--task',action='append');g.add_argument('--output',required=True)
    g=sub.add_parser('pool');g.add_argument('--output',required=True)
    g=sub.add_parser('import-pool');g.add_argument('source')
    g=sub.add_parser('replace-pool');g.add_argument('source')
    sub.add_parser('stats')
    args=parser.parse_args();server.initialize()
    if args.action=='generate':
        generate(args.per_task,args.task or [t['id'] for t in server.catalog()['tasks']],args.output)
    elif args.action=='pool': pool(args.output)
    elif args.action=='import-pool': import_pool(args.source)
    elif args.action=='replace-pool': import_pool(args.source,replace=True)
    else:
        with server.connect() as db:
            for row in db.execute('SELECT batch,task,count(*) AS total,(SELECT count(*) FROM code_uses u JOIN redeem_codes c ON c.digest=u.digest WHERE c.batch=redeem_codes.batch AND c.task=redeem_codes.task) AS used FROM redeem_codes GROUP BY batch,task'):
                print(f"{row['batch']} / {row['task']}: использовано {row['used']} из {row['total']}")

if __name__=='__main__':
    try: main()
    except (ValueError,FileExistsError) as e:
        print(str(e),file=sys.stderr);sys.exit(1)
