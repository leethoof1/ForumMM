"""Unlisted live poll. Tokens are URL fragments, not request URLs or access-log entries."""
import base64
import hmac
import io
import json
import os
import secrets
import time

QUESTION='Кто кого сегодня лучше понимает?'
OPTIONS=[{'id':'adults','label':'Взрослые лучше понимают молодёжь'},
         {'id':'youth','label':'Молодёжь лучше понимает взрослых'}]

def initialize(db,state):
    db.executescript('''CREATE TABLE IF NOT EXISTS live_polls(
      id TEXT PRIMARY KEY,question TEXT,options TEXT,opened INTEGER NOT NULL DEFAULT 0,
      voter TEXT UNIQUE,screen TEXT UNIQUE,control TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS poll_votes(
      poll TEXT REFERENCES live_polls(id),session TEXT REFERENCES sessions(id),
      choice TEXT,ip TEXT,created INTEGER,PRIMARY KEY(poll,session));
    CREATE INDEX IF NOT EXISTS poll_choice ON poll_votes(poll,choice);
    CREATE INDEX IF NOT EXISTS poll_ip ON poll_votes(poll,ip);''')
    db.execute('INSERT OR IGNORE INTO live_polls(id,question,options,voter,screen,control) VALUES(?,?,?,?,?,?)',
       ('plenary',QUESTION,json.dumps(OPTIONS,ensure_ascii=False),secrets.token_urlsafe(24),secrets.token_urlsafe(24),secrets.token_urlsafe(32)))
    db.commit()
    row=db.execute("SELECT voter,screen,control FROM live_polls WHERE id='plenary'").fetchone()
    base=os.environ.get('FORUM_PUBLIC_URL','https://mm2026.ru').rstrip('/')
    links=dict(vote=base+'/vote#'+row['voter'],results=base+'/results#'+row['screen'],control=base+'/poll-admin#'+row['control'])
    path=state/'poll-links.json'
    # A private copy for the owner. Never exposed by the static-file handler.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(links,f,ensure_ascii=False,indent=2)

def view(db,row,sid=None):
    choice=None
    if sid:
        found=db.execute('SELECT choice FROM poll_votes WHERE poll=? AND session=?',(row['id'],sid)).fetchone()
        choice=found['choice'] if found else None
    return dict(question=row['question'],options=json.loads(row['options']),opened=bool(row['opened']),choice=choice)

def tally(db,row):
    result=view(db,row)
    counts={r['choice']:r['n'] for r in db.execute('SELECT choice,count(*) AS n FROM poll_votes WHERE poll=? GROUP BY choice',(row['id'],))}
    result['counts']=counts;result['total']=sum(counts.values())
    return result

def handle(handler,body,connect):
    action=handler.path.rsplit('/',1)[-1]
    role={'view':'voter','vote':'voter','results':'screen','qr':'screen','manage':'control'}.get(action)
    token=body.get('token','')
    if not role or not isinstance(token,str) or not 16<=len(token)<=128:
        handler.reply(403,{'error':'Ссылка неполная или недействительна.'});return
    with connect() as db:
        row=db.execute('SELECT * FROM live_polls WHERE '+role+'=?',(token,)).fetchone()
        if not row:handler.reply(403,{'error':'Ссылка недействительна.'});return
        if action=='results':handler.reply(200,tally(db,row));return
        if action=='qr':
            try:
                import qrcode
                from qrcode.image.svg import SvgPathImage
            except ImportError:
                handler.reply(503,{'error':'На сервере требуется пакет python3-qrcode.'});return
            url=os.environ.get('FORUM_PUBLIC_URL','https://mm2026.ru').rstrip('/')+'/vote#'+row['voter']
            image=qrcode.make(url,image_factory=SvgPathImage,border=4);output=io.BytesIO();image.save(output)
            handler.reply(200,{'image':'data:image/svg+xml;base64,'+base64.b64encode(output.getvalue()).decode(),'url':url});return
        if action=='manage':
            command=body.get('action','status')
            if command not in ['status','open','close','reset']:
                handler.reply(400,{'error':'Неизвестная команда'});return
            db.execute('BEGIN IMMEDIATE')
            if command=='reset':
                if body.get('confirm')!='RESET-POLL':handler.reply(400,{'error':'Сброс не подтверждён'});return
                db.execute('DELETE FROM poll_votes WHERE poll=?',(row['id'],))
                db.execute('UPDATE live_polls SET opened=0 WHERE id=?',(row['id'],))
            elif command in ['open','close']:
                db.execute('UPDATE live_polls SET opened=? WHERE id=?',(int(command=='open'),row['id']))
            db.commit();row=db.execute('SELECT * FROM live_polls WHERE id=?',(row['id'],)).fetchone()
            handler.reply(200,tally(db,row));return
        sid=handler.session(db)
        if action=='view':handler.reply(200,view(db,row,sid),sid);return
        choice=body.get('choice')
        if choice not in [x['id'] for x in json.loads(row['options'])]:
            handler.reply(400,{'error':'Выбери один из вариантов.'},sid);return
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM live_polls WHERE id=?',(row['id'],)).fetchone()
        previous=db.execute('SELECT choice FROM poll_votes WHERE poll=? AND session=?',(row['id'],sid)).fetchone()
        if previous:
            status=200 if previous['choice']==choice else 409
            data=view(db,row,sid)
            if status!=200:data['error']='Голос уже учтён. Изменить вариант нельзя.'
            handler.reply(status,data,sid);return
        if not row['opened']:handler.reply(409,{'error':'Голосование сейчас закрыто.'},sid);return
        ip=handler.identity()
        if os.environ.get('FORUM_POLL_IP_GUARD','0')=='1' and db.execute('SELECT 1 FROM poll_votes WHERE poll=? AND ip=?',(row['id'],ip)).fetchone():
            handler.reply(409,{'error':'С этого IP уже голосовали.'},sid);return
        db.execute('INSERT INTO poll_votes VALUES(?,?,?,?,?)',(row['id'],sid,choice,ip,int(time.time())))
        db.commit();handler.reply(200,view(db,row,sid),sid)
