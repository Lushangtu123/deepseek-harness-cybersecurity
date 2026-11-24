"""Byte-addressed execution point regression cases. Static parsing only."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import json
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'work/harness-purge-improved/package/scripts'))
import eval_evidence_batch as batch

class LocationsTest(unittest.TestCase):
    def inventory(self, source):
        self.assertTrue(hasattr(batch,'location_inventory'),'Location inventory missing')
        return batch.location_inventory({'sample.py':source})

    def hit(self, source, a, b, rule='eval'):
        raw=source.encode()
        def point(offset):
            return {'line':raw[:offset].count(b'\n')+1,'col':offset-(raw.rfind(b'\n',0,offset)+1)+1,'offset':offset}
        return {'check_id':'policy.harness.python.'+rule,'path':'/src/sample.py','start':point(a),'end':point(b)}

    def test_utf8_crlf_tabs_and_distinct_same_line_calls(self):
        source='label="中文😀"; eval(x); exec(y)\r\n\t# tail\r\n'
        inventory=self.inventory(source);points=inventory['files']['sample.py']['points']
        self.assertEqual(len(points),2);self.assertNotEqual(points[0]['id'],points[1]['id'])
        raw=source.encode()
        for point in points:
            span=point['call'];self.assertEqual(raw[span['start']['offset']:span['end']['offset']].decode(),point['callee']+'('+('x' if point['callee']=='eval' else 'y')+')')
            self.assertEqual(span['start']['col'],span['start']['offset']+1)

    def test_reproducible_id_ignores_rule_and_file_alias(self):
        source='eval(value)\n';one=self.inventory(source)
        other=batch.location_inventory({'other.py':source})
        self.assertEqual(one['files']['sample.py']['points'][0]['id'],other['files']['other.py']['points'][0]['id'])
        first=self.hit(source,0,11);second=self.hit(source,5,10,'request-to-dynamic-code')
        result=batch.map_findings({'sample.py':source},one,[first,second])
        self.assertEqual([r['state'] for r in result],['bound','bound']);self.assertEqual(result[0]['pointId'],result[1]['pointId'])

    def test_multiline_enclosure_and_argument_focus(self):
        source='result = (\n eval(\n  value\n )\n)\n';inventory=self.inventory(source);raw=source.encode()
        point=inventory['files']['sample.py']['points'][0]
        rows=batch.map_findings({'sample.py':source},inventory,[self.hit(source,9,len(raw)-1),self.hit(source,raw.index(b'value'),raw.index(b'value')+5,'request-to-dynamic-code')])
        self.assertEqual([r['state'] for r in rows],['bound','bound']);self.assertTrue(all(r['pointId']==point['id'] for r in rows))

    def test_ambiguous_nested_and_multiple_calls_are_not_guessed(self):
        for source in ['eval(x); eval(y)\n','eval(eval(x))\n','eval(x); exec(y)\n','exec(eval(x))\n','exec(exec(x))\n']:
            inv=self.inventory(source)
            for rule in ['eval','exec','request-to-dynamic-code']:
                rows=batch.map_findings({'sample.py':source},inv,[self.hit(source,0,len(source.encode())-1,rule)])
                self.assertEqual(rows[0]['state'],'unmatched')
                self.assertEqual(rows[0]['reason'],'ambiguous-execution-points')
                self.assertNotIn('pointId',rows[0]);self.assertNotIn('point',rows[0])

    def test_missing_mid_character_wrong_digest_and_rule_mismatch(self):
        source='"中"; eval(x)\n';inv=self.inventory(source);raw=source.encode()
        cases=[{'check_id':'policy.harness.python.eval','path':'sample.py','start':{'line':1}},self.hit(source,2,len(raw)-1),self.hit(source,raw.index(b'eval'),len(raw)-1,'exec')]
        result=batch.map_findings({'sample.py':source},inv,cases)
        self.assertTrue(all(r['state']=='unmatched' for r in result))
        self.assertEqual([r['reason'] for r in result],['missing-or-invalid-span','missing-or-invalid-span','rule-execution-point-mismatch'])
        inv['files']['sample.py']['sha256']='f'*64
        with self.assertRaises(ValueError):batch.map_findings({'sample.py':source},inv,[])

    def test_batch_preserves_missing_positions_and_cross_file_locations(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            sources={'a.py':'from flask import request\nfrom b import run\ndef route():\n    value=request.args.get("v")\n    return run(value)\n','b.py':'def run(value):\n    return exec(value)\n'}
            for name,source in sources.items():(root/name).write_text(source)
            report=batch.review_batch(root,{'files':{n:sha256(s.encode()).hexdigest() for n,s in sources.items()},'discoverImports':True},
                {'results':[{'check_id':'policy.harness.python.exec','path':'b.py'},None,{'check_id':[],'path':'b.py'}]})
            self.assertEqual(len(report['findingLocations']),3)
            self.assertTrue(all(r['state']=='unmatched' for r in report['findingLocations']))
            evidence,=report['importEvidence']
            self.assertEqual(evidence['sinkLocation']['id'],report['locations']['files']['b.py']['points'][0]['id'])
            self.assertEqual(evidence['callerLocation']['call']['start']['line'],5)
            caller=evidence['callerLocation']
            self.assertEqual(caller['sourceSha256'],sha256(sources['a.py'].encode()).hexdigest())
            self.assertEqual(caller['id'],batch.location_digest({k:caller[k] for k in ('sourceSha256','callee','call')}))
            self.assertEqual(caller['callee'],'run')

    def test_explicit_builtins_is_syntax_not_identity(self):
        inv=self.inventory('builtins.eval(x); builtins.exec(y)\n')
        self.assertEqual([p['callee'] for p in inv['files']['sample.py']['points']],['builtins.eval','builtins.exec'])
        self.assertTrue(all(p['builtinIdentity']=='unverified' for p in inv['files']['sample.py']['points']))

    def test_unknown_callee_parse_failure_and_limits(self):
        inv=self.inventory('alias(x)\n');self.assertEqual(inv['files']['sample.py']['points'],[])
        inv=self.inventory('eval(\n');self.assertEqual(inv['files']['sample.py']['state'],'unavailable')
        inv=self.inventory('eval(x)\n'*65);self.assertEqual(inv['files']['sample.py']['reason'],'point-limit')

if __name__=='__main__':unittest.main()
