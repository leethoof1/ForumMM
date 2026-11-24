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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    g=sub.add_parser('generate');g.add_argument('--per-task',type=int,required=True)
    g.add_argument('--task',action='append');g.add_argument('--output',required=True)
    sub.add_parser('stats')
    args=parser.parse_args();server.initialize()
    if args.action=='generate':
        generate(args.per_task,args.task or [t['id'] for t in server.catalog()['tasks']],args.output)
    else:
        with server.connect() as db:
            for row in db.execute('SELECT batch,task,count(*) AS total,sum(used_by IS NOT NULL) AS used FROM redeem_codes GROUP BY batch,task'):
                print(f"{row['batch']} / {row['task']}: использовано {row['used']} из {row['total']}")

if __name__=='__main__':
    try: main()
    except (ValueError,FileExistsError) as e:
        print(str(e),file=sys.stderr);sys.exit(1)
