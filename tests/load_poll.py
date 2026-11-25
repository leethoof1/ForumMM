"""600 concurrent test voters. Loopback only, resets this TEST poll. Requires aiohttp."""
import asyncio,json,os,statistics,time
from pathlib import Path
from urllib.parse import urlsplit
import aiohttp
BASE=os.environ.get('FORUM_TEST_URL','http://127.0.0.1:8101').rstrip('/')
assert urlsplit(BASE).hostname in ['127.0.0.1','localhost'],'Use a separate loopback test server'
STATE=Path(os.environ['FORUM_STATE_DIR'])
links=json.loads((STATE/'poll-links.json').read_text());tokens={k:v.split('#')[1] for k,v in links.items()}
async def main():
 async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0),cookie_jar=aiohttp.DummyCookieJar(),timeout=aiohttp.ClientTimeout(total=60)) as client:
  async def post(endpoint,role='vote',cookie='',**body):
   async with client.post(BASE+'/api/poll/'+endpoint,json={'token':tokens[role],**body},headers={'X-Forum-Request':'1','Cookie':cookie}) as r:
    d=await r.json();assert r.status==200,(r.status,d)
    return d,r.headers.get('Set-Cookie','').split(';')[0]
  await post('manage',role='control',action='reset',confirm='RESET-POLL')
  await post('manage',role='control',action='open')
  initial=await asyncio.gather(*(post('view') for _ in range(600)))
  cookies=[r[1] for r in initial];assert len(set(cookies))==600
  latencies=[]
  async def voter(i):
   t=time.perf_counter();await post('vote',cookie=cookies[i],choice='adults' if i%2==0 else 'youth');latencies.append(time.perf_counter()-t)
  begin=time.perf_counter();await asyncio.gather(*(voter(i) for i in range(600)));elapsed=time.perf_counter()-begin
  result,_=await post('results',role='results')
  assert result['total']==600 and result['counts']=={'adults':300,'youth':300},result
  await asyncio.gather(*(post('vote',cookie=cookies[i],choice='adults' if i%2==0 else 'youth') for i in range(600)))
  result,_=await post('results',role='results');assert result['total']==600
  latency=sorted(latencies)
  print(json.dumps({'voters':600,'concurrent_vote_requests':600,'counts':result['counts'],'duplicate_replays':600,'errors':0,'burst_seconds':round(elapsed,3),'p95_seconds':round(latency[569],3)},ensure_ascii=False))
asyncio.run(main())
