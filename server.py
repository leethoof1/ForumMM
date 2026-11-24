"""Forum demo. Python 3.12+, no runtime dependencies."""
import argparse, hashlib, hmac, json, os, secrets, sqlite3, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
STATE = Path(os.environ.get('FORUM_STATE_DIR', str(Path.home()/'.local/share/forummm')))

def catalog():
    return json.loads((ROOT/'data.json').read_text())

def connect():
    db = sqlite3.connect(STATE/'progress.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0));
        CREATE TABLE IF NOT EXISTS completed(session TEXT REFERENCES sessions(id),task TEXT,PRIMARY KEY(session,task));
        CREATE TABLE IF NOT EXISTS exchanges(session TEXT REFERENCES sessions(id),request TEXT,product TEXT,name TEXT,price INTEGER,created INTEGER,PRIMARY KEY(session,request));
        CREATE TABLE IF NOT EXISTS attempts(session TEXT PRIMARY KEY,window INTEGER,count INTEGER);''')
        db.execute("""CREATE TABLE IF NOT EXISTS redeem_codes(
            digest TEXT PRIMARY KEY, task TEXT NOT NULL, batch TEXT NOT NULL,
            created INTEGER NOT NULL, used_by TEXT REFERENCES sessions(id), used_at INTEGER,
            CHECK((used_by IS NULL) = (used_at IS NULL)))""")
        db.execute('CREATE INDEX IF NOT EXISTS codes_batch ON redeem_codes(batch)')
        columns={r['name'] for r in db.execute('PRAGMA table_info(redeem_codes)')}
        if 'max_uses' not in columns:
            db.execute('ALTER TABLE redeem_codes ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 1 CHECK(max_uses>0)')
        db.execute("""CREATE TABLE IF NOT EXISTS code_uses(
            digest TEXT REFERENCES redeem_codes(digest), session TEXT REFERENCES sessions(id),
            created INTEGER NOT NULL, PRIMARY KEY(digest,session))""")
        db.execute('INSERT OR IGNORE INTO code_uses SELECT digest,used_by,used_at FROM redeem_codes WHERE used_by IS NOT NULL')

    with connect() as db:
        columns={r['name'] for r in db.execute('PRAGMA table_info(exchanges)')}
        if 'receipt' not in columns: db.execute('ALTER TABLE exchanges ADD COLUMN receipt TEXT')
        if 'fulfilled_at' not in columns: db.execute('ALTER TABLE exchanges ADD COLUMN fulfilled_at INTEGER')
        for row in db.execute('SELECT rowid FROM exchanges WHERE receipt IS NULL').fetchall():
            db.execute('UPDATE exchanges SET receipt=? WHERE rowid=?',(secrets.token_hex(8).upper(),row['rowid']))
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS exchange_receipt ON exchanges(receipt)')
    keyfile=STATE/'staff-key.txt'
    if not keyfile.exists():
        try:
            fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f: f.write(secrets.token_urlsafe(32))
        except FileExistsError: pass
    # Legacy shared words deliberately remain disabled. Existing progress is retained.

def code_digest(code):
    return hashlib.sha256(code.strip().casefold().encode('utf-8')).hexdigest()


def progress(db,sid):
    return dict(balance=db.execute('SELECT balance FROM sessions WHERE id=?',(sid,)).fetchone()[0],completed=[r[0] for r in db.execute('SELECT task FROM completed WHERE session=?',(sid,))],redeemed=db.execute('SELECT count(*) FROM code_uses WHERE session=?',(sid,)).fetchone()[0],history=[dict(r) for r in db.execute('SELECT request,product,name,price,created,receipt,fulfilled_at FROM exchanges WHERE session=? ORDER BY created DESC,rowid DESC',(sid,))])

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass # Never log request bodies or code words.
    def reply(self,status,value,cookie=None):
        raw=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status); self.headers_common()
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        if cookie: self.send_header('Set-Cookie',f'forum_session={cookie}; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000'+ ('; Secure' if os.environ.get('FORUM_SECURE_COOKIE')=='1' else ''))
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
    def session(self,db):
        c=SimpleCookie()
        try: c.load(self.headers.get('Cookie',''))
        except Exception: pass
        sid=c['forum_session'].value if 'forum_session' in c else ''
        if len(sid)!=64 or not db.execute('SELECT 1 FROM sessions WHERE id=?',(sid,)).fetchone():
            sid=secrets.token_hex(32); db.execute('INSERT INTO sessions(id) VALUES(?)',(sid,)); db.commit()
        return sid
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/api/state':
            with connect() as db:
                sid=self.session(db); self.reply(200,dict(data=catalog(),**progress(db,sid)),sid)
            return
        files={'/':'index.html','/staff':'staff.html','/staff.js':'staff.js','/app.js':'app.js','/style.css':'style.css','/logo.png':'logo.png','/logo.svg':'logo.svg','/district.svg':'district.svg'}
        file=ROOT/'public'/files.get(path,'missing')
        if not file.is_file(): self.send_error(404); return
        raw=file.read_bytes(); self.send_response(200); self.headers_common()
        self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','png':'image/png','svg':'image/svg+xml'}[file.suffix[1:]])
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.headers.get('X-Forum-Request')!='1': self.reply(403,{'error':'Недопустимый запрос'}); return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<4096: raise ValueError()
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict): raise ValueError()
        except (ValueError,TypeError): self.reply(400,{'error':'Некорректный запрос'}); return
        if self.path in ['/api/staff/lookup','/api/staff/fulfill']:
            key=self.headers.get('X-Staff-Key','')
            if not hmac.compare_digest(key.encode(),(STATE/'staff-key.txt').read_text().strip().encode()):
                self.reply(403,{'error':'Неверный ключ организатора'});return
            receipt=body.get('receipt','')
            if not isinstance(receipt,str): self.reply(400,{'error':'Неверный номер'});return
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT name,price,created,receipt,fulfilled_at FROM exchanges WHERE receipt=?',(receipt.strip().upper(),)).fetchone()
                if not row: self.reply(404,{'error':'Обмен не найден'});return
                already=bool(row['fulfilled_at'])
                if self.path.endswith('/fulfill') and not already:
                    db.execute('UPDATE exchanges SET fulfilled_at=? WHERE receipt=? AND fulfilled_at IS NULL',(int(time.time()),row['receipt']))
                db.commit()
                row=db.execute('SELECT name,price,created,receipt,fulfilled_at FROM exchanges WHERE receipt=?',(row['receipt'],)).fetchone()
                self.reply(200,dict(exchange=dict(row),already_fulfilled=already));return
        with connect() as db:
            sid=self.session(db)
            db.execute('BEGIN IMMEDIATE')
            data=catalog(); error=None; status=200
            if self.path=='/api/redeem':
                supplied=body.get('code','')
                row=db.execute('SELECT window,count FROM attempts WHERE session=?',(sid,)).fetchone()
                now=int(time.time()); count=row['count'] if row and now-row['window']<60 else 0
                db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(sid,row['window'] if count else now,count+1))
                record=db.execute("SELECT * FROM redeem_codes WHERE digest=? AND task='*'",
                    (code_digest(supplied),)).fetchone() if isinstance(supplied,str) and 0<len(supplied)<=100 else None
                if count>=20: error='Слишком много попыток. Повтори через минуту.';status=429
                elif not record: error='Код не найден. Проверь написание.';status=400
                elif db.execute('SELECT 1 FROM code_uses WHERE digest=? AND session=?',(record['digest'],sid)).fetchone():
                    pass # Idempotent retry: already credited to this browser.
                elif db.execute('SELECT count(*) FROM code_uses WHERE digest=?',(record['digest'],)).fetchone()[0]>=record['max_uses']:
                    error='Лимит использований этого кода исчерпан.';status=409
                else:
                    db.execute('INSERT INTO code_uses VALUES(?,?,?)',(record['digest'],sid,now))
                    db.execute('UPDATE sessions SET balance=balance+1 WHERE id=?',(sid,))
            elif self.path=='/api/complete':
                task=next((x for x in data['tasks'] if x['id']==body.get('task')),None)
                if not task: error='Задание не найдено'; status=404
                elif not db.execute('SELECT 1 FROM completed WHERE session=? AND task=?',(sid,task['id'])).fetchone():
                    now=int(time.time()); row=db.execute('SELECT window,count FROM attempts WHERE session=?',(sid,)).fetchone()
                    count=row['count'] if row and now-row['window']<60 else 0
                    window=row['window'] if count else now
                    db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(sid,window,count+1))
                    supplied=body.get('code','')
                    record=db.execute('SELECT * FROM redeem_codes WHERE digest=?',
                        (code_digest(supplied),)).fetchone() if isinstance(supplied,str) and 0<len(supplied)<=100 else None
                    if count>=20: error='Слишком много попыток. Повтори через минуту.'; status=429
                    elif not record or record['task']!=task['id']:
                        error='Проверь код и задание. Такой код не найден для этого задания.'; status=400
                    elif record['used_by'] is not None:
                        error='Этот код уже использован. Получи новый код у организатора.'; status=409
                    else:
                        db.execute('UPDATE redeem_codes SET used_by=?,used_at=? WHERE digest=? AND used_by IS NULL',
                            (sid,now,record['digest']))
                        db.execute('INSERT INTO code_uses VALUES(?,?,?)',(record['digest'],sid,now))
                        db.execute('INSERT INTO completed VALUES(?,?)',(sid,task['id']))
                        db.execute('UPDATE sessions SET balance=balance+? WHERE id=?',(task['reward'],sid))
            elif self.path=='/api/exchange':
                key=body.get('request'); product=next((x for x in data['products'] if x['id']==body.get('product')),None)
                previous=db.execute('SELECT product FROM exchanges WHERE session=? AND request=?',(sid,key)).fetchone() if isinstance(key,str) else None
                if not isinstance(key,str) or not 8<=len(key)<=128: error='Неверный идентификатор обмена'; status=400
                elif previous:
                    if previous['product']!=body.get('product'): error='Этот запрос уже использован'; status=409
                elif not product: error='Товар не найден'; status=404
                else:
                    balance=progress(db,sid)['balance']
                    if balance<product['price']: error=f"Нужно ещё {product['price']-balance} балл(ов)"; status=409
                    else:
                        db.execute('UPDATE sessions SET balance=balance-? WHERE id=?',(product['price'],sid))
                        db.execute('INSERT INTO exchanges(session,request,product,name,price,created,receipt) VALUES(?,?,?,?,?,?,?)',(sid,key,product['id'],product['name'],product['price'],int(time.time()),secrets.token_hex(8).upper()))
            else: error='Не найдено'; status=404
            db.commit(); result=progress(db,sid)
            if error: result['error']=error
            self.reply(status,result,sid)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8090); parser.add_argument('--host',default='0.0.0.0'); args=parser.parse_args()
    initialize(); print(f'ForumMM listening on port {args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
