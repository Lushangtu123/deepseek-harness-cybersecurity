"""Run actual handler methods with real socket pairs and inert launch failures."""
from pathlib import Path
from tempfile import TemporaryFile
import ast,json,select,socket,socketserver,subprocess,threading,time,types,unittest,uuid
SOURCE=Path(__file__).resolve().parents[1]/'harness_acceptance_relay.py'
class StartError(unittest.TestCase):
    def exercise(self,phase):
        node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        rows=[];files=[];starts=[]
        def temporary():
            if phase=='stderr-file':raise OSError(24,'synthetic fd exhaustion')
            f=TemporaryFile();files.append(f);return f
        def launch(*args,**kwargs):starts.append(True);raise OSError(11,'synthetic launch failed')
        ns=dict(time=time,uuid=uuid,select=select,socket=socket,socketserver=socketserver,threading=threading,
            TemporaryFile=temporary,subprocess=types.SimpleNamespace(Popen=launch,PIPE=subprocess.PIPE),
            stopping=threading.Event(),admission=threading.BoundedSemaphore(8),lock=threading.Lock(),children=set(),
            peak_exec_clients=0,ADMISSION_TIMEOUT=5.0,MAX_QUEUED_BYTES=65536,record=rows.append,args=['synthetic-only'])
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),ns)
        server,client=socket.socketpair()
        try:
            client.sendall(b'GET /synthetic HTTP/1.1\r\nHost: localhost\r\n\r\n')
            obj=ns['Handler'].__new__(ns['Handler']);obj.request=server;obj.handle()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].get('execStartError'),'OSError')
            self.assertEqual(rows[0].get('execStartPhase'),phase)
            self.assertFalse(rows[0]['execStarted'])
            self.assertNotIn('admissionReason',rows[0])
            client.settimeout(1);self.assertTrue(client.recv(1024).startswith(b'HTTP/1.1 502 '))
            self.assertEqual(len(starts),int(phase=='ssh-client'))
            self.assertTrue(all(f.closed for f in files))
            self.assertFalse(ns['children'])
            self.assertTrue(all(ns['admission'].acquire(blocking=False) for _ in range(8)))
            self.assertFalse(ns['admission'].acquire(blocking=False))
            self.assertNotIn('synthetic launch failed',json.dumps(rows))
        finally:
            server.close();client.close()
            for f in files:f.close()
    def test_stderr_creation_error_is_not_client_disconnect(self):self.exercise('stderr-file')
    def test_exec_launch_error_returns_502_and_releases_permit(self):self.exercise('ssh-client')
if __name__=='__main__':unittest.main()
