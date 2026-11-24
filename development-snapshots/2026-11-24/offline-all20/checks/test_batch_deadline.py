from pathlib import Path
from unittest.mock import patch
import importlib.util,unittest
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('deadline_producer_fixture',R/'checks/test_four_blockers.py');base=importlib.util.module_from_spec(s);s.loader.exec_module(base)
class Deadline(unittest.TestCase):
 def exercise(self,clock,count):
  f=base.FourBlockers();f.setUp();self.addCleanup(f.doCleanups)
  with patch.object(base.m.time,'monotonic',side_effect=clock):result,launches,queries=f.batch('normal')
  self.assertEqual(len(launches),count,result);self.assertFalse(result['complete']);self.assertEqual(result['problem']['type'],'batch-deadline');self.assertIsNone(result['publication'])
 def test_deadline_before_first(self):self.exercise([0,2701],0)
 def test_deadline_after_smoke_stops_second(self):self.exercise([0,0,2701],1)
 def test_deadline_before_publication(self):self.exercise([0]+[0]*20+[2701],20)
if __name__=='__main__':unittest.main(verbosity=2)
