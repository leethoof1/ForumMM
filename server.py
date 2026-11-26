"""Forum application. Python 3.12+, no runtime dependencies."""
import polls
from concurrent.futures import ThreadPoolExecutor
import ipaddress
from datetime import datetime, timezone
import argparse, hashlib, hmac, json, os, secrets, sqlite3, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
STATE = Path(os.environ.get('FORUM_STATE_DIR', str(Path.home()/'.local/share/forummm')))

BUILD_ID=hashlib.sha256(Path(__file__).read_bytes()+(ROOT/'polls.py').read_bytes()).hexdigest()

def catalog():
    return json.loads(Path(os.environ.get('FORUM_CATALOG_PATH',str(ROOT/'data.json'))).read_text())

def public_catalog():
    data=catalog()
    for product in data['products']:
        product.pop('stock',None);product.pop('legacy_products',None)
    return data

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
        CREATE TABLE IF NOT EXISTS attempts(session TEXT PRIMARY KEY,window INTEGER,count INTEGER);
        CREATE TABLE IF NOT EXISTS delivery_attempts(session TEXT PRIMARY KEY,window INTEGER,count INTEGER);
        CREATE TABLE IF NOT EXISTS ip_codes(ip TEXT,digest TEXT,session TEXT,created INTEGER,PRIMARY KEY(ip,digest));
        CREATE TABLE IF NOT EXISTS session_products(session TEXT,product TEXT,PRIMARY KEY(session,product));
        CREATE TABLE IF NOT EXISTS ip_products(ip TEXT,product TEXT,session TEXT,PRIMARY KEY(ip,product));
        CREATE TABLE IF NOT EXISTS ip_attempts(ip TEXT PRIMARY KEY,window INTEGER,count INTEGER);''')
        db.execute("""CREATE TABLE IF NOT EXISTS redeem_codes(
            digest TEXT PRIMARY KEY, task TEXT NOT NULL, batch TEXT NOT NULL,
            created INTEGER NOT NULL, used_by TEXT REFERENCES sessions(id), used_at INTEGER,
            CHECK((used_by IS NULL) = (used_at IS NULL)))""")
        db.execute('CREATE INDEX IF NOT EXISTS codes_batch ON redeem_codes(batch)')
        columns={r['name'] for r in db.execute('PRAGMA table_info(redeem_codes)')}
        if 'max_uses' not in columns:
            db.execute('ALTER TABLE redeem_codes ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 1 CHECK(max_uses>0)')
        db.execute('UPDATE redeem_codes SET max_uses=5 WHERE max_uses=10')
        if 'active' not in columns:
            db.execute('ALTER TABLE redeem_codes ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))')
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
        db.execute('CREATE INDEX IF NOT EXISTS exchange_stock ON exchanges(product,fulfilled_at)')
        db.execute('CREATE INDEX IF NOT EXISTS code_uses_session ON code_uses(session)')
        db.execute('INSERT OR IGNORE INTO session_products SELECT session,product FROM exchanges')
    keyfile=STATE/'staff-key.txt'
    if not keyfile.exists():
        try:
            fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f: f.write(secrets.token_urlsafe(32))
        except FileExistsError: pass
    deliveryfile=STATE/'delivery-code.txt'
    if not deliveryfile.exists():
        try:
            fd=os.open(deliveryfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f: f.write('ВЫДАНО-'+secrets.token_hex(4).upper())
        except FileExistsError: pass
    ipkey=STATE/'ip-key.txt'
    if not ipkey.exists():
        try:
            fd=os.open(ipkey,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
        except FileExistsError:pass
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        polls.initialize(db,STATE)
    # Legacy shared words deliberately remain disabled. Existing progress is retained.

def code_digest(code):
    return hashlib.sha256(code.strip().casefold().replace('ё','е').encode('utf-8')).hexdigest()


def ip_guard():
    return os.environ.get('FORUM_IP_GUARD','1')=='1'

def product_ids(product):
    return list(dict.fromkeys([product['id'],*product.get('legacy_products',[])]))

def claimed(db,table,identity,product):
    column={'session_products':'session','ip_products':'ip'}[table]
    ids=product_ids(product)
    return bool(db.execute('SELECT 1 FROM '+table+' WHERE '+column+'=? AND product IN ('+','.join('?' for _ in ids)+')',[identity,*ids]).fetchone())

def inventory(db,product,now=None):
    config=product.get('stock')
    if not config:return None
    now=now or datetime.now(timezone.utc)
    total=int(config['total']);initial=int(config['initial'])
    release=datetime.fromisoformat(config['release_at'])
    cap=total if now>=release else initial
    ids=product_ids(product)
    row=db.execute('SELECT count(*),sum(fulfilled_at IS NOT NULL) FROM exchanges WHERE product IN ('+','.join('?' for _ in ids)+')',ids).fetchone()
    allocated=row[0];issued=row[1] or 0
    return dict(total=cap,released=cap,available=max(0,cap-allocated),reserved=allocated-issued,
                issued=issued,remaining=max(0,cap-issued))

def shop_data(db,sid,ip):
    result={}
    for p in catalog()['products']:
        bought=claimed(db,'session_products',sid,p)
        blocked=ip_guard() and claimed(db,'ip_products',ip,p)
        result[p['id']]=dict(purchased=bool(bought or blocked),stock=inventory(db,p))
    return result

def progress(db,sid,ip=""):
    shop=shop_data(db,sid,ip)
    return dict(shop=shop,balance=db.execute('SELECT balance FROM sessions WHERE id=?',(sid,)).fetchone()[0],completed=[r[0] for r in db.execute('SELECT task FROM completed WHERE session=?',(sid,))],redeemed=db.execute('SELECT count(*) FROM code_uses WHERE session=?',(sid,)).fetchone()[0],history=[dict(r) for r in db.execute('SELECT request,product,name,price,created,receipt,fulfilled_at FROM exchanges WHERE session=? ORDER BY created DESC,rowid DESC',(sid,))])

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
    def identity(self):
        peer=ipaddress.ip_address(self.client_address[0])
        addr=peer
        if os.environ.get('FORUM_TRUST_PROXY','0')=='1' and peer.is_loopback:
            try:addr=ipaddress.ip_address(self.headers.get('X-Real-IP',''))
            except ValueError:pass
        if isinstance(addr,ipaddress.IPv6Address) and addr.ipv4_mapped:addr=addr.ipv4_mapped
        return hmac.new((STATE/'ip-key.txt').read_bytes(),addr.compressed.encode(),hashlib.sha256).hexdigest()
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/api/health':
            self.reply(200,{'status':'ok','build':BUILD_ID});return
        if path=='/api/state':
            with connect() as db:
                sid=self.session(db); self.reply(200,dict(data=public_catalog(),**progress(db,sid,self.identity())),sid)
            return
        files={'/':'index.html','/vote':'vote.html','/results':'results.html','/poll-admin':'poll-admin.html','/control':'poll-admin.html','/poll.js':'poll.js','/staff':'staff.html','/staff.js':'staff.js','/app.js':'app.js','/style.css':'style.css','/logo.png':'logo.png','/logo.svg':'logo.svg','/district.svg':'district.svg'}
        file=ROOT/'public'/files.get(path,'missing')
        if not file.is_file(): self.send_error(404); return
        raw=file.read_bytes(); self.send_response(200); self.headers_common()
        self.send_header('Cache-Control','no-cache')
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
        if self.path.startswith('/api/poll/'):
            polls.handle(self,body,connect);return
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
            ip=self.identity()
            data=catalog(); error=None; status=200
            if self.path=='/api/receive':
                now=int(time.time())
                attempts=db.execute('SELECT window,count FROM delivery_attempts WHERE session=?',(sid,)).fetchone()
                count=attempts['count'] if attempts and now-attempts['window']<60 else 0
                if count>=5:
                    error='Слишком много попыток. Подожди минуту.';status=429
                else:
                    confirmation=body.get('confirmation','')
                    valid=isinstance(confirmation,str) and len(confirmation)<=200 and hmac.compare_digest(
                        confirmation.strip().casefold().encode(),(STATE/'delivery-code.txt').read_text().strip().casefold().encode())
                    receipt=body.get('receipt','')
                    row=db.execute('SELECT receipt,fulfilled_at FROM exchanges WHERE session=? AND receipt=?',
                        (sid,receipt.strip().upper())).fetchone() if isinstance(receipt,str) else None
                    if not valid:
                        db.execute('INSERT OR REPLACE INTO delivery_attempts VALUES(?,?,?)',(sid,attempts['window'] if count else now,count+1))
                        error='Неверный код организатора.';status=403
                    elif not row:
                        error='Обмен не найден в истории этого участника.';status=404
                    else:
                        db.execute('UPDATE exchanges SET fulfilled_at=? WHERE session=? AND receipt=? AND fulfilled_at IS NULL',
                            (now,sid,row['receipt']))
                        db.execute('DELETE FROM delivery_attempts WHERE session=?',(sid,))
            elif self.path=='/api/redeem':
                supplied=body.get('code','')
                row=db.execute('SELECT window,count FROM attempts WHERE session=?',(sid,)).fetchone()
                now=int(time.time()); count=row['count'] if row and now-row['window']<60 else 0
                db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(sid,row['window'] if count else now,count+1))
                record=db.execute("SELECT * FROM redeem_codes WHERE digest=? AND task='*' AND active=1",
                    (code_digest(supplied),)).fetchone() if isinstance(supplied,str) and 0<len(supplied)<=100 else None
                iprow=db.execute('SELECT window,count FROM ip_attempts WHERE ip=?',(ip,)).fetchone()
                ipcount=iprow['count'] if iprow and now-iprow['window']<60 else 0
                if ip_guard():db.execute('INSERT OR REPLACE INTO ip_attempts VALUES(?,?,?)',(ip,iprow['window'] if ipcount else now,ipcount+1))
                if count>=20 or (ip_guard() and ipcount>=60): error='Слишком много попыток. Повтори через минуту.';status=429
                elif not record: error='Код не найден. Проверь написание.';status=400
                elif db.execute('SELECT 1 FROM code_uses WHERE digest=? AND session=?',(record['digest'],sid)).fetchone():
                    if ip_guard():db.execute('INSERT OR IGNORE INTO ip_codes VALUES(?,?,?,?)',(ip,record['digest'],sid,now))
                elif ip_guard() and db.execute('SELECT 1 FROM ip_codes WHERE ip=? AND digest=?',(ip,record['digest'])).fetchone():
                    error='С этого IP-адреса этот код уже применяли.';status=409
                elif db.execute('SELECT count(*) FROM code_uses WHERE digest=?',(record['digest'],)).fetchone()[0]>=(5 if record['max_uses']==10 else record['max_uses']):
                    error='Лимит использований этого кода исчерпан.';status=409
                else:
                    if ip_guard():db.execute('INSERT INTO ip_codes VALUES(?,?,?,?)',(ip,record['digest'],sid,now))
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
                    elif not record or not record['active'] or record['task']!=task['id']:
                        error='Проверь код и задание. Такой код не найден для этого задания.'; status=400
                    elif ip_guard() and db.execute('SELECT 1 FROM ip_codes WHERE ip=? AND digest=?',(ip,record['digest'])).fetchone():
                        error='С этого IP-адреса этот код уже применяли.';status=409
                    elif record['used_by'] is not None:
                        error='Этот код уже использован. Получи новый код у организатора.'; status=409
                    else:
                        db.execute('UPDATE redeem_codes SET used_by=?,used_at=? WHERE digest=? AND used_by IS NULL',
                            (sid,now,record['digest']))
                        if ip_guard():db.execute('INSERT INTO ip_codes VALUES(?,?,?,?)',(ip,record['digest'],sid,now))
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
                elif claimed(db,'session_products',sid,product):
                    error='Ты уже обменял баллы на этот товар. Повторный обмен недоступен.';status=409
                elif ip_guard() and claimed(db,'ip_products',ip,product):
                    error='С этого IP-адреса этот товар уже приобретали.';status=409
                else:
                    balance=progress(db,sid)['balance']
                    stock=inventory(db,product)
                    if stock and stock['available']<=0:
                        error='Этот товар сейчас закончился.';status=409
                    elif balance<product['price']: error=f"Нужно ещё {product['price']-balance} балл(ов)"; status=409
                    else:
                        db.execute('INSERT INTO session_products VALUES(?,?)',(sid,product['id']))
                        if ip_guard():db.execute('INSERT INTO ip_products VALUES(?,?,?)',(ip,product['id'],sid))
                        db.execute('UPDATE sessions SET balance=balance-? WHERE id=?',(product['price'],sid))
                        db.execute('INSERT INTO exchanges(session,request,product,name,price,created,receipt) VALUES(?,?,?,?,?,?,?)',(sid,key,product['id'],product['name'],product['price'],int(time.time()),secrets.token_hex(8).upper()))
            else: error='Не найдено'; status=404
            db.commit(); result=progress(db,sid,ip)
            if error: result['error']=error
            self.reply(status,result,sid)

class ForumServer(ThreadingHTTPServer):
    request_queue_size=1024
    def __init__(self,*args,**kwargs):
        self.pool=ThreadPoolExecutor(max_workers=32)
        super().__init__(*args,**kwargs)
    def process_request(self,request,client_address):
        self.pool.submit(self.process_request_thread,request,client_address)
    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8090); parser.add_argument('--host',default='0.0.0.0'); args=parser.parse_args()
    initialize(); print(f'ForumMM listening on port {args.port}',flush=True)
    ForumServer((args.host,args.port),Handler).serve_forever()
