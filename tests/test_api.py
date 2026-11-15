import concurrent.futures, http.cookiejar, json, os, pathlib, subprocess, tempfile, time, unittest, urllib.request, urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
class API(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(); cls.proc=subprocess.Popen(['python3','server.py','--port','8011','--host','127.0.0.1'],cwd=ROOT,env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name},stdout=subprocess.DEVNULL)
  for _ in range(100):
   try: urllib.request.urlopen('http://127.0.0.1:8011/api/state');break
   except OSError: time.sleep(.05)
  (pathlib.Path(cls.tmp.name)/'codes.json').write_text(json.dumps({'t0':'МОСТ'}))
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def setUp(self):
  r=urllib.request.urlopen('http://127.0.0.1:8011/api/state');self.cookie=r.headers['Set-Cookie'].split(';')[0]
 def request(self,path,body=None):
  req=urllib.request.Request('http://127.0.0.1:8011/api/'+path,data=json.dumps(body).encode() if body else None,headers={'Cookie':self.cookie,'X-Forum-Request':'1','Content-Type':'application/json'})
  try:r=urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:r=e
  return r.status,json.load(r)
 def test_full_flow_and_concurrency(self):
  self.assertEqual(self.request('complete',{'task':'t0','code':'wrong'})[0],400)
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
   results=list(pool.map(lambda _:self.request('complete',{'task':'t0','code':'  мост  '}),range(10)))
  self.assertTrue(all(s==200 and d['balance']==1 for s,d in results))
  self.assertEqual(self.request('state')[1]['completed'],['t0'])
  self.assertEqual(self.request('exchange',{'product':'shirt','request':'not-enough'})[0],409)
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
   list(pool.map(lambda _:self.request('exchange',{'product':'sticker','request':'same-request'}),range(10)))
  d=self.request('state')[1];self.assertEqual(d['balance'],0);self.assertEqual(len(d['history']),1)
  self.assertEqual(self.request('exchange',{'product':'sticker','request':'another-request'})[0],409)
  self.assertNotIn('МОСТ',json.dumps(d,ensure_ascii=False));self.assertNotIn('codes',d)
 def test_competing_exchanges(self):
  self.request('complete',{'task':'t0','code':'мост'})
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda i:self.request('exchange',{'product':'sticker','request':f'unique-key-{i}'}),range(8)))
  self.assertEqual(sum(s==200 for s,_ in results),1)
  self.assertEqual(len(self.request('state')[1]['history']),1)
 def test_isolation_and_unknown_task(self):
  self.assertEqual(self.request('complete',{'task':'missing','code':'x'})[0],404)
  self.request('complete',{'task':'t0','code':'мост'})
  fresh=json.load(urllib.request.urlopen('http://127.0.0.1:8011/api/state'));self.assertEqual(fresh['balance'],0)
if __name__=='__main__': unittest.main()
