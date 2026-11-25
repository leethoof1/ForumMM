"""Register one additional word from stdin without resetting any existing counters."""
import argparse
from pathlib import Path
import secrets
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--uses',type=int,required=True)
    args=parser.parse_args()
    word=sys.stdin.read().strip()
    if not word or len(word)>100 or not 1<=args.uses<=10000:
        parser.error('Нужно непустое слово до 100 символов и лимит 1–10000')
    sys.path.insert(0,str(Path(args.root).resolve()))
    import server
    server.initialize()
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        digest=server.code_digest(word)
        old=db.execute('SELECT task,max_uses,active FROM redeem_codes WHERE digest=?',(digest,)).fetchone()
        if old:
            if old['task']!='*' or old['max_uses']!=args.uses or not old['active']:
                raise ValueError('Слово уже есть с другими настройками. Изменения не внесены.')
            print('Слово уже зарегистрировано. Использования не сбрасывались.')
        else:
            db.execute("INSERT INTO redeem_codes(digest,task,batch,created,max_uses) VALUES(?,'*',?,?,?)",
                       (digest,'extra-'+secrets.token_hex(8),int(time.time()),args.uses))
            print(f'Дополнительное слово добавлено. Общий лимит: {args.uses}.')

if __name__=='__main__':
    try: main()
    except ValueError as e: print(str(e),file=sys.stderr);sys.exit(1)
