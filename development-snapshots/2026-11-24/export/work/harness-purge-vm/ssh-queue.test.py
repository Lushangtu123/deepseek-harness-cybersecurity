"""Managed SSH shares one bounded channel without retrying remote commands."""
import concurrent.futures,fcntl,importlib.util,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('queue_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SSHQueue(unittest.TestCase):
 def test_threads_cannot_overlap_and_each_command_runs_once(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   active=peak=0;calls=[];guard=threading.Lock();barrier=threading.Barrier(3)
   def command(argv,**kwargs):
    nonlocal active,peak
    with guard:active+=1;peak=max(peak,active);calls.append(argv[-1])
    try:time.sleep(.05);return subprocess.CompletedProcess(argv,0,'ok','')
    finally:
     with guard:active-=1
   def run(i):barrier.wait(timeout=3);return m.ssh('synthetic-'+str(i),timeout=2)
   with patch.object(m,'command',side_effect=command),concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,range(3)))
   self.assertEqual(peak,1);self.assertCountEqual(calls,['synthetic-'+str(i) for i in range(3)]);self.assertTrue(all(r.stdout=='ok' for r in results))
 def test_independent_processes_share_channel(self):
  code="""import importlib.util,json,subprocess,sys,time
from pathlib import Path
s=importlib.util.spec_from_file_location('child',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT=Path(sys.argv[2]);label=sys.argv[3]
(m.ROOT/('ready-'+label)).touch();deadline=time.monotonic()+5
while not (m.ROOT/'go').exists():
 if time.monotonic()>deadline:raise TimeoutError('Parent did not release workers')
 time.sleep(.005)
def command(argv,**kwargs):
 start=time.monotonic();time.sleep(.1);end=time.monotonic();return subprocess.CompletedProcess(argv,0,json.dumps([start,end]),'')
m.command=command;print(m.ssh('synthetic',timeout=3).stdout)
"""
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);children=[subprocess.Popen([sys.executable,'-B','-c',code,m.__file__,temp,str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(3)]
   try:
    deadline=time.monotonic()+5
    while len(list(root.glob('ready-*')))<3:
     if time.monotonic()>deadline:self.fail('Child readiness deadline')
     time.sleep(.01)
    (root/'go').touch();intervals=[]
    for child in children:
     out,err=child.communicate(timeout=5);self.assertEqual(child.returncode,0,err);intervals.append(json.loads(out))
    intervals.sort();self.assertTrue(all(a[1]<=b[0] for a,b in zip(intervals,intervals[1:])),intervals)
   finally:
    for child in children:
     if child.poll() is None:child.kill()
     child.communicate(timeout=3)
 def test_queue_timeout_means_not_sent_and_is_recorded_without_payload(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   fd=os.open(Path(temp)/'.ssh-channel.lock',os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with patch.object(m,'command') as command:
     started=time.monotonic()
     with self.assertRaises(subprocess.TimeoutExpired) as caught:m.ssh('PRIVATE-COMMAND',input='PRIVATE-INPUT',timeout=.08,phase='program-update')
     self.assertLess(time.monotonic()-started,.6);command.assert_not_called()
     self.assertIn('not sent',str(caught.exception));self.assertNotIn('outcome unconfirmed',str(caught.exception))
    row=m.ssh_diagnostics()[-1];self.assertEqual(row['reason'],'queue-timeout');self.assertEqual(row['trace']['transportStage'],'queue');self.assertNotIn('PRIVATE',json.dumps(row));self.assertNotIn('PRIVATE',str(caught.exception))
   finally:os.close(fd)
 def test_queue_wait_consumes_execution_budget(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   fd=os.open(Path(temp)/'.ssh-channel.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   timer=threading.Timer(.12,lambda:fcntl.flock(fd,fcntl.LOCK_UN));timer.start()
   try:
    with patch.object(m,'command',return_value=subprocess.CompletedProcess([],0,'','')) as command:m.ssh('synthetic',timeout=.5)
    budget=command.call_args.kwargs['timeout'];self.assertGreater(budget,0);self.assertLess(budget,.43)
   finally:timer.join(timeout=1);os.close(fd)
 def test_unsafe_lock_files_fail_before_execution(self):
  for kind in ['symlink','hardlink','public','fifo']:
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command') as command:
    root=Path(temp);lock=root/'.ssh-channel.lock';target=root/'untouched';target.write_text('sentinel');target.chmod(0o600)
    if kind=='symlink':lock.symlink_to(target)
    elif kind=='hardlink':os.link(target,lock)
    elif kind=='public':lock.touch(mode=0o644)
    else:os.mkfifo(lock,0o600)
    with self.assertRaises((ValueError,OSError)):m.ssh('PRIVATE',timeout=.1)
    command.assert_not_called();self.assertEqual(target.read_text(),'sentinel')
 def test_invalid_timeout_rejected_before_execution(self):
  for value in [0,-1,True,float('inf'),float('nan'),'2']:
   with self.subTest(value=value),patch.object(m,'command') as command:
    with self.assertRaises(ValueError):m.ssh('PRIVATE',timeout=value)
    command.assert_not_called()
 def test_os_timeout_from_executor_is_not_misreported_as_not_sent(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=TimeoutError('executor timeout')) as command:
   with self.assertRaises(Exception) as caught:m.ssh('synthetic',timeout=1)
   self.assertIsInstance(caught.exception,TimeoutError);self.assertFalse(hasattr(caught.exception,'trace'));self.assertEqual(command.call_count,1)
 def test_clock_read_excludes_channel_wait(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   fd=os.open(Path(temp)/'.ssh-channel.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   timer=threading.Timer(.18,lambda:fcntl.flock(fd,fcntl.LOCK_UN));timer.start()
   try:
    with patch.object(m,'command',side_effect=lambda argv,**kw:subprocess.CompletedProcess(argv,0,str(time.time()),'')):offset=m.measure_guest_clock()
    self.assertLess(abs(offset),.04)
   finally:timer.join(timeout=1);os.close(fd)
 def test_clock_set_builds_epoch_after_channel_wait(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)):
   fd=os.open(Path(temp)/'.ssh-channel.lock',os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);epoch=[1000]
   def release():epoch[0]=2000;fcntl.flock(fd,fcntl.LOCK_UN)
   timer=threading.Timer(.08,release);timer.start()
   try:
    with patch.object(m,'measure_guest_clock',side_effect=[100,0]),patch.object(m.time,'time',side_effect=lambda:epoch[0]),patch.object(m,'command',return_value=subprocess.CompletedProcess([],0,'','')) as command:result=m.synchronize_clock()
    self.assertTrue(result['adjusted']);self.assertIn('--set=@2000.000000',command.call_args.args[0][-1])
   finally:timer.join(timeout=1);os.close(fd)
 def test_sigterm_cleans_active_child_before_channel_is_released(self):
  code="""import importlib.util,subprocess,sys
from pathlib import Path
s=importlib.util.spec_from_file_location('child',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.ROOT=Path(sys.argv[2]);original=m.command
program="import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(20)"
def command(argv,**kwargs):return original([sys.executable,'-c',program,str(m.ROOT/'child-pid')],**kwargs)
m.command=command;m.ssh('synthetic',timeout=10)
"""
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);controller=subprocess.Popen([sys.executable,'-B','-c',code,m.__file__,temp],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);child=None
   try:
    deadline=time.monotonic()+4
    while not (root/'child-pid').is_file():
     if time.monotonic()>deadline:self.fail('Synthetic child did not start')
     time.sleep(.01)
    child=int((root/'child-pid').read_text());controller.terminate();controller.communicate(timeout=3)
    fd=os.open(root/'.ssh-channel.lock',os.O_RDWR)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:os.close(fd)
    status=subprocess.run(['ps','-p',str(child),'-o','stat='],capture_output=True,text=True,timeout=2).stdout.strip();self.assertTrue(not status or status.startswith('Z'),'SSH stand-in survived controller SIGTERM')
   finally:
    if controller.poll() is None:controller.kill()
    if child is not None:
     try:os.kill(child,9)
     except ProcessLookupError:pass
    controller.communicate(timeout=3)
 def test_failure_releases_channel_without_replaying_command(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(m,'ROOT',Path(temp)),patch.object(m,'command',side_effect=[subprocess.CalledProcessError(9,['ssh'],stderr='PRIVATE'),subprocess.CompletedProcess([],0,'next','')]) as command:
   with self.assertRaises(subprocess.CalledProcessError):m.ssh('first',timeout=1)
   self.assertEqual(m.ssh('second',timeout=1).stdout,'next');self.assertEqual(command.call_count,2)

if __name__=='__main__':unittest.main()
