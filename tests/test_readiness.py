import unittest
from tools.check_readiness import validate_state
class Readiness(unittest.TestCase):
 def data(self,total):
  return {'data':{'venues':[{}]*6,'products':[{'id':'kit'}]},'shop':{'kit':{'stock':{'total':total,'released':total,'available':total,'remaining':total}}}}
 def test_500_before_release_is_ready(self):validate_state(self.data(500))
 def test_700_after_release_is_ready(self):validate_state(self.data(700))
 def test_invalid_stock_is_rejected(self):
  d=self.data(500);d['shop']['kit']['stock']['available']=501
  with self.assertRaises(AssertionError):validate_state(d)
if __name__=='__main__':unittest.main()
