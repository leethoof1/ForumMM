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
  cls.env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name,'FORUM_SECURE_COOKIE':'0'}
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
 def request(self,path,body=None,cookie=None):
  req=urllib.request.Request('http://127.0.0.1:8011/api/'+path,data=json.dumps(body).encode() if body else None,headers={'Cookie':cookie or self.cookie,'X-Forum-Request':'1','Content-Type':'application/json'})
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
if __name__=='__main__':unittest.main()
