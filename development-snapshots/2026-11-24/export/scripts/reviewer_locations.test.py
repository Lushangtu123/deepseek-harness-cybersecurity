"""Synthetic controller tests; no Docker or untrusted source execution."""
import importlib.util
from pathlib import Path
import json,sys,unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('snapshot_tests',HERE/'reviewer_snapshot.test.py');tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(tests)
sys.path.insert(0,str(HERE.parent/'work/harness-purge-improved/package/scripts'))
import eval_evidence_batch as batch

class LocationControllerTest(tests.SnapshotTest):
    # Inherit the fixture but not the old test methods (removed below).
    def location_fixture(self):
        snapshot,project,manifest,scan=self.execution_fixture()
        (project/'safe.py').write_text('eval(value)\n')
        request=json.loads(manifest.read_bytes());request['files']['safe.py']=batch.sha256((project/'safe.py').read_bytes()).hexdigest();manifest.write_text(json.dumps(request))
        inv=batch.location_inventory({'safe.py':(project/'safe.py').read_text()})
        return snapshot,project,manifest,scan,inv

    def test_locations_is_read_only_sandboxed_and_original_attempt_recoverable(self):
        snap,project,manifest,scan,inv=self.location_fixture();backend=tests.Backend()
        backend.report=json.dumps({'version':2,'operation':'locations','locations':inv,'findingLocations':[]}).encode()
        result=self.api.locations(self.bundle,self.api.digest(snap),project,manifest,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
        receipt=result['reviewerExecution'];self.assertEqual((receipt['version'],receipt['operation']),(3,'locations'))
        self.assertEqual(receipt['locationBindingSha256'],self.api.digest(result['locationBinding']))
        self.assertEqual(result['locationBinding']['imageId'],tests.IMAGE)
        self.assertIn('--locations',backend.create_args);self.assertIn('--network',backend.create_args);self.assertIn('none',backend.create_args)
        calls=len(backend.calls);self.assertEqual(self.api.status(Path(result['attemptDirectory']))['result'],result)
        self.assertEqual(self.api.recover(Path(result['attemptDirectory']))['result'],result);self.assertEqual(len(backend.calls),calls)

    def test_formal_review_recomputes_location_binding_and_drift_has_no_receipt(self):
        snap,project,manifest,scan,inv=self.location_fixture();binding={'version':1,'snapshotSha256':self.api.digest(snap),'imageId':tests.IMAGE,'uid':self.api.os.geteuid(),'inventory':inv}
        request=json.loads(manifest.read_bytes());request['locationBinding']=binding;manifest.write_text(json.dumps(request))
        backend=tests.Backend();backend.report=json.dumps({'version':2,'locations':inv,'findingLocations':[]}).encode()
        value=self.api.execute(self.bundle,self.api.digest(snap),project,manifest,scan,'a'*64,'b'*64,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
        self.assertEqual(value['reviewerExecution']['operation'],'review');self.assertEqual(value['locationBinding'],binding)
        self.assertEqual(value['reviewArtifact']['scanJson'],scan.read_bytes().decode('utf-8'))
        self.assertEqual(value['reviewArtifact']['manifestJson'],manifest.read_bytes().decode('utf-8'))
        self.assertEqual(value['reviewArtifact']['reportJson'],value['reportJson'])
        changed=json.loads(json.dumps(inv));changed['runtimePython']='3.12.99';backend=tests.Backend();backend.report=json.dumps({'version':2,'locations':changed,'findingLocations':[]}).encode()
        with self.assertRaises(self.api.ReviewAttemptError) as error:self.api.execute(self.bundle,self.api.digest(snap),project,manifest,scan,'a'*64,'b'*64,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
        self.assertEqual(error.exception.status['failure']['kind'],'location-binding-changed');self.assertNotIn('result',error.exception.status)

    def test_invalid_inventory_never_commits_and_supplied_binding_is_not_discarded(self):
        snap,project,manifest,scan,inv=self.location_fixture()
        for mutation in ['missing','wrong-coordinate','forged-id']:
            broken=json.loads(json.dumps(inv))
            if mutation=='missing':broken['files']['safe.py']={'sha256':inv['files']['safe.py']['sha256']}
            elif mutation=='wrong-coordinate':broken['files']['safe.py']['points'][0]['call']['start']['col']=999
            else:broken['files']['safe.py']['points'][0]['id']='f'*64
            backend=tests.Backend();backend.report=json.dumps({'version':2,'operation':'locations','locations':broken,'findingLocations':[]}).encode()
            with self.assertRaises(self.api.ReviewAttemptError) as caught:self.api.locations(self.bundle,self.api.digest(snap),project,manifest,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
            self.assertEqual(caught.exception.status['failure']['kind'],'report-invalid');self.assertNotIn('result',caught.exception.status)
        request=json.loads(manifest.read_bytes());request['locationBinding']={'changed':True};manifest.write_text(json.dumps(request))
        backend=tests.Backend();backend.report=json.dumps({'version':2,'operation':'locations','locations':inv,'findingLocations':[]}).encode()
        with self.assertRaises(self.api.ReviewAttemptError) as caught:self.api.locations(self.bundle,self.api.digest(snap),project,manifest,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
        self.assertEqual(caught.exception.status['failure']['kind'],'location-binding-changed')

    def test_utf8_endpoint_validation_and_review_requires_original_scan(self):
        snap,project,manifest,scan,inv=self.location_fixture()
        with self.assertRaisesRegex(ValueError,'requires original scan'):self.api.execute(self.bundle,self.api.digest(snap),project,manifest,None,'a'*64,'b'*64,attempts_root=self.root/'attempts',_engine_factory=tests.Backend().factory)
        source='"中😀"; eval(value)\r\n';raw=source.encode();inventory=batch.location_inventory({'sample.py':source})
        payload={'sources/sample.py':raw};self.api.validate_locations(inventory,payload)
        inventory['files']['sample.py']['points'][0]['call']['start']={'line':1,'col':3,'offset':2}
        with self.assertRaisesRegex(ValueError,'execution point'):self.api.validate_locations(inventory,payload)

    def test_locations_rejects_wrong_source_digest_before_task_creation(self):
        snap,project,manifest,scan,inv=self.location_fixture();(project/'safe.py').write_text('exec(other)\n');backend=tests.Backend()
        with self.assertRaisesRegex(ValueError,'source digest'):self.api.locations(self.bundle,self.api.digest(snap),project,manifest,attempts_root=self.root/'attempts',_engine_factory=backend.factory)
        self.assertEqual(backend.calls,[]);self.assertFalse((self.root/'attempts').exists())

# unittest discovery only runs the new controller checks here.
for name in list(tests.SnapshotTest.__dict__):
    if name.startswith('test_'):setattr(LocationControllerTest,name,None)
if __name__=='__main__':unittest.main()
