import concurrent.futures,json,os,pathlib,sqlite3,subprocess,tempfile,time,unittest,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Merch(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.state=pathlib.Path(cls.tmp.name)
  data=json.loads((ROOT/'data.json').read_text())
  for p in data['products']:p['stock']={'total':3,'initial':2,'release_at':'2030-11-27T14:00:00+03:00'}
  path=cls.state/'catalog.json';path.write_text(json.dumps(data))
  env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name,'FORUM_CATALOG_PATH':str(path),'FORUM_TRUST_PROXY':'1','FORUM_IP_GUARD':'1','FORUM_SECURE_COOKIE':'0'}
  cls.proc=subprocess.Popen(['python3','server.py','--port','8014','--host','127.0.0.1'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL)
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:8014/api/state');break
   except OSError:time.sleep(.05)
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def setUp(self):
  with self.db() as db:
   for t in ['exchanges','session_products','ip_products']:db.execute('DELETE FROM '+t)
 def db(self):return sqlite3.connect(self.state/'progress.sqlite3')
 def client(self,ip):
  r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8014/api/state',headers={'X-Real-IP':ip}));cookie=r.headers['Set-Cookie'].split(';')[0]
  with self.db() as db:db.execute('UPDATE sessions SET balance=20 WHERE id=?',(cookie.split('=')[1],))
  return ip,cookie
 def req(self,c,path='state',body=None):
  request=urllib.request.Request('http://127.0.0.1:8014/api/'+path,data=json.dumps(body).encode() if body else None,headers={'X-Forum-Request':'1','Content-Type':'application/json','X-Real-IP':c[0],'Cookie':c[1]})
  try:r=urllib.request.urlopen(request)
  except urllib.error.HTTPError as e:r=e
  return r.status,json.load(r)
 def buy(self,c,p,key):return self.req(c,'exchange',dict(product=p,request=key))
 def oldkit(self,c):
  sid=c[1].split('=')[1]
  with self.db() as db:
   db.execute("INSERT INTO exchanges(session,request,product,name,price,created,receipt) VALUES(?,'legacy-kit','kit','Набор',10,0,'LEGACYKIT')",(sid,))
   db.execute("INSERT INTO session_products VALUES(?,'kit')",(sid,))
 def test_three_items_prices_independent_claims_and_fulfillment(self):
  c=self.client('198.51.100.111');d=self.req(c)[1]
  self.assertEqual([(p['id'],p['price']) for p in d['data']['products']],[('pen',2),('notebook',4),('bag',6)])
  for p in ['pen','notebook','bag']:
   self.assertEqual(self.buy(c,p,'buy-'+p+'-first')[0],200)
   self.assertEqual(self.buy(c,p,'buy-'+p+'-second')[0],409)
  d=self.req(c)[1];self.assertEqual(d['balance'],8)
  other=self.client(c[0]);self.assertTrue(all(x['purchased'] for x in self.req(other)[1]['shop'].values()))
  self.assertEqual(self.buy(other,'pen','new-browser')[0],409)
  receipt=next(h['receipt'] for h in d['history'] if h['product']=='pen');key=(self.state/'delivery-code.txt').read_text()
  status,d=self.req(c,'receive',dict(receipt=receipt,confirmation=key));self.assertEqual(status,200)
  self.assertEqual(d['shop']['pen']['stock']['issued'],1)
  self.assertEqual(d['shop']['bag']['stock']['issued'],0)
 def test_old_kit_reserves_each_component_and_blocks_duplicates(self):
  c=self.client('198.51.100.112');self.oldkit(c)
  d=self.req(c)[1]
  for p in ['pen','notebook','bag']:
   self.assertTrue(d['shop'][p]['purchased']);self.assertEqual(d['shop'][p]['stock']['available'],1)
   self.assertEqual(self.buy(c,p,'legacy-repeat-'+p)[0],409)
  key=(self.state/'delivery-code.txt').read_text()
  for _ in range(2):self.assertEqual(self.req(c,'receive',dict(receipt='LEGACYKIT',confirmation=key))[0],200)
  for s in self.req(c)[1]['shop'].values():self.assertEqual(s['stock']['issued'],1)
 def test_concurrent_pen_sales_respect_old_kit_reservation(self):
  old=self.client('198.51.100.113');self.oldkit(old)
  clients=[self.client('203.0.113.'+str(i)) for i in range(1,6)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
   results=list(pool.map(lambda item:self.buy(item[1],'pen','pen-request-'+str(item[0])),enumerate(clients)))
  self.assertEqual(sum(status==200 for status,_ in results),1)
if __name__=='__main__':unittest.main()
