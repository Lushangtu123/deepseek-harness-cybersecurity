"""Exercise the actual relay lifecycle with local SSH stand-ins and real processes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import shutil
import signal
import subprocess
import sys
import unittest


RELAY = Path(__file__).resolve().parents[1] / 'harness_acceptance_relay.py'
FAKE_SSH = '''
from pathlib import Path
import os,signal,socket,sys,time
control=Path(sys.argv[1])
if sys.argv[2]=='stubborn':signal.signal(signal.SIGTERM,signal.SIG_IGN)
listener=socket.socket(socket.AF_UNIX)
listener.bind(str(control));os.chmod(control,0o600);listener.listen()
while True:time.sleep(.1)
'''
DRIVER = '''
from pathlib import Path
import importlib.util,json,os,runpy,signal,socket,subprocess,sys,threading,time
fixture=Path(sys.argv[1]);relay=sys.argv[2];mode=sys.argv[3]
original_spec=importlib.util.spec_from_file_location
def spec(name,location,*args,**kwargs):
    if name=='harness_manager':location=fixture/'manager.py'
    return original_spec(name,location,*args,**kwargs)
importlib.util.spec_from_file_location=spec
original_popen=subprocess.Popen
owned_children=[]
class UnconfirmedChild:
    def __init__(self,process):
        self.process=process;self.pid=process.pid
    def poll(self):return None
    def terminate(self):self.process.terminate()
    def kill(self):self.process.kill()
    def wait(self,timeout=None):raise subprocess.TimeoutExpired('synthetic unconfirmed child',timeout)
def popen(argv,*args,**kwargs):
    if argv[0]=='/usr/bin/ssh' and '-M' in argv:
        control=argv[argv.index('-S')+1]
        child=original_popen([sys.executable,str(fixture/'fake-ssh.py'),control,mode],*args,**kwargs)
        (fixture/'owned-master.json').write_text(json.dumps({'pid':child.pid,'control':control}))
        return child
    if argv[0]=='/usr/bin/ssh' and mode in ['connections','queue-timeout','queue-disconnect','queue-stop'] and '-O' not in argv:
        child=original_popen([sys.executable,'-c','import time;time.sleep(30)'],*args,**kwargs)
        owned_children.append(child)
        return child
    return original_popen(argv,*args,**kwargs)
subprocess.Popen=popen
original_run=subprocess.run
def run(argv,*args,**kwargs):
    if argv[0]=='/usr/bin/ssh' and '-O' in argv:
        return subprocess.CompletedProcess(argv,0,b'',b'')
    return original_run(argv,*args,**kwargs)
subprocess.run=run
original_write=Path.write_text
def write(path,text,*args,**kwargs):
    result=original_write(path,text,*args,**kwargs)
    if path.name=='mux-lifecycle.json' and mode.startswith('queue-'):
        sys._getframe(1).f_globals['ADMISSION_TIMEOUT']=.4
    if mode=='interrupt' and path.name=='mux-lifecycle.json' and not json.loads(text)['stopped']:
        os.kill(os.getpid(),signal.SIGTERM)
    if path.name=='relay-url.txt' and mode=='unconfirmed-child':
        frame=sys._getframe(1)
        child=original_popen([sys.executable,'-c','import time;time.sleep(30)'])
        owned_children.append(child)
        frame.f_globals['children'].add(UnconfirmedChild(child))
        (fixture/'unconfirmed-pid.json').write_text(json.dumps({'pid':child.pid}))
    if path.name=='relay-url.txt' and mode=='connections':
        from urllib.parse import urlsplit
        port=urlsplit(text.strip()).port
        sockets=[]
        try:
            for _ in range(24):
                connection=socket.create_connection(('127.0.0.1',port),timeout=2)
                sockets.append(connection)
            samples=[]
            deadline=time.monotonic()+.6
            while time.monotonic()<deadline:
                samples.append(sum('process_request_thread' in t.name for t in threading.enumerate()))
                time.sleep(.02)
            (fixture/'connection-observation.json').write_text(json.dumps({'maxHandlerThreads':max(samples),'attempted':len(sockets)}))
        finally:
            for connection in sockets:connection.close()
    if path.name=='relay-url.txt' and mode.startswith('queue-'):
        from urllib.parse import urlsplit
        port=urlsplit(text.strip()).port
        sockets=[socket.create_connection(('127.0.0.1',port),timeout=2) for _ in range(8)]
        waiting=None
        try:
            deadline=time.monotonic()+2
            while len(owned_children)<8 and time.monotonic()<deadline:time.sleep(.01)
            if len(owned_children)!=8:raise AssertionError('Eight occupied channels not established')
            waiting=socket.create_connection(('127.0.0.1',port),timeout=2)
            waiting.sendall(b'GET /queued HTTP/1.1\\r\\nHost: localhost\\r\\n\\r\\n')
            if mode=='queue-disconnect':waiting.close();waiting=None
            if mode=='queue-stop':
                time.sleep(.05);sys._getframe(1).f_globals['stopping'].set()
            reason={'queue-timeout':'timeout','queue-disconnect':'client-disconnected','queue-stop':'stopping'}[mode]
            deadline=time.monotonic()+1.5;found=False
            while time.monotonic()<deadline:
                traces=fixture/'relay-mux-traces.jsonl'
                rows=[json.loads(line) for line in traces.read_text().splitlines()] if traces.exists() else []
                if any(row.get('admissionReason')==reason for row in rows):found=True;break
                time.sleep(.01)
            (fixture/'queue-observation.json').write_text(json.dumps({'reason':reason,'found':found,'execChildren':len(owned_children)}))
        finally:
            if waiting:waiting.close()
            for connection in sockets:connection.close()
    return result
Path.write_text=write
sys.argv=[relay,'--stage-dir',str(fixture)]
try:
    runpy.run_path(relay,run_name='__main__')
finally:
    for child in owned_children:
        if child.poll() is None:child.kill()
        child.wait(timeout=3)
'''


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class RelayLifecycle(unittest.TestCase):
    def exercise(self, mode):
        with TemporaryDirectory(prefix='relay-lifecycle-', dir='/private/tmp') as folder:
            fixture = Path(folder)
            (fixture / 'stage.json').write_text(json.dumps({'ready': True, 'port': 23456,
                                                           'root': '/home/purge/.cache/score-native-qa-test'}))
            (fixture / 'manager.py').write_text("from pathlib import Path\nSETUP=Path('/private/tmp/inert-setup')\ndef validate():pass\n")
            (fixture / 'fake-ssh.py').write_text(FAKE_SSH)
            (fixture / 'driver.py').write_text(DRIVER)
            try:
                result = subprocess.run([sys.executable, '-B', str(fixture / 'driver.py'), str(fixture), str(RELAY), mode],
                                        input='stop\n', capture_output=True, text=True, timeout=15)
                owned = json.loads((fixture / 'owned-master.json').read_text())
                stopped = json.loads((fixture / 'mux-lifecycle.json').read_text())
                if mode=='unconfirmed-child':
                    self.assertFalse(stopped['stopped'], result.stderr)
                    self.assertFalse(process_exists(owned['pid']), result.stderr)
                    self.assertTrue(stopped['masterStopped'], result.stderr)
                    child_pid=json.loads((fixture/'unconfirmed-pid.json').read_text())['pid']
                    self.assertIn(child_pid,stopped['remainingPids'],result.stderr)
                    self.assertNotEqual(result.returncode,0)
                else:
                    self.assertTrue(stopped['stopped'], result.stderr)
                if mode=='connections':
                    observation=json.loads((fixture/'connection-observation.json').read_text())
                    self.assertEqual(observation['attempted'],24)
                    self.assertLessEqual(observation['maxHandlerThreads'],16)
                if mode.startswith('queue-'):
                    observed=json.loads((fixture/'queue-observation.json').read_text())
                    self.assertTrue(observed['found'],str(observed)+result.stderr)
                    self.assertEqual(observed['execChildren'],8)
                self.assertTrue(stopped['controlDirectoryRemoved'], result.stderr)
                self.assertFalse(Path(owned['control']).parent.exists())
                self.assertFalse(process_exists(owned['pid']))
            finally:
                record = fixture / 'owned-master.json'
                if record.exists():
                    owned = json.loads(record.read_text())
                    if process_exists(owned['pid']):
                        os.kill(owned['pid'], signal.SIGKILL)
                    control = Path(owned['control'])
                    if control.parent.parent == Path('/private/tmp') and control.parent.name.startswith('hmux-'):
                        shutil.rmtree(control.parent, ignore_errors=True)

    def test_interrupt_after_authentication_cleans_master_and_socket(self):
        self.exercise('interrupt')

    def test_master_ignoring_terminate_is_killed_and_reaped(self):
        self.exercise('stubborn')

    def test_child_second_wait_failure_still_stops_master_and_reports_remaining_pid(self):
        self.exercise('unconfirmed-child')

    def test_queued_client_times_out_without_ninth_exec(self):
        self.exercise('queue-timeout')

    def test_queued_request_disconnect_cancels_without_ninth_exec(self):
        self.exercise('queue-disconnect')

    def test_queued_client_stops_without_ninth_exec(self):
        self.exercise('queue-stop')

    def test_connection_limit_applies_before_handler_threads_start(self):
        self.exercise('connections')


if __name__ == '__main__':
    unittest.main()
