"""Required-journal checks. Real operators, no VM or project execution."""
from pathlib import Path
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock, patch
import importlib.util
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest

R=Path(__file__).resolve().parents[1]
SOURCE=sha256((R/'candidate/protocol-manifest.json').read_bytes()).hexdigest()
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('required_batch',R/'operator/full20_batch.py')
b=load('required_bounded',R/'operator/bounded.py')
c=load('required_consumer',R/'operator/consumer_vm.py')
def identity(pid=2147483647):
    return {'pid':pid,'pgid':pid,'starttime':1,'bootId':'00000000-0000-0000-0000-000000000001','groupLeader':True}
def fake_guard():
    return SimpleNamespace(process_identity=identity,group_state=Mock(return_value={'state':'exited'}),
                           spawn_group_state=Mock(return_value={'state':'exited'}))

class RequiredJournal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=R/'checks');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'guest';self.suite='consumer-12'
    def seed(self):
        (self.root/'candidate').mkdir(parents=True);(self.root/'evidence').mkdir()
    def records(self,cleanup=True):
        if not self.root.exists():self.seed()
        out=self.root/'evidence'/self.suite;out.mkdir(exist_ok=True)
        intent={'suite':self.suite,'identityRequired':True,'createdBeforeProcess':True,
                'cwd':str(self.root/'candidate'),'command':['unit-only'],'noAutomaticReplay':True}
        process={'pid':2147483647,'processGroup':2147483647,'originalPopenChild':True,'identity':identity()}
        row={'suite':self.suite,'pid':2147483647,'cleanupConfirmed':cleanup,'passed':False,'unitOnly':True}
        for n,v in [('intent.json',intent),('process.json',process),('capture.json',row)]:
            (out/n).write_text(json.dumps(v))
        return out,row
    def query(self,attempted=None,rows=None):
        kwargs={}
        if attempted is not None:
            self.assertIn('attempted_suites',inspect.signature(m._actual_process_quiescence).parameters,
                          'missing submitted-attempt accounting')
            kwargs={'attempted_suites':attempted,'rows':rows}
        with patch.object(m,'_load_guard',return_value=fake_guard()):
            return m._actual_process_quiescence(self.root,{},**kwargs)
    def test_intent_with_absent_process_is_unknown(self):
        out,row=self.records();(out/'process.json').unlink()
        ok,detail=self.query();self.assertFalse(ok,detail)
    def test_called_group_with_both_records_absent_is_unknown(self):
        self.seed();ok,detail=self.query([self.suite],[]);self.assertFalse(ok,detail)
    def test_missing_required_intent_is_unknown(self):
        out,row=self.records();(out/'intent.json').unlink()
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_partial_process_record_is_unknown(self):
        out,row=self.records();(out/'process.json').write_text('{')
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_process_read_permission_failure_is_unknown(self):
        out,row=self.records();p=out/'process.json';p.chmod(0)
        try:
            with self.assertRaises(PermissionError):p.read_bytes()
            ok,detail=self.query([self.suite],[row])
        finally:p.chmod(0o600)
        self.assertFalse(ok,detail)
    def test_linked_process_record_is_unknown(self):
        out,row=self.records();p=out/'process.json';p.rename(out/'original.json');p.symlink_to(out/'original.json')
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_mismatched_intent_owner_is_unknown(self):
        out,row=self.records();v=json.loads((out/'intent.json').read_bytes());v['suite']='other-group';(out/'intent.json').write_text(json.dumps(v))
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_legacy_missing_requirement_field_is_unknown(self):
        out,row=self.records();v=json.loads((out/'intent.json').read_bytes());v.pop('identityRequired');(out/'intent.json').write_text(json.dumps(v))
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_disk_cleanup_false_cannot_be_quiet(self):
        out,row=self.records(False);ok,detail=self.query();self.assertFalse(ok,detail)
    def test_row_missing_after_call_is_unknown(self):
        out,row=self.records();ok,detail=self.query([self.suite],[]);self.assertFalse(ok,detail)
    def test_disk_intent_without_capture_is_not_hidden_by_empty_context(self):
        out,row=self.records();(out/'capture.json').unlink()
        ok,detail=self.query([],[]);self.assertFalse(ok,detail)
    def test_duplicate_rows_cannot_overwrite_unknown(self):
        out,row=self.records();failed=dict(row,cleanupConfirmed=False)
        ok,detail=self.query([self.suite],[failed,row]);self.assertFalse(ok,detail)
    def test_foreign_row_cannot_complete_current_attempt(self):
        out,row=self.records();foreign=dict(row,suite='other-group')
        ok,detail=self.query([self.suite],[row,foreign]);self.assertFalse(ok,detail)
    def test_cleanup_missing_or_nonboolean_is_unknown(self):
        out,row=self.records();row['cleanupConfirmed']=1
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
    def test_reappearing_journal_does_not_clear_failed_row(self):
        out,row=self.records(False);raw=(out/'process.json').read_bytes();(out/'process.json').unlink()
        self.assertFalse(self.query([self.suite],[row])[0]);(out/'process.json').write_bytes(raw)
        ok,detail=self.query([self.suite],[row]);self.assertFalse(ok,detail)
        self.assertFalse(json.loads((out/'capture.json').read_bytes())['cleanupConfirmed'])
    def test_normal_confirmed_wrapper_is_quiet(self):
        out,row=self.records();ok,detail=self.query([self.suite],[row]);self.assertTrue(ok,detail)
    def test_unsubmitted_groups_do_not_need_records(self):
        self.seed();ok,detail=self.query([],[]);self.assertTrue(ok,detail)
    def test_shared_collection_predicate_rejects_false_row(self):
        fn=getattr(m,'resources_confirmed',None);self.assertTrue(callable(fn),'missing shared resource predicate')
        result={'resourceQuiescent':True,'actualProcessQuiescence':{'state':'quiescent'},
                'attemptedSuites':[self.suite],'rows':[{'suite':self.suite,'cleanupConfirmed':False}]}
        self.assertFalse(fn(result))
        result['rows'][0]['cleanupConfirmed']=True;self.assertTrue(fn(result))
    def test_collection_flag_requires_literal_true(self):
        fn=getattr(m,'resources_confirmed',None);self.assertTrue(callable(fn),'missing shared resource predicate')
        result={'resourceQuiescent':1,'actualProcessQuiescence':{'state':'quiescent'},
                'attemptedSuites':[],'rows':[]}
        self.assertFalse(fn(result))

    def controller(self,mode):
        guard=fake_guard();launches=[];collector=Mock(return_value={'archiveComplete':True,
          'archiveBytesPayload':b'unit-only','archiveSha256':'unit-only','members':{},
          'linksRecordedNotFollowed':{},'collectionIssues':[],'VMTreeBytes':0})
        names=['candidate/checks/finalize_closure.py','candidate/tools/resource_guard.py','candidate/protocol-manifest.json','operator/suite-plan.json',
               'operator/full20_batch.py','operator/bounded.py','operator/archive_helpers.py','operator/linux_admission.py']
        files={n:(R/n).read_bytes() for n in names};files['candidate/checks/evidence_capture.py']=b'# not run; unit-only\n'
        counts=dict(zip(json.loads(files['operator/suite-plan.json'])['order'],[12,13,15,27,21,24,15,28,13,24,12,13,20,11,29,57,6,87,116,300]))
        g=SimpleNamespace(_FIXED_COUNTS=counts,_source_state=lambda *_:{'manifestSha256':SOURCE,'actual':{}})
        def run(root,suite,args,expected,immutable,**kwargs):
            launches.append(suite)
            if mode=='no-row':
                out=root/'evidence'/suite;out.mkdir()
                (out/'intent.json').write_text(json.dumps({'suite':suite,'identityRequired':True,
                   'createdBeforeProcess':True,'cwd':str(root/'candidate'),'command':['unit-only']}))
                raise OSError('unit failure after start intent')
            dest=root/'unit-result.json'
            code='from pathlib import Path;Path('+repr(str(dest))+').write_text('+repr(json.dumps(
                {'passed':0,'total':1,'checks':[{'passed':False}],'unitOnly':True}))+')'
            writer=b.write_json
            def writing(path,value):
                if mode=='journal-failure' and Path(path).name=='process.json':raise OSError('unit process journal create failure')
                return writer(path,value)
            with patch.object(b,'write_json',side_effect=writing):
                return b.run_one(root,suite,[sys.executable,'-I','-B','-c',code],1,sorted(files),
                                  result_file=dest,identity_reader=kwargs['identity_reader'])
        bounded=SimpleNamespace(run_one=run,usage=b.usage,budget_admitted=b.budget_admitted)
        helpers=SimpleNamespace(usage=b.usage,collect_artifacts=collector)
        admission=SimpleNamespace(check_runtime=lambda:{'pid':os.getpid(),'pgid':os.getpgrp(),'starttime':1,'bootId':'unit-only'})
        def module(name,raw,filename=None):
            return {'operator_linux_admission':admission,'operator_bounded':bounded,
                    'operator_archive_helpers':helpers,'operator_full20_batch':m}[name]
        def stage(rows,_helpers):
            for n,raw in rows.items():
                p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        with patch.object(c,'GUEST',self.root),patch.object(c,'_validate_packet',return_value=(files,{}, {},SOURCE)), \
             patch.object(c,'_load_module',side_effect=module),patch.object(c,'_validate_parent_chain',return_value=None), \
             patch.object(c,'_stage_files',side_effect=stage),patch.object(m,'_load_path',return_value=g), \
             patch.object(m,'_load_guard',return_value=guard):
            result=c.main({'caseIds':list(c.CONSUMER_CASE_IDS),'sourceManifestSha256':SOURCE,'unitOnly':True})
        self.assertEqual(launches,[self.suite],result)
        out=R/'evidence/controller-cases'/(mode+'-'+os.urandom(5).hex());out.mkdir(parents=True)
        raw_files={}
        for p in (self.root/'evidence').rglob('*'):
            if p.is_file():
                rel=p.relative_to(self.root);q=out/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
                raw_files[str(rel)]=sha256(p.read_bytes()).hexdigest()
        # Original files remain in place until the unit framework's temporary-dir cleanup.
        (out/'unit-outcome.json').write_text(json.dumps({'unitOnly':True,'notVMMeasurement':True,
          'collectorCalls':collector.call_count,'result':{k:v for k,v in result.items() if k!='archiveBytesPayload'},
          'rawFiles':raw_files,'originalFilesPresentBeforeFrameworkCleanup':True},indent=2))
        return result,collector
    def test_actual_write_failure_blocks_controller_collection(self):
        result,collector=self.controller('journal-failure')
        collector.assert_not_called();self.assertFalse(result['result']['actualProcessQuiescent'])
        self.assertFalse(result['diagnosticArchiveComplete'])
    def test_missing_row_after_intent_blocks_controller_collection(self):
        result,collector=self.controller('no-row')
        collector.assert_not_called();self.assertFalse(result['result']['actualProcessQuiescent'])
    def test_clean_test_failure_can_collect_diagnostics(self):
        result,collector=self.controller('clean-failure')
        collector.assert_called_once();self.assertFalse(result['result']['complete'])
        self.assertTrue(result['diagnosticArchiveComplete'])

if __name__=='__main__':unittest.main(verbosity=2)
