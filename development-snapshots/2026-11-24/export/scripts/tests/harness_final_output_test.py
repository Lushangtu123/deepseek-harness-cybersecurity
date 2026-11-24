from pathlib import Path
import importlib.util,json,unittest
MODULE=Path(__file__).resolve().parents[1]/'harness_final_output.py'
class FullOutput(unittest.TestCase):
    def collect(self,text):
        self.assertTrue(MODULE.exists(),'Full stdout final collector is missing')
        spec=importlib.util.spec_from_file_location('full_output',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        return m.capture_final_output(text)
    def test_final_before_truncated_tail_is_still_counted(self):
        text=json.dumps({'type':'final','text':'first'})+'\n'+json.dumps({'type':'progress','text':'x'*6000})+'\n'+json.dumps({'type':'final','text':'last'})+'\n'
        v=self.collect(text)
        self.assertEqual(v['finalCount'],2)
        self.assertIsNone(v['finalText'])
    def test_sole_final_is_preserved_and_full_output_hashed(self):
        from hashlib import sha256
        text='non-json log\n'+json.dumps({'type':'final','text':'完整结果'})+'\n'
        v=self.collect(text)
        self.assertEqual(v,{'finalCount':1,'finalText':'完整结果','stdoutSha256':sha256(text.encode()).hexdigest(),'stdoutBytes':len(text.encode())})
    def test_no_final_is_not_a_success(self):
        self.assertEqual(self.collect('[]\nnull\nnot json\n')['finalCount'],0)
    def test_malformed_final_is_rejected(self):
        with self.assertRaises(ValueError):self.collect('{"type":"final","text":3}\n')
class RawBinding(unittest.TestCase):
    def bind(self,raw,assistant):
        spec=importlib.util.spec_from_file_location('full_output',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        self.assertTrue(callable(getattr(m,'bind_final_output',None)),'Raw final binding is missing')
        import re
        scrub=lambda s:re.sub(r'(token=|sk-)[A-Za-z0-9_-]{10,}',r'\1[redacted]',s)
        return m.bind_final_output(raw,assistant,scrub)
    def stdout(self,text):return json.dumps({'type':'final','text':text})+'\n'
    def test_equal_sensitive_looking_text_is_bound_before_both_sides_are_scrubbed(self):
        text='Synthetic token=abcdefghijklmnopqrstuv'
        out=self.bind(self.stdout(text),text)
        self.assertEqual(out['finalText'],'Synthetic token=[redacted]')
        self.assertEqual(out['assistantText'],out['finalText'])
        self.assertTrue(out['rawBinding']['rawTextMatch'])
        self.assertTrue(out['rawBinding']['redactionChangedFinal'])
        self.assertEqual(out['rawBinding']['finalSha256'],out['rawBinding']['assistantSha256'])
    def test_redaction_collision_cannot_bind_different_raw_text(self):
        with self.assertRaises(ValueError):self.bind(self.stdout('token=aaaaaaaaaaaaaa'),'token=bbbbbbbbbbbbbb')
    def test_ordinary_equal_text_remains_unchanged(self):
        out=self.bind(self.stdout('same'),'same')
        self.assertEqual(out['finalText'],'same');self.assertFalse(out['rawBinding']['redactionChangedFinal'])
    def test_duplicate_final_cannot_bind(self):
        with self.assertRaises(ValueError):self.bind(self.stdout('same')+self.stdout('same'),'same')
    def test_missing_assistant_cannot_bind(self):
        with self.assertRaises(ValueError):self.bind(self.stdout('same'),None)

if __name__=='__main__':unittest.main()
