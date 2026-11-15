"""Forum demo. Python 3.12+, no runtime dependencies."""
import argparse, hmac, json, os, secrets, sqlite3, time
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
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0));
        CREATE TABLE IF NOT EXISTS completed(session TEXT REFERENCES sessions(id),task TEXT,PRIMARY KEY(session,task));
        CREATE TABLE IF NOT EXISTS exchanges(session TEXT REFERENCES sessions(id),request TEXT,product TEXT,name TEXT,price INTEGER,created INTEGER,PRIMARY KEY(session,request));
        CREATE TABLE IF NOT EXISTS attempts(session TEXT PRIMARY KEY,window INTEGER,count INTEGER);''')
    if not (STATE/'codes.json').exists():
        words=['ДЕМО-'+secrets.token_hex(3).upper() for _ in catalog()['tasks']]
        fd=os.open(STATE/'codes.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: json.dump(dict(zip([t['id'] for t in catalog()['tasks']],words)),f,ensure_ascii=False,indent=2)

def progress(db,sid):
    return dict(balance=db.execute('SELECT balance FROM sessions WHERE id=?',(sid,)).fetchone()[0],completed=[r[0] for r in db.execute('SELECT task FROM completed WHERE session=?',(sid,))],history=[dict(r) for r in db.execute('SELECT request,product,name,price,created FROM exchanges WHERE session=? ORDER BY created DESC,rowid DESC',(sid,))])

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
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/logo.png':'logo.png'}
        file=ROOT/'public'/files.get(path,'missing')
        if not file.is_file(): self.send_error(404); return
        raw=file.read_bytes(); self.send_response(200); self.headers_common()
        self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','png':'image/png'}[file.suffix[1:]])
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.headers.get('X-Forum-Request')!='1': self.reply(403,{'error':'Недопустимый запрос'}); return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<4096: raise ValueError()
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict): raise ValueError()
        except (ValueError,TypeError): self.reply(400,{'error':'Некорректный запрос'}); return
        with connect() as db:
            sid=self.session(db)
            db.execute('BEGIN IMMEDIATE')
            data=catalog(); error=None; status=200
            if self.path=='/api/complete':
                task=next((x for x in data['tasks'] if x['id']==body.get('task')),None)
                if not task: error='Задание не найдено'; status=404
                elif not db.execute('SELECT 1 FROM completed WHERE session=? AND task=?',(sid,task['id'])).fetchone():
                    now=int(time.time()); row=db.execute('SELECT window,count FROM attempts WHERE session=?',(sid,)).fetchone()
                    count=row['count'] if row and now-row['window']<60 else 0
                    window=row['window'] if count else now
                    db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(sid,window,count+1))
                    codes=json.loads((STATE/'codes.json').read_text())
                    supplied=body.get('code','')
                    valid=isinstance(supplied,str) and task['id'] in codes and hmac.compare_digest(supplied.strip().casefold().encode(),str(codes[task['id']]).strip().casefold().encode())
                    if count>=20: error='Слишком много попыток. Повтори через минуту.'; status=429
                    elif not valid: error='Проверь написание кодового слова и попробуй ещё раз'; status=400
                    else:
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
                        db.execute('INSERT INTO exchanges VALUES(?,?,?,?,?,?)',(sid,key,product['id'],product['name'],product['price'],int(time.time())))
            else: error='Не найдено'; status=404
            db.commit(); result=progress(db,sid)
            if error: result['error']=error
            self.reply(status,result,sid)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8000); parser.add_argument('--host',default='0.0.0.0'); args=parser.parse_args()
    initialize(); print(f'ForumMM listening on port {args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
