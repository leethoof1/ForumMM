"""Verify the running build, static poll pages and currently released stock."""
from pathlib import Path
import hashlib,json,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]

def validate_state(data):
    assert len(data['data']['venues'])==6
    assert data['data']['products'][0]['id']=='kit'
    stock=data['shop']['kit']['stock']
    # Both release stages are legitimate. Do not roll back a healthy 500-item release!
    assert stock['total'] in (500,700)
    assert stock['total']==stock['released']
    assert 0<=stock['available']<=stock['total']
    assert 0<=stock['remaining']<=stock['total']
    assert 'upcoming' not in stock and 'release_at' not in stock

def check(base='http://127.0.0.1:8090'):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(base+path,timeout=4) as response:return response.read()
    expected=hashlib.sha256((ROOT/'server.py').read_bytes()+(ROOT/'polls.py').read_bytes()).hexdigest()
    health=json.loads(get('/api/health'));assert health['build']==expected,'Запущена другая версия сервера'
    validate_state(json.loads(get('/api/state')))
    for filename in ['app.js','poll.js','style.css']:
        assert get('/'+filename)==(ROOT/'public'/filename).read_bytes(),'Отдаётся старый файл интерфейса: '+filename
    for path,role in [('/vote','vote'),('/results','results'),('/control','control')]:
        assert ('data-poll-role="'+role+'"').encode() in get(path),path+' не готов'
    print('Текущая версия, обе стадии остатков, страницы голосования и интерфейс: OK')

if __name__=='__main__':
    for i in range(15):
        try:check(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8090');break
        except (OSError,AssertionError,ValueError):
            if i==14:raise
            time.sleep(1)
