import unittest
from tools.configure_capacity import site,global_config
class Capacity(unittest.TestCase):
 def test_preserves_tls_and_write_limits(self):
  original='limit_req_zone $binary_remote_addr zone=forum_api:10m rate=5r/s;\nserver {\n listen 443 ssl;\n ssl_certificate /secret/cert.pem;\n location /api/ { limit_req zone=forum_api burst=30; }\n}\n'
  changed=site(original)
  self.assertIn('ssl_certificate /secret/cert.pem;',changed)
  self.assertIn('limit_req zone=forum_api burst=30;',changed)
  self.assertEqual(changed,site(changed))
  self.assertIn('location = /api/state',changed)
  self.assertNotIn('location / {\n        root',changed)
 def test_connection_limits_only_increase(self):
  self.assertIn('worker_connections 4096;',global_config('events { worker_connections 768; }'))
  original='worker_rlimit_nofile 65536;\nevents { worker_connections 8192; }'
  self.assertEqual(original,global_config(original))
 def test_refuses_unknown_configuration(self):
  with self.assertRaises(ValueError):site('server { location = /api/state {} }')
  with self.assertRaises(ValueError):global_config('events {}')
