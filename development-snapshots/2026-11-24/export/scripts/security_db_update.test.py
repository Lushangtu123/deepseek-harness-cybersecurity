import hashlib,importlib.util,io,json
from pathlib import Path
import tarfile,tempfile,unittest

class DatabaseUpdateTests(unittest.TestCase):
 def module(self):
  path=Path(__file__).with_name('security_db_update.py');self.assertTrue(path.exists(),'Manual database updater is missing');spec=importlib.util.spec_from_file_location('db_update_fixture',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def bundle(self,folder,entries):
  p=folder/'database.tar.gz'
  with tarfile.open(p,'w:gz') as out:
   for name,value,kind in entries:
    item=tarfile.TarInfo(name);item.type=kind
    if kind==tarfile.REGTYPE:item.size=len(value);out.addfile(item,io.BytesIO(value))
    else:item.linkname='outside';out.addfile(item)
  return p
 def test_exact_regular_archive_entries_validate_metadata_and_hashes(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as directory:
   folder=Path(directory);metadata={'Version':2,'UpdatedAt':'2026-10-29T19:00:00.123456789Z','NextUpdate':'2026-10-30T19:00:00Z'};db=b'B'*4096;p=self.bundle(folder,[('metadata.json',json.dumps(metadata).encode(),tarfile.REGTYPE),('trivy.db',db,tarfile.REGTYPE)]);digest=hashlib.sha256(p.read_bytes()).hexdigest();result=m.unpack_verified(p,folder/'verified',digest,now='2026-10-29T22:00:00Z');self.assertEqual(result['fileSha256'],hashlib.sha256(db).hexdigest());self.assertEqual(result['fileBytes'],len(db));self.assertEqual(result['metadata'],metadata)
 def test_traversal_links_duplicate_and_unexpected_entries_are_rejected(self):
  m=self.module();meta=json.dumps({'Version':2,'UpdatedAt':'2026-10-29T19:00:00Z','NextUpdate':'2026-10-30T19:00:00Z'}).encode()
  for extra in [('../outside',b'x',tarfile.REGTYPE),('trivy.db',b'x',tarfile.SYMTYPE),('metadata.json',meta,tarfile.REGTYPE),('unexpected',b'x',tarfile.REGTYPE)]:
   with self.subTest(extra=extra[0]),tempfile.TemporaryDirectory() as directory:
    folder=Path(directory);p=self.bundle(folder,[('metadata.json',meta,tarfile.REGTYPE),('trivy.db',b'B'*4096,tarfile.REGTYPE),extra]);digest=hashlib.sha256(p.read_bytes()).hexdigest()
    with self.assertRaises(ValueError):m.unpack_verified(p,folder/'verified',digest,now='2026-10-29T22:00:00Z')
    self.assertFalse((folder.parent/'outside').exists())
 def test_checksum_and_numeric_or_impossible_timestamps_are_rejected(self):
  m=self.module()
  for updated,next_at in [(2026,2027),('2026-10-29','2026-10-30'),('2026-02-30T00:00:00Z','2026-03-02T00:00:00Z'),('2030-01-01T00:00:00Z','2030-01-02T00:00:00Z')]:
   with tempfile.TemporaryDirectory() as directory:
    folder=Path(directory);p=self.bundle(folder,[('metadata.json',json.dumps({'Version':2,'UpdatedAt':updated,'NextUpdate':next_at}).encode(),tarfile.REGTYPE),('trivy.db',b'B'*4096,tarfile.REGTYPE)]);digest=hashlib.sha256(p.read_bytes()).hexdigest()
    with self.assertRaises(ValueError):m.unpack_verified(p,folder/'verified',digest,now='2026-10-29T22:00:00Z')
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'bad';p.write_bytes(b'x')
   with self.assertRaises(ValueError):m.unpack_verified(p,Path(directory)/'verified','0'*64,now='2026-10-29T22:00:00Z')
 def test_hidden_pax_headers_are_rejected_before_consuming_their_payload(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as directory:
   folder=Path(directory);p=folder/'database.tar.gz'
   with tarfile.open(p,'w:gz',format=tarfile.PAX_FORMAT) as out:
    item=tarfile.TarInfo('trivy.db');item.size=4096;item.pax_headers={'comment':'x'*65536};out.addfile(item,io.BytesIO(b'B'*4096))
    meta=json.dumps({'Version':2,'UpdatedAt':'2026-10-29T19:00:00Z','NextUpdate':'2026-10-30T19:00:00Z'}).encode();item=tarfile.TarInfo('metadata.json');item.size=len(meta);out.addfile(item,io.BytesIO(meta))
   with self.assertRaises(ValueError):m.unpack_verified(p,folder/'verified',hashlib.sha256(p.read_bytes()).hexdigest(),now='2026-10-29T22:00:00Z')
 def test_deadline_interrupts_a_blocking_response_read_and_restores_signal_state(self):
  m=self.module()
  import time
  from unittest.mock import patch
  timer=m.signal.setitimer;handler=m.signal.getsignal(m.signal.SIGALRM)
  class Response:
   headers={}
   def __enter__(self):return self
   def __exit__(self,*args):return False
   def read(self,size):time.sleep(.3);return b''
  class Client:
   def open(self,*args,**kwargs):return Response()
  def short_timer(kind,seconds,*args):return timer(kind,.03 if seconds==180 else seconds,*args)
  started=time.monotonic()
  with patch.object(m.signal,'setitimer',short_timer),self.assertRaises(TimeoutError):m.fetch(Client(),'https://ghcr.io/test')
  self.assertLess(time.monotonic()-started,.2);self.assertEqual(m.signal.getsignal(m.signal.SIGALRM),handler);self.assertEqual(m.signal.getitimer(m.signal.ITIMER_REAL),(0.,0.))
 def test_registry_redirect_strips_anonymous_auth_and_rejects_non_registry_hosts(self):
  m=self.module();handler=m.PublicRegistryRedirect();request=m.urllib.request.Request('https://ghcr.io/v2/aquasecurity/trivy-db/blobs/sha256:abc',headers={'Authorization':'Bearer ANONYMOUS_TEST_CANARY'})
  redirected=handler.redirect_request(request,None,302,'found',{},'https://pkg-containers.githubusercontent.com/ghcr1/blobs/sha256:abc');self.assertIsNone(redirected.get_header('Authorization'))
  for url in ['http://ghcr.io/file','https://127.0.0.1/file','https://ghcr.io:8443/file','https://ghcr.io.evil.invalid/file']:
   with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'found',{},url)

 def test_unverified_new_database_is_only_reported_and_never_transferred(self):
  from unittest.mock import Mock,patch
  m=self.module();manager=Mock()
  current={'maintenance':None,'database':{'digest':'sha256:'+'a'*64},'ready':True,'idle':True}
  remote={'digest':'sha256:'+'b'*64,'layerDigest':'sha256:'+'c'*64}
  with patch.object(m.sys,'platform','darwin'),patch.object(m,'query_guest',return_value=current),patch.object(m,'public_manifest',return_value=(None,None,remote)),patch.object(m,'fetch') as fetch,patch.object(m,'send_bundle') as send:
   result=m.run_update(check_only=True,manager=manager)
   self.assertEqual(result['publisherAdmission'],'unverified')
   with self.assertRaisesRegex(m.UpdateNotice,'发布者'):
    m.run_update(manager=manager)
   fetch.assert_not_called();send.assert_not_called();manager.vm_operation.assert_not_called()
 def test_generated_guest_rejects_digest_or_layer_mismatch_before_receiving_archive(self):
  import subprocess,sys
  m=self.module()
  digest,layer='sha256:'+'b'*64,'sha256:'+'c'*64
  for pins in [frozenset(),frozenset({(digest,'sha256:'+'d'*64)})]:
   m.VERIFIED_DATABASE_PUBLISHER_PINS=pins
   source=m.guest_source({'action':'update','identity':{'digest':digest,'layerDigest':layer}})
   child=subprocess.run([sys.executable,'-B','-c',source],input='',text=True,capture_output=True,timeout=5)
   self.assertNotEqual(child.returncode,0)
   self.assertIn('Database publisher evidence missing',child.stderr)
   self.assertNotIn('Dedicated improved VM required',child.stderr)
if __name__=='__main__':unittest.main()
