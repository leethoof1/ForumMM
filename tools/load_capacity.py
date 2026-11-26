"""Run on the VPS. Read-only live traffic, votes only in a fresh isolated database."""
import argparse, asyncio, collections, json, os, socket, subprocess, tempfile, time
from pathlib import Path
import aiohttp

class LocalResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [dict(hostname=host,host='127.0.0.1',port=port,family=socket.AF_INET,proto=0,flags=0)]
    async def close(self): pass

def memory():
    fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return {k:int(fields[k].split()[0])//1024 for k in ('MemTotal','MemAvailable','SwapFree')}

async def stage(base,n,hold):
    statuses=collections.Counter(); latency=[]; failures=[]; samples=[]; stop=asyncio.Event()
    async def monitor():
        while not stop.is_set():
            samples.append(memory()['MemAvailable'])
            await asyncio.sleep(.2)
    async def visitor(i):
        # Distinct genuine loopback source addresses model different client IPs.
        address=f'127.1.{i//250}.{i%250+1}'
        connector=aiohttp.TCPConnector(resolver=LocalResolver(),local_addr=(address,0),limit=4)
        async with aiohttp.ClientSession(connector=connector,cookie_jar=aiohttp.CookieJar(unsafe=True),timeout=aiohttp.ClientTimeout(total=30)) as client:
            async def get(path):
                start=time.monotonic()
                try:
                    async with client.get(base+path) as r:
                        await r.read();statuses[str(r.status)]+=1
                        if r.status!=200 and len(failures)<5:failures.append(f'{path}: HTTP {r.status}')
                except Exception as e:
                    statuses['network_error']+=1
                    if len(failures)<5:failures.append(type(e).__name__+': '+str(e)[:120])
                latency.append(time.monotonic()-start)
            await get('/')
            await asyncio.gather(*(get(p) for p in ['/app.js','/style.css','/logo.svg','/district.svg','/api/state']))
            if hold:
                await asyncio.sleep(hold)
                await get('/api/state')
    watcher=asyncio.create_task(monitor());start=time.monotonic()
    try:await asyncio.gather(*(visitor(i) for i in range(n)))
    finally:stop.set();await watcher
    latency.sort();count=sum(statuses.values());errors=count-statuses['200']
    return dict(visitors=n,requests=count,statuses=dict(statuses),errors=errors,p95_seconds=round(latency[min(len(latency)-1,int(len(latency)*.95))],3),seconds=round(time.monotonic()-start,2),minimum_available_mb=min(samples),examples=failures)

async def shadow(root,n):
    # Never use the production state directory or its tokens for write tests.
    with tempfile.TemporaryDirectory(prefix='forum-capacity-') as state:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'FORUM_STATE_DIR':state,'FORUM_IP_GUARD':'0','FORUM_POLL_IP_GUARD':'0','FORUM_SECURE_COOKIE':'0','FORUM_PUBLIC_URL':base}
        with open(Path(state)/'server.log','w') as log:
            process=subprocess.Popen(['python3',str(root/'server.py'),'--host','127.0.0.1','--port',str(port)],env=env,cwd=root,stdout=log,stderr=log)
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0),cookie_jar=aiohttp.DummyCookieJar(),timeout=aiohttp.ClientTimeout(total=60)) as client:
                    for _ in range(100):
                        if process.poll() is not None:raise RuntimeError('Тестовый сервер не запустился')
                        try:
                            async with client.get(base+'/api/health') as r:
                                if r.status==200:break
                        except aiohttp.ClientError:pass
                        await asyncio.sleep(.1)
                    else:raise RuntimeError('Тестовый сервер не отвечает')
                    links=json.loads((Path(state)/'poll-links.json').read_text())
                    tokens={k:v.partition('#')[2] for k,v in links.items()}
                    async def post(endpoint,role='vote',cookie='',**body):
                        async with client.post(base+'/api/poll/'+endpoint,json={'token':tokens[role],**body},headers={'X-Forum-Request':'1','Cookie':cookie}) as r:
                            data=await r.json()
                            if r.status!=200:raise RuntimeError(f'{endpoint}: HTTP {r.status}')
                            return data,r.headers.get('Set-Cookie','').split(';')[0]
                    await post('manage',role='control',action='open')
                    initial=await asyncio.gather(*(post('view') for _ in range(n)))
                    cookies=[x[1] for x in initial]
                    if len(set(cookies))!=n:raise RuntimeError('Не созданы уникальные тестовые сессии')
                    timings=[]
                    async def vote(i):
                        start=time.monotonic();await post('vote',cookie=cookies[i],choice='adults' if i%2==0 else 'youth');timings.append(time.monotonic()-start)
                    start=time.monotonic();await asyncio.gather(*(vote(i) for i in range(n)));elapsed=time.monotonic()-start
                    await asyncio.gather(*(vote(i) for i in range(n)))
                    result,_=await post('results',role='results')
                    if result['total']!=n or result['counts']!={'adults':(n+1)//2,'youth':n//2}:raise RuntimeError('Неверное число голосов')
                    return dict(voters=n,total=result['total'],counts=result['counts'],duplicate_requests=n,seconds=round(elapsed,3),errors=0)
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()

async def main(args):
    report=dict(memory_mb=memory(),cpu_cores=os.cpu_count(),initial_load=os.getloadavg(),note='Генератор нагрузки работает на том же сервере. Внешняя сеть и мобильные операторы не проверяются.',stages=[])
    for n in map(int,args.stages.split(',')):
        print(f'Проверка одновременного входа: {n} участников',flush=True)
        result=await stage(args.base.rstrip('/'),n,args.hold);report['stages'].append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if result['errors'] or result['minimum_available_mb']<max(64,report['memory_mb']['MemTotal']*.08):
            report['stopped']='Ошибки или малый запас памяти: следующая ступень отменена';break
    if not args.no_shadow and 'stopped' not in report:
        print('700 голосов в отдельной временной базе, без изменения настоящего голосования',flush=True)
        try:report['isolated_votes']=await shadow(Path(__file__).resolve().parents[1],700)
        except Exception as e:report['isolated_votes']={'error':str(e)}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    os.chmod(args.output,0o600)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    print('Отчёт: '+args.output,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='https://mm2026.ru');p.add_argument('--stages',default='50,150,350,700');p.add_argument('--hold',type=float,default=10);p.add_argument('--no-shadow',action='store_true');p.add_argument('--output',default='/tmp/forum-capacity-report.json');args=p.parse_args()
    if not args.base.startswith(('https://mm2026.ru','http://127.0.0.1:')):p.error('Разрешён только локальный сервер форума')
    asyncio.run(main(args))
