import concurrent.futures
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
class API(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  fixture=json.loads((ROOT/'data.json').read_text())
  fixture['products']=[dict(id='sticker',name='Наклейка',price=1),dict(id='shirt',name='Футболка',price=7)]
  path=pathlib.Path(cls.tmp.name)/'catalog.json';path.write_text(json.dumps(fixture))
  cls.env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name,'FORUM_SECURE_COOKIE':'0','FORUM_IP_GUARD':'0','FORUM_CATALOG_PATH':str(path)}
  cls.start_server()
 @classmethod
 def start_server(cls):
  cls.proc=subprocess.Popen(['python3','server.py','--port','8011','--host','127.0.0.1'],cwd=ROOT,env=cls.env,stdout=subprocess.DEVNULL)
  for _ in range(100):
   try:
    urllib.request.urlopen('http://127.0.0.1:8011/api/state',timeout=1);return
   except OSError: time.sleep(.05)
  raise RuntimeError('Test server did not start')
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def setUp(self):
  self.cookie=self.new_cookie()
  self.code='TEST-'+os.urandom(10).hex()
  self.add_code(self.code)
 def add_code(self,code,task='t0'):
  with sqlite3.connect(pathlib.Path(self.tmp.name)/'progress.sqlite3') as db:
   db.execute('INSERT INTO redeem_codes(digest,task,batch,created) VALUES(?,?,?,?)',(hashlib.sha256(code.strip().casefold().encode()).hexdigest(),task,'test',int(time.time())))
 def new_cookie(self):
  r=urllib.request.urlopen('http://127.0.0.1:8011/api/state');return r.headers['Set-Cookie'].split(';')[0]
 def request(self,path,body=None,cookie=None,staff=False):
  req=urllib.request.Request('http://127.0.0.1:8011/api/'+path,data=json.dumps(body).encode() if body else None,headers={'Cookie':cookie or self.cookie,'X-Forum-Request':'1','Content-Type':'application/json',**({'X-Staff-Key':(pathlib.Path(self.tmp.name)/'staff-key.txt').read_text().strip()} if staff else {})})
  try:r=urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:r=e
  return r.status,json.load(r)
 def complete(self,code=None,task='t0',cookie=None):
  return self.request('complete',{'task':task,'code':code or self.code},cookie)
 def test_full_flow_and_concurrency(self):
  self.assertEqual(self.complete('wrong')[0],400)
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
   results=list(pool.map(lambda _:self.complete('  '+self.code.lower()+'  '),range(10)))
  self.assertTrue(all(s==200 and d['balance']==1 for s,d in results))
  self.assertEqual(self.request('state')[1]['completed'],['t0'])
  self.assertEqual(self.request('exchange',{'product':'shirt','request':'not-enough'})[0],409)
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
   list(pool.map(lambda _:self.request('exchange',{'product':'sticker','request':'same-request'}),range(10)))
  d=self.request('state')[1];self.assertEqual(d['balance'],0);self.assertEqual(len(d['history']),1)
  self.assertEqual(self.request('exchange',{'product':'sticker','request':'another-request'})[0],409)
  self.assertNotIn(self.code,json.dumps(d));self.assertNotIn('digest',json.dumps(d))
 def test_one_code_globally_even_after_cookie_reset(self):
  self.assertEqual(self.complete()[0],200)
  other=self.new_cookie()
  self.assertEqual(self.complete(cookie=other)[0],409)
  self.assertEqual(self.request('state',cookie=other)[1]['balance'],0)
 def test_competing_participants_same_code(self):
  cookies=[self.new_cookie() for _ in range(12)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
   results=list(pool.map(lambda c:self.complete(cookie=c),cookies))
  self.assertEqual(sum(s==200 for s,_ in results),1)
  self.assertEqual(sum(d['balance'] for _,d in results),1)
 def test_wrong_task_does_not_burn_code(self):
  self.assertEqual(self.complete(task='t1')[0],400)
  self.assertEqual(self.complete()[0],200)
 def test_completed_task_does_not_burn_second_code(self):
  second='OTHER-'+self.code;self.add_code(second)
  self.complete();self.complete(second)
  self.assertEqual(self.request('state')[1]['balance'],1)
  self.assertEqual(self.complete(second,cookie=self.new_cookie())[0],200)
 def test_competing_exchanges(self):
  self.complete()
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda i:self.request('exchange',{'product':'sticker','request':f'unique-key-{i}'}),range(8)))
  self.assertEqual(sum(s==200 for s,_ in results),1)
  self.assertEqual(len(self.request('state')[1]['history']),1)
 def test_restart_retains_progress_and_redemption(self):
  self.complete();self.proc.terminate();self.proc.wait();type(self).start_server()
  self.assertEqual(self.request('state')[1]['balance'],1)
  self.assertEqual(self.complete(cookie=self.new_cookie())[0],409)
 def test_generator_hashes_and_non_overwrite(self):
  out=pathlib.Path(self.tmp.name)/'print.csv'
  args=['python3','tools/manage_codes.py','generate','--per-task','3','--task','t1','--output',str(out)]
  result=subprocess.run(args,cwd=ROOT,env=self.env,capture_output=True)
  self.assertEqual(result.returncode,0,result.stderr)
  import csv
  with out.open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
  self.assertEqual(len(rows),3)
  self.assertEqual(len({r['code'] for r in rows}),3)
  self.assertEqual(self.complete(rows[0]['code'],task='t1')[0],200)
  before=out.read_bytes();self.assertNotEqual(subprocess.run(args,cwd=ROOT,env=self.env,capture_output=True).returncode,0)
  self.assertEqual(out.read_bytes(),before)
  self.assertEqual(out.stat().st_mode&0o777,0o600)
 def test_throttle(self):
  for _ in range(20):self.complete('wrong')
  self.assertEqual(self.complete()[0],429)
  self.assertEqual(self.complete(cookie=self.new_cookie())[0],200)
 def test_pool_capacity_concurrency_and_repeat(self):
  with sqlite3.connect(pathlib.Path(self.tmp.name)/'progress.sqlite3') as db:
   db.execute("UPDATE redeem_codes SET task='*',max_uses=3 WHERE digest=?",(hashlib.sha256(self.code.casefold().encode()).hexdigest(),))
  cookies=[self.new_cookie() for _ in range(12)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
   results=list(pool.map(lambda c:self.request('redeem',{'code':self.code},cookie=c),cookies))
  self.assertEqual(sum(status==200 for status,_ in results),3)
  winner=cookies[next(i for i,r in enumerate(results) if r[0]==200)]
  result=self.request('redeem',{'code':self.code},cookie=winner)
  self.assertEqual(result[0],200);self.assertEqual(result[1]['balance'],1)
  self.assertEqual(result[1]['redeemed'],1)
  self.assertEqual(self.request('redeem',{'code':self.code},cookie=self.new_cookie())[0],409)
 def test_pool_generation_and_repeat_import(self):
  import csv,collections
  out=pathlib.Path(self.tmp.name)/('pool-'+os.urandom(5).hex()+'.csv')
  result=subprocess.run(['python3','tools/manage_codes.py','pool','--output',str(out)],cwd=ROOT,env=self.env,capture_output=True)
  self.assertEqual(result.returncode,0,result.stderr)
  with out.open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
  self.assertEqual(collections.Counter(int(r['max_uses']) for r in rows),{600:5,100:15,5:80})
  self.assertEqual(len({r['code'] for r in rows}),100)
  self.request('redeem',{'code':rows[0]['code']})
  for _ in range(2):
   result=subprocess.run(['python3','tools/manage_codes.py','import-pool',str(out)],cwd=ROOT,env=self.env,capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.request('redeem',{'code':rows[0]['code']})[1]['balance'],1)
 def test_staff_fulfillment_auth_idempotency(self):
  self.complete()
  self.request('exchange',{'product':'sticker','request':'claim-request'})
  h=self.request('state')[1]['history'][0];receipt=h['receipt']
  self.assertIsNone(h['fulfilled_at'])
  self.assertEqual(self.request('staff/fulfill',{'receipt':receipt})[0],403)
  self.assertEqual(self.request('staff/lookup',{'receipt':receipt},staff=True)[0],200)
  with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
   results=list(pool.map(lambda _:self.request('staff/fulfill',{'receipt':receipt},staff=True),range(6)))
  self.assertEqual(sum(not d['already_fulfilled'] for _,d in results),1)
  self.assertTrue(all(d['exchange']['fulfilled_at'] for _,d in results))
  state=self.request('state')[1]
  self.assertTrue(state['history'][0]['fulfilled_at']);self.assertEqual(state['balance'],0)
  self.assertNotIn('staff-key',json.dumps(state))
 def test_phone_delivery_owner_auth_and_concurrency(self):
  self.complete();self.request('exchange',{'product':'sticker','request':'phone-delivery'})
  receipt=self.request('state')[1]['history'][0]['receipt']
  secret=(pathlib.Path(self.tmp.name)/'delivery-code.txt').read_text()
  self.assertEqual(self.request('receive',{'receipt':receipt,'confirmation':'wrong'})[0],403)
  self.assertEqual(self.request('receive',{'receipt':receipt,'confirmation':secret},cookie=self.new_cookie())[0],404)
  self.assertIsNone(self.request('state')[1]['history'][0]['fulfilled_at'])
  with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
   results=list(pool.map(lambda _:self.request('receive',{'receipt':receipt,'confirmation':' '+secret.lower()+' '}),range(6)))
  self.assertTrue(all(status==200 for status,_ in results))
  self.assertEqual(len({r['history'][0]['fulfilled_at'] for _,r in results}),1)
  d=self.request('state')[1];self.assertEqual(d['balance'],0);self.assertTrue(d['history'][0]['fulfilled_at'])
  self.assertNotIn(secret,json.dumps(d,ensure_ascii=False))
 def test_phone_delivery_throttle(self):
  self.complete();self.request('exchange',{'product':'sticker','request':'phone-delivery-throttle'})
  receipt=self.request('state')[1]['history'][0]['receipt']
  for _ in range(5):self.assertEqual(self.request('receive',{'receipt':receipt,'confirmation':'wrong'})[0],403)
  secret=(pathlib.Path(self.tmp.name)/'delivery-code.txt').read_text()
  self.assertEqual(self.request('receive',{'receipt':receipt,'confirmation':secret})[0],429)
  self.assertIsNone(self.request('state')[1]['history'][0]['fulfilled_at'])
 def test_pool_replace_keeps_balance_and_disables_old(self):
  import csv
  old=pathlib.Path(self.tmp.name)/('old-'+os.urandom(4).hex()+'.csv')
  new=pathlib.Path(self.tmp.name)/('new-'+os.urandom(4).hex()+'.csv')
  for path in [old,new]:
   r=subprocess.run(['python3','tools/manage_codes.py','pool','--output',str(path)],cwd=ROOT,env=self.env,capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr)
  with old.open(encoding='utf-8-sig') as f:oldcode=next(csv.DictReader(f))['code']
  with new.open(encoding='utf-8-sig') as f:newcode=next(csv.DictReader(f))['code']
  self.request('redeem',{'code':oldcode})
  for _ in range(2):
   r=subprocess.run(['python3','tools/manage_codes.py','replace-pool',str(new)],cwd=ROOT,env=self.env,capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr)
  self.assertEqual(self.request('state')[1]['balance'],1)
  self.assertEqual(self.request('redeem',{'code':oldcode},cookie=self.new_cookie())[0],400)
  self.assertEqual(self.request('redeem',{'code':newcode})[1]['balance'],2)
  self.assertEqual(self.request('redeem',{'code':newcode})[1]['balance'],2)
 def test_code_normalization_cyrillic(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('forum_server',ROOT/'server.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertEqual(module.code_digest('  УЧЁБА '),module.code_digest('учеба'))
 def test_lower_ten_use_limit_preserves_consumption_and_balance(self):
  with sqlite3.connect(pathlib.Path(self.tmp.name)/'progress.sqlite3') as db:
   db.execute("UPDATE redeem_codes SET task='*',max_uses=10 WHERE digest=?",(hashlib.sha256(self.code.casefold().encode()).hexdigest(),))
  cookies=[self.new_cookie() for _ in range(6)]
  for cookie in cookies[:5]:self.assertEqual(self.request('redeem',{'code':self.code},cookie=cookie)[0],200)
  self.assertEqual(self.request('redeem',{'code':self.code},cookie=cookies[5])[0],409)
  self.proc.terminate();self.proc.wait();type(self).start_server()
  with sqlite3.connect(pathlib.Path(self.tmp.name)/'progress.sqlite3') as db:
   self.assertEqual(db.execute('SELECT max_uses FROM redeem_codes WHERE digest=?',(hashlib.sha256(self.code.casefold().encode()).hexdigest(),)).fetchone()[0],5)
  self.assertEqual(self.request('state',cookie=cookies[0])[1]['balance'],1)
if __name__=='__main__':unittest.main()
