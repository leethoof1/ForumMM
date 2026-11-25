import concurrent.futures,json,os,pathlib,sqlite3,subprocess,tempfile,time,unittest,urllib.request,urllib.error
from datetime import datetime
import server
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Shop(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.state=pathlib.Path(cls.tmp.name)
  data=json.loads((ROOT/'data.json').read_text());cls.product=data['products'][0]
  cls.product['stock']={'total':3,'initial':2,'release_at':'2030-11-27T14:30:00+03:00'}
  cls.path=cls.state/'catalog.json';cls.path.write_text(json.dumps(data))
  cls.env={**os.environ,'FORUM_STATE_DIR':cls.tmp.name,'FORUM_SECURE_COOKIE':'0','FORUM_IP_GUARD':'1','FORUM_TRUST_PROXY':'1','FORUM_CATALOG_PATH':str(cls.path)}
  cls.proc=subprocess.Popen(['python3','server.py','--host','127.0.0.1','--port','8012'],cwd=ROOT,env=cls.env,stdout=subprocess.DEVNULL)
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:8012/api/state');break
   except OSError:time.sleep(.05)
 @classmethod
 def tearDownClass(cls):cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
 def setUp(self):
  with self.db() as db:
   for table in ['exchanges','session_products','ip_products','ip_codes','ip_attempts','code_uses','redeem_codes','attempts','delivery_attempts']:db.execute('DELETE FROM '+table)
   db.execute('UPDATE sessions SET balance=0')
 def db(self):return sqlite3.connect(self.state/'progress.sqlite3')
 def client(self,ip):
  req=urllib.request.Request('http://127.0.0.1:8012/api/state',headers={'X-Real-IP':ip})
  r=urllib.request.urlopen(req);cookie=r.headers['Set-Cookie'].split(';')[0]
  with self.db() as db:db.execute('UPDATE sessions SET balance=6 WHERE id=?',(cookie.split('=')[1],))
  return ip,cookie
 def req(self,client,path='state',body=None):
  req=urllib.request.Request('http://127.0.0.1:8012/api/'+path,data=json.dumps(body).encode() if body else None,headers={'X-Forum-Request':'1','X-Real-IP':client[0],'Cookie':client[1],'Content-Type':'application/json'})
  try:r=urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:r=e
  return r.status,json.load(r)
 def buy(self,c,key):return self.req(c,'exchange',dict(product='kit',request=key))
 def test_no_oversell_and_delivery_counter(self):
  clients=[self.client('198.51.100.'+str(i)) for i in range(1,9)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda t:self.buy(t[1],'purchase-key-'+str(t[0])),enumerate(clients)))
  self.assertEqual(sum(s==200 for s,_ in results),2)
  idx=next(i for i,r in enumerate(results) if r[0]==200);winner=clients[idx]
  state=self.req(winner)[1];stock=state['shop']['kit']['stock']
  self.assertEqual((stock['available'],stock['reserved'],stock['remaining']),(0,2,3))
  receipt=state['history'][0]['receipt'];secret=(self.state/'delivery-code.txt').read_text()
  status,data=self.req(winner,'receive',dict(receipt=receipt,confirmation=secret))
  self.assertEqual(status,200);stock=data['shop']['kit']['stock']
  self.assertEqual((stock['issued'],stock['remaining'],stock['reserved'],stock['available']),(1,2,1,0))
  with self.db() as db:
   after=server.inventory(db,self.product,datetime.fromisoformat('2030-11-27T14:30:00+03:00'))
  self.assertEqual(after['available'],1)
 def test_one_product_session_and_ip(self):
  first=self.client('198.51.100.20');self.assertEqual(self.buy(first,'first-request')[0],200)
  self.assertEqual(self.buy(first,'first-request')[0],200)
  self.assertEqual(self.buy(first,'second-request')[0],409)
  self.assertEqual(self.buy(('198.51.100.99',first[1]),'changed-ip-request')[0],409)
  second=self.client(first[0]);self.assertEqual(self.buy(second,'another-request')[0],409)
  self.assertTrue(self.req(second)[1]['shop']['kit']['purchased'])
  self.assertEqual(self.req(second)[1]['balance'],6)
 def test_code_cannot_repeat_in_other_browser_same_ip(self):
  with self.db() as db:db.execute("INSERT INTO redeem_codes(digest,task,batch,created,max_uses) VALUES(?,'*','test',0,600)",(server.code_digest('ПРИМЕР'),))
  first=self.client('198.51.100.30');second=self.client(first[0]);other=self.client('198.51.100.31')
  self.assertEqual(self.req(first,'redeem',{'code':'пример'})[0],200)
  self.assertEqual(self.req(first,'redeem',{'code':'пример'})[1]['balance'],7)
  self.assertEqual(self.req(second,'redeem',{'code':'пример'})[0],409)
  self.assertEqual(self.req(other,'redeem',{'code':'пример'})[0],200)
  with self.db() as db:
   hashes=[r[0] for r in db.execute('SELECT ip FROM ip_codes')]
  self.assertTrue(all(len(x)==64 and '198.51' not in x for x in hashes))
 def test_release_boundary(self):
  with self.db() as db:
   before=server.inventory(db,self.product,datetime.fromisoformat('2030-11-27T14:29:59+03:00'))
   after=server.inventory(db,self.product,datetime.fromisoformat('2030-11-27T14:30:00+03:00'))
  self.assertEqual((before['available'],after['available']),(2,3))
 def test_stock_rejection_does_not_charge(self):
  clients=[self.client('203.0.113.'+str(i)) for i in range(2)]
  with self.db() as db:
   for i in range(2):db.execute('INSERT INTO exchanges(session,request,product,name,price,created,receipt) VALUES(?,?,?,?,?,?,?)',(clients[i][1].split('=')[1],str(i),'kit','kit',6,0,'receipt-'+str(i)))
  c=self.client('203.0.113.10');status,d=self.buy(c,'out-of-stock')
  self.assertEqual(status,409);self.assertEqual(d['balance'],6);self.assertEqual(len(d['history']),0)
 def test_untrusted_client_cannot_spoof_ip_header(self):
  from unittest.mock import patch
  handler=server.Handler.__new__(server.Handler)
  handler.client_address=('203.0.113.80',12345)
  handler.headers={'X-Real-IP':'198.51.100.1'}
  with patch.object(server,'STATE',self.state),patch.dict(os.environ,{'FORUM_TRUST_PROXY':'1'}):
   a=handler.identity();handler.headers={'X-Real-IP':'198.51.100.2'};self.assertEqual(a,handler.identity())
   handler.client_address=('127.0.0.1',12345)
   b=handler.identity();handler.headers={'X-Real-IP':'198.51.100.3'};self.assertNotEqual(b,handler.identity())
if __name__=='__main__':unittest.main()
