import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
source=Path(__file__).with_name('manage.py').resolve()
spec=importlib.util.spec_from_file_location('lock_manager',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class LifecycleLock(unittest.TestCase):
 def setUp(self):
  self.assertTrue(callable(getattr(m,'vm_operation',None)),'VM mutation guard is missing')
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.patcher=patch.object(m,'ROOT',self.root);self.patcher.start();self.addCleanup(self.patcher.stop)
 def holder(self):
  code="import importlib.util,sys;from pathlib import Path;s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT=Path(sys.argv[2]);\nwith m.vm_operation('restore'):\n print('locked',flush=True)\n sys.stdin.readline()\n"
  process=subprocess.Popen([sys.executable,'-B','-c',code,str(source),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.addCleanup(lambda:process.kill() if process.poll() is None else None)
  self.assertEqual(process.stdout.readline().strip(),'locked')
  return process
 def release(self,p):
  out,err=p.communicate('\n',timeout=3);self.assertEqual(p.returncode,0,err)
 def test_another_process_cannot_enter_any_mutation_and_status_reads_remain_available(self):
  p=self.holder()
  try:
   with patch.object(m,'validate') as validate,patch.object(m,'command') as command,patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','filesChecked':0,'differentFiles':[]}))):
    for method,args in [(m.start,(True,)),(m.stop,()),(m.switch,('improved',True)),(m.restore,(True,m.CURRENT_RECOVERY)),(m.create_current_recovery,()),(m.restore_current_recovery,(m.CURRENT_RECOVERY,))]:
     with self.assertRaisesRegex(RuntimeError,'恢复|正在'):method(*args)
    command.assert_not_called();validate.assert_not_called()
    self.assertEqual(m.deployment_status()['mode'],'improved')
  finally:self.release(p)
 def test_nested_switch_start_and_restore_calls_reuse_the_same_owner_lock(self):
  with m.vm_operation('switch'):
   inode=(self.root/'.vm-operation.lock').stat().st_ino
   with m.vm_operation('start'):
    self.assertEqual((self.root/'.vm-operation.lock').stat().st_ino,inode)
   data=json.loads((self.root/'.vm-operation.lock').read_text());self.assertEqual(data['action'],'switch')
  self.assertEqual((self.root/'.vm-operation.lock').read_text(),'')
 def test_exceptions_release_the_lock_and_preserve_the_lock_inode(self):
  with self.assertRaisesRegex(RuntimeError,'synthetic'):
   with m.vm_operation('stop'):raise RuntimeError('synthetic')
  inode=(self.root/'.vm-operation.lock').stat().st_ino
  with m.vm_operation('start'):pass
  self.assertEqual((self.root/'.vm-operation.lock').stat().st_ino,inode)
 def test_process_exit_releases_the_lock_without_needing_to_delete_metadata(self):
  code="import importlib.util,sys,os;from pathlib import Path;s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT=Path(sys.argv[2]);\nwith m.vm_operation('restore'):os._exit(0)"
  subprocess.run([sys.executable,'-B','-c',code,str(source),str(self.root)],check=True,timeout=3)
  with m.vm_operation('start'):pass
 def test_symbolic_or_public_lock_files_are_rejected(self):
  path=self.root/'.vm-operation.lock';target=self.root/'unrelated';target.write_text('user data');path.symlink_to(target)
  with self.assertRaises((OSError,ValueError)): 
   with m.vm_operation('start'):pass
  self.assertEqual(target.read_text(),'user data');path.unlink();path.write_text('');path.chmod(0o644)
  with self.assertRaises(ValueError):
   with m.vm_operation('start'):pass
 def test_busy_metadata_cannot_echo_arbitrary_content(self):
  p=self.holder()
  try:
   (self.root/'.vm-operation.lock').write_text('{"action":"PRIVATE_CANARY","pid":123}')
   try:
    with m.vm_operation('start'):self.fail('Concurrent lock accepted')
   except RuntimeError as error:self.assertNotIn('PRIVATE_CANARY',str(error))
  finally:self.release(p)
 def test_unexpected_busy_metadata_types_still_return_a_safe_busy_error(self):
  p=self.holder()
  try:
   (self.root/'.vm-operation.lock').write_text('{"action":["PRIVATE_CANARY"]}')
   with self.assertRaisesRegex(RuntimeError,'正在'):
    with m.vm_operation('start'):pass
  finally:self.release(p)
 def test_a_metadata_cleanup_error_still_closes_the_descriptor_and_releases_the_lock(self):
  original=m.os.ftruncate;calls=[]
  def truncate(fd,size):
   calls.append(fd)
   if len(calls)==2:raise OSError('synthetic cleanup failure')
   return original(fd,size)
  with patch.object(m.os,'ftruncate',side_effect=truncate),patch.object(m.os,'close',wraps=m.os.close) as close:
   with self.assertRaisesRegex(OSError,'synthetic'):
    with m.vm_operation('start'):pass
   close.assert_called_once_with(calls[0])
  with m.vm_operation('stop'):pass
if __name__=='__main__':unittest.main()
