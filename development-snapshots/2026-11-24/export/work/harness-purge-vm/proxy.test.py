import unittest,importlib.util,socket,sys,threading,time,subprocess
from unittest.mock import patch
from pathlib import Path
spec=importlib.util.spec_from_file_location('egress',Path(__file__).with_name('egress_proxy.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class ProxyPolicy(unittest.TestCase):
 def test_kali_tunnel_needs_no_child_process_or_dns(self):
  with patch.object(subprocess,'run',side_effect=BlockingIOError(35,'Process limit')) as spawn,patch.object(socket,'getaddrinfo',side_effect=AssertionError('No DNS for Kali')),patch.object(socket,'socket') as fake:
   self.assertIs(mod.connect_tunnel('kali.harness.internal',443),fake.return_value)
   fake.return_value.connect.assert_called_once_with(('192.168.64.7',22))
   spawn.assert_not_called()
 def test_kali_socket_failure_closes_without_fallback(self):
  with patch.object(socket,'socket') as fake,patch.object(mod,'connect_public') as public:
   fake.return_value.connect.side_effect=ConnectionRefusedError('Kali stopped')
   with self.assertRaises(ConnectionRefusedError):mod.connect_tunnel('kali.harness.internal',443)
   fake.return_value.close.assert_called_once();public.assert_not_called()
 def test_only_exact_kali_tunnel_maps_to_guest_ssh(self):
  connect=getattr(mod,'connect_tunnel',None);self.assertTrue(callable(connect),'Dedicated CONNECT route missing')
  with patch.object(socket,'socket') as fake,patch.object(mod,'connect_public',return_value='public') as public:
   self.assertIs(connect('kali.harness.internal',443),fake.return_value)
   fake.return_value.connect.assert_called_once_with(('192.168.64.7',22))
   self.assertEqual(connect('api.deepseek.com',443),'public');public.assert_called_once_with('api.deepseek.com',443)
  for host,port in [('kali.harness.internal',22),('kali.harness.internal.evil.example',443),('192.168.64.7',443),('kali.harness.internal.',443)]:
   with self.assertRaises(ValueError):connect(host,port)
  with self.assertRaises(ValueError):mod.validate_authority('kali.harness.internal',80)
 def test_connect_handler_routes_only_well_formed_authorities(self):
  connect=getattr(mod,'connect_tunnel',None);self.assertTrue(callable(connect),'Dedicated CONNECT route missing')
  for authority,allowed in [('kali.harness.internal:443',True),('kali.harness.internal:22',False),('user@kali.harness.internal:443',False),('kali.harness.internal:443/path',False),('kali.harness.internal:443?x',False),('kali.harness.internal:443#x',False)]:
   client,handler=socket.socketpair();client.settimeout(2);errors=[]
   def serve():
    try:mod.Handler(handler,('127.0.0.1',0),object())
    except BaseException as error:errors.append(error)
    finally:handler.close()
   with patch.object(mod,'connect_tunnel',return_value=object()) as route,patch.object(mod,'relay'),patch.object(mod,'connect_public',side_effect=AssertionError('Wrong route')):
    # close() is required on the fake upstream.
    route.return_value=unittest.mock.Mock()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    try:
     client.sendall(('CONNECT '+authority+' HTTP/1.0\r\n\r\n').encode());chunks=[]
     while True:
      chunk=client.recv(4096)
      if not chunk:break
      chunks.append(chunk)
     response=b''.join(chunks)
     self.assertIn(b' 200 ' if allowed else b' 403 ',response)
     self.assertEqual(route.called,allowed)
    finally:client.close();thread.join(2);handler.close()
    self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
 def test_only_observed_docker_registry_origins_added(self):
  for host in ['auth.docker.io','registry-1.docker.io','production.cloudfront.docker.com']:
   self.assertEqual(mod.validate_authority(host,443),(host,443))
  for host in ['evil.docker.io','production.cloudfront.docker.com.evil.example','anything.cloudflarestorage.com']:
   with self.assertRaises(ValueError):mod.validate_authority(host,443)
 def test_exact_host_only(self):
  for host in ['localhost','127.0.0.1','::1','10.0.2.2','api.deepseek.com.evil.example','evilapi.deepseek.com','registry.npmjs.org@localhost']:
   with self.assertRaises(ValueError):mod.validate_authority(host,443)
  self.assertEqual(mod.validate_authority('api.deepseek.com',443),('api.deepseek.com',443))
 def test_ports_closed(self):
  for port in [22,3080,49222,1,65535]:
   with self.assertRaises(ValueError):mod.validate_authority('api.deepseek.com',port)
 def test_dns_rebinding_and_non_global_denied(self):
  for ip in ['127.0.0.1','10.0.0.1','172.16.0.1','192.168.1.1','169.254.169.254','0.0.0.0','::1','fe80::1','fc00::1','224.0.0.1','ff02::1']:
   with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
    with self.assertRaises(ValueError):mod.public_addresses('api.deepseek.com',443)
 def test_mixed_public_private_dns_fails_closed(self):
  with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('1.1.1.1',443)),(2,1,6,'',('127.0.0.1',443))]):
   with self.assertRaises(ValueError):mod.public_addresses('api.deepseek.com',443)
 def test_connect_uses_validated_numeric_address(self):
  info=[(2,1,6,'',('1.1.1.1',443))]
  with patch.object(socket,'getaddrinfo',return_value=info),patch.object(socket,'socket') as fake:
   mod.connect_public('api.deepseek.com',443);fake.return_value.connect.assert_called_once_with(('1.1.1.1',443))
 def test_http_delayed_client_bytes_never_reach_origin(self):
  client,handler=socket.socketpair();origin,upstream=socket.socketpair();origin.settimeout(.25)
  errors=[]
  def serve():
   try:mod.Handler(handler,('127.0.0.1',0),object())
   except Exception as e:errors.append(type(e).__name__)
  with patch.object(mod,'connect_public',return_value=upstream):
   thread=threading.Thread(target=serve,daemon=True);thread.start()
   try:
    client.sendall(b'GET http://nodejs.org/file HTTP/1.0\r\nHost: nodejs.org\r\n\r\n');self.assertIn(b'GET /file',origin.recv(4096));client.sendall(b'POST /unexpected HTTP/1.0\r\nContent-Length: 1\r\n\r\nx')
    with self.assertRaises(TimeoutError):origin.recv(4096)
   finally:client.close();origin.close();thread.join(1);handler.close();upstream.close()
 def test_absolute_header_deadline_defeats_slow_drips(self):
  client,handler=socket.socketpair();done=threading.Event()
  def serve():
   try:mod.Handler(handler,('127.0.0.1',0),object())
   except (OSError,ValueError):pass
   finally:done.set()
  with patch.object(mod,'HEADER_SECONDS',.12,create=True):
   thread=threading.Thread(target=serve,daemon=True);thread.start()
   try:
    for _ in range(9):
     try:client.sendall(b'G')
     except OSError:break
     time.sleep(.03)
    self.assertTrue(done.wait(.1),'absolute parsing deadline did not close a drip-fed request')
   finally:client.close();handler.close();thread.join(.2)
if __name__=='__main__':unittest.main()
