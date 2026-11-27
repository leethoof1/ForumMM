import csv,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server
from tools.manage_codes import import_pool
from tools.reset_progress import reset
class FirstWords(unittest.TestCase):
 def test_migration_reimport_and_reset(self):
  with tempfile.TemporaryDirectory() as directory,patch.object(server,'STATE',Path(directory)):
   server.initialize()
   rows=[]
   with server.connect() as db:
    for i in range(100):
     word=server.FIRST_MOVEMENT_WORDS[i-84] if 84<=i<92 else 'ТЕСТ'+str(i)
     limit=600 if i<5 else 100 if i<20 else 5
     rows.append(dict(code=word,max_uses=limit,batch='test'))
     db.execute("INSERT INTO redeem_codes(digest,task,batch,created,max_uses) VALUES(?,'*','test',0,?)",(server.code_digest(word),limit))
    db.execute("INSERT INTO sessions VALUES('participant',3)")
    db.execute("INSERT INTO code_uses VALUES(?,'participant',0)",(server.code_digest('ПЕРВЫЕ'),))
    db.execute("INSERT INTO exchanges(session,request,product,name,price,created,receipt) VALUES('participant','request','bag','Шоппер',6,0,'receipt')")
   server.initialize()
   with server.connect() as db:
    self.assertEqual(db.execute('SELECT count(*) FROM redeem_codes WHERE max_uses=50').fetchone()[0],8)
    self.assertEqual(db.execute('SELECT count(*) FROM code_uses').fetchone()[0],1)
   source=Path(directory)/'codes.csv'
   with source.open('w') as f:
    writer=csv.DictWriter(f,fieldnames=['code','max_uses','batch']);writer.writeheader();writer.writerows(rows)
   import_pool(source)
   backup=reset()
   self.assertTrue(backup.exists())
   with server.connect() as db:
    self.assertEqual(db.execute('SELECT count(*) FROM code_uses').fetchone()[0],0)
    self.assertEqual(db.execute('SELECT count(*) FROM exchanges').fetchone()[0],0)
    self.assertEqual(db.execute('SELECT sum(balance) FROM sessions').fetchone()[0],0)
    self.assertEqual(db.execute('SELECT count(*) FROM redeem_codes WHERE max_uses=50').fetchone()[0],8)
    self.assertEqual(db.execute('SELECT count(*) FROM redeem_codes').fetchone()[0],100)
