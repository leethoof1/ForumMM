import concurrent.futures,json,os,pathlib,subprocess,tempfile,time,unittest,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Poll(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.state=pathlib.Path(cls.tmp.name)
  cls.env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name,'FORUM_SECURE_COOKIE':'0'}
  cls.proc=subprocess.Popen(['python3','server.py','--host','127.0.0.1','--port','8013'],cwd=ROOT,env=cls.env,stdout=subprocess.DEVNULL)
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:8013/api/state');break
   except OSError:time.sleep(.05)
  links=json.loads((cls.state/'poll-links.json').read_text());cls.tokens={k:v.split('#')[1] for k,v in links.items()}
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def req(self,endpoint,role='vote',cookie='',**body):
  data={'token':self.tokens[role],**body}
  req=urllib.request.Request('http://127.0.0.1:8013/api/poll/'+endpoint,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Forum-Request':'1','Cookie':cookie})
  try:r=urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:r=e
  return r.status,json.load(r),r.headers.get('Set-Cookie','').split(';')[0]
 def setUp(self):self.req('manage',role='control',action='reset',confirm='RESET-POLL')
 def test_closed_open_duplicate_and_close(self):
  _,d,c=self.req('view');self.assertFalse(d['opened'])
  self.assertEqual(self.req('vote',cookie=c,choice='adults')[0],409)
  self.req('manage',role='control',action='open')
  self.assertEqual(self.req('vote',cookie=c,choice='adults')[0],200)
  self.assertEqual(self.req('vote',cookie=c,choice='adults')[0],200)
  self.assertEqual(self.req('vote',cookie=c,choice='youth')[0],409)
  self.assertEqual(self.req('results',role='results')[1]['total'],1)
  self.req('manage',role='control',action='close')
  self.assertEqual(self.req('vote',choice='adults')[0],409)
  self.assertEqual(self.req('view',cookie=c)[1]['choice'],'adults')
 def test_role_isolation(self):
  for action,role in [('results','vote'),('manage','vote'),('manage','results'),('view','control')]:
   self.assertEqual(self.req(action,role=role)[0],403)
  d=self.req('view')[1]
  for value in self.tokens.values():self.assertNotIn(value,json.dumps(d))
 def test_parallel_repeat_one_vote(self):
  self.req('manage',role='control',action='open');_,_,c=self.req('view')
  with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
   results=list(pool.map(lambda _:self.req('vote',cookie=c,choice='youth'),range(12)))
  self.assertTrue(all(r[0]==200 for r in results))
  self.assertEqual(self.req('results',role='results')[1]['total'],1)
 def test_progress_reset_preserves_codes_and_poll_votes(self):
  self.req('manage',role='control',action='open');_,_,c=self.req('view');self.req('vote',cookie=c,choice='adults')
  import sqlite3
  with sqlite3.connect(self.state/'progress.sqlite3') as db:
   sid=c.split('=')[1];db.execute('UPDATE sessions SET balance=9 WHERE id=?',(sid,))
   db.execute("INSERT INTO redeem_codes(digest,task,batch,created) VALUES('testhash','*','test',0)")
   db.execute("INSERT INTO code_uses VALUES('testhash',?,0)",(sid,))
  r=subprocess.run(['python3','tools/reset_progress.py','--confirm','RESET-PROGRESS'],cwd=ROOT,env=self.env,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr)
  with sqlite3.connect(self.state/'progress.sqlite3') as db:
   self.assertEqual(db.execute('SELECT balance FROM sessions WHERE id=?',(sid,)).fetchone()[0],0)
   self.assertEqual(db.execute('SELECT count(*) FROM code_uses').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT count(*) FROM redeem_codes').fetchone()[0],1)
  self.assertEqual(self.req('results',role='results')[1]['total'],1)
  self.assertTrue(list(self.state.glob('before-reset-*.sqlite3')))
 def test_reset_requires_confirmation(self):self.assertEqual(self.req('manage',role='control',action='reset')[0],400)
 def test_poll_proxy_preserves_tls_and_is_repeatable(self):
  from tools.configure_poll_proxy import configure
  path=self.state/'nginx.conf'
  original='server {\n listen 443 ssl;\n ssl_certificate /private/cert.pem;\n}\nserver {\n listen 80;\n return 301 https://mm2026.ru;\n}'
  path.write_text(original);configure(path);first=path.read_text();configure(path)
  self.assertEqual(path.read_text(),first)
  self.assertIn('ssl_certificate /private/cert.pem;',first)
  self.assertIn('return 301 https://mm2026.ru;',first)
  self.assertEqual(first.count('FORUM_POLL_LOCATION'),2)
if __name__=='__main__':unittest.main()
