from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as RealNamespace
import importlib.util,json,unittest
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('publication_producer_fixture',R/'checks/test_four_blockers.py');base=importlib.util.module_from_spec(s);s.loader.exec_module(base)
class PublicationPhase(unittest.TestCase):
 def test_actual_gate_receives_preexisting_phase_file(self):
  f=base.FourBlockers();f.setUp();self.addCleanup(f.doCleanups);seen=[]
  def namespace(*a,**kw):
   if 'run_gate' in kw:
    def real_contract(*args):
     phase=Path(args[3]);self.assertTrue(phase.is_file(),'real run_gate reads phase-result.json but never creates it');d=json.loads(phase.read_bytes());self.assertEqual(d['sourceManifestSha256'],base.SOURCE);self.assertEqual(d['state'],'pending-independent-review');seen.append(str(phase));return {'state':'pending-independent-review','archiveCalls':0,'unitOnly':True}
    kw['run_gate']=real_contract
   return RealNamespace(*a,**kw)
  with patch.object(base,'SimpleNamespace',side_effect=namespace):result,launches,queries=f.batch('normal')
  self.assertTrue(result['complete'],result);self.assertEqual(len(seen),1)
if __name__=='__main__':unittest.main(verbosity=2)
