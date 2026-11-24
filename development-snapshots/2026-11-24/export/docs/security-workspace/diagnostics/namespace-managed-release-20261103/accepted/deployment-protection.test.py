from pathlib import Path
from tempfile import TemporaryDirectory
import ast,hashlib,sqlite3,unittest

class DeploymentProtection(unittest.TestCase):
 def test_checkpoint_preserves_logical_protection_but_changes_raw_file(self):
  remote=ast.parse(Path(__file__).with_name('deploy-remote.py').read_text());watched=next(n for n in remote.body if isinstance(n,ast.FunctionDef) and n.name=='watched')
  with TemporaryDirectory() as directory:
   home=Path(directory);dbfile=home/'.dsh-improved/redteam/engagements/test/assets.db';dbfile.parent.mkdir(parents=True)
   for name in ('.dsh-improved/cordis.patch.yml','tools/security-workbench/images.json'):
    p=home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('unchanged')
   context={'home':home,'hashlib':hashlib,'sqlite3':sqlite3};exec(compile(ast.Module(body=[watched],type_ignores=[]),'watched','exec'),context)
   db=sqlite3.connect(dbfile)
   try:
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
    db.execute('CREATE TABLE sample(value TEXT)');db.execute('INSERT INTO sample VALUES (?)',('synthetic',));db.commit()
    before=context['watched']();raw=hashlib.sha256(dbfile.read_bytes()).hexdigest()
    db.execute('PRAGMA wal_checkpoint(FULL)').fetchall()
    self.assertNotEqual(raw,hashlib.sha256(dbfile.read_bytes()).hexdigest())
    self.assertEqual(before,context['watched']())
    db.execute('INSERT INTO sample VALUES (?)',('changed',));db.commit()
    self.assertNotEqual(before,context['watched']())
   finally:db.close()


class RollbackQuarantine(unittest.TestCase):
 def test_changed_candidate_is_preserved_and_cannot_block_old_program_restore(self):
  tree=ast.parse(Path(__file__).with_name('deploy-remote.py').read_text())
  restore=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='restore_previous'),None)
  self.assertIsNotNone(restore,'Rollback must not require the failed candidate to be unchanged')
  inventory=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='inventory')
  with TemporaryDirectory() as directory:
   root=Path(directory);backup=root/'backup';backup.mkdir();previous=backup/'previous';previous.mkdir();(previous/'app.py').write_text('old')
   package=root/'package';package.mkdir();(package/'app.py').write_text('new');(package/'unexpected-runtime-file').write_text('preserve me')
   context={'previous':previous,'backup':backup,'package':package,'OLD':{'app.py':hashlib.sha256(b'old').hexdigest()},'digest':lambda raw:hashlib.sha256(raw).hexdigest(),'sync_dirs':lambda *paths:None}
   exec(compile(ast.Module(body=[inventory,restore],type_ignores=[]),'rollback','exec'),context);context['restore_previous']()
   self.assertEqual((package/'app.py').read_text(),'old');self.assertEqual((backup/'candidate-failed'/'unexpected-runtime-file').read_text(),'preserve me')



class StopCompletion(unittest.TestCase):
 def test_timeout_waits_for_inactive_unit_and_an_empty_job_field(self):
  import subprocess
  from types import SimpleNamespace
  tree=ast.parse(Path(__file__).with_name('deploy-remote.py').read_text());stop=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stop')
  seen={};clock=[0]
  def system(action,unit):
   if action=='stop':raise subprocess.TimeoutExpired('systemctl',30)
   seen[unit]=seen.get(unit,0)+1
   return SimpleNamespace(stdout='ActiveState=deactivating\nJob=17\n' if seen[unit]==1 else 'ActiveState=inactive\nJob=\n')
  def now():clock[0]+=1;return clock[0]
  context={'units':['daily','socket','security'],'system':system,'subprocess':subprocess,'time':SimpleNamespace(monotonic=now,sleep=lambda _:None)}
  exec(compile(ast.Module(body=[stop],type_ignores=[]),'stop','exec'),context);context['stop']();self.assertEqual(seen,{'socket':2,'security':2,'daily':2})



class BeforeSwapFailure(unittest.TestCase):
 def test_untouched_old_program_restarts_without_repeating_failed_stop(self):
  from types import SimpleNamespace
  tree=ast.parse(Path(__file__).with_name('deploy-remote.py').read_text());rollback=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='rollback')
  with TemporaryDirectory() as directory:
   package=Path(directory);(package/'old.py').write_text('old');calls=[]
   context={'signal':SimpleNamespace(SIGTERM=15,SIGHUP=1,SIG_IGN=0,signal=lambda *a:None),'record':calls.append,'previous':package/'absent','package':package,'OLD':{'old.py':'unchanged'},'inventory':lambda _: {'old.py':'unchanged'},'stop':lambda: self.fail('must not repeat the failed stop'),'start':lambda:calls.append('start'),'wait_healthy':lambda:calls.append('healthy'),'active':lambda _:True,'units':['daily'],'was':{'daily':True},'watched':lambda:{'db':'unchanged'},'before_watched':{'db':'unchanged'}}
   exec(compile(ast.Module(body=[rollback],type_ignores=[]),'rollback','exec'),context);context['rollback']();self.assertEqual(calls,['rollback-started','start','healthy','rolled-back'])

if __name__=='__main__':unittest.main()
