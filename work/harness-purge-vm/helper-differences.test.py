import importlib.util,tempfile,json,unittest,hashlib
from pathlib import Path
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('helper_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Helpers(unittest.TestCase):
 def test_fixed_changed_and_missing_helpers_have_safe_difference_details(self):
  for variant in ['changed','missing','matches']:
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);tools=root/'host-tools';tools.mkdir();expected={}
    for name in m.RECOVERY_HELPERS:
     (tools/name).write_bytes(b'original');expected[name]=hashlib.sha256(b'original').hexdigest()
    (root/'host-tools.sha256.json').write_text(json.dumps(expected))
    if variant=='changed':(tools/'web-health.mjs').write_bytes(b'changed')
    if variant=='missing':(tools/'web-health.mjs').unlink()
    files={'tools/dsh-purge-personal-1.1.77-personal.1/client.js':'hash',**{name:'hash' for name in m.RECOVERY_TOOL_FILES|m.RECOVERY_CONFIG_FILES|m.RECOVERY_RUNTIME_FILES|{m.RECOVERY_PLUGIN_ROOT+n+'/package.json' for n in m.RECOVERY_PLUGINS}}}
    folder=root/'recoveries'/m.CURRENT_RECOVERY;folder.mkdir(parents=True);(folder/'guest-proof.json').write_text(json.dumps({'files':files}))
    launches={m.LABEL+'.plist':'hash',m.WEB_LABEL+'.plist':'hash'}
    with patch.object(m,'ROOT',root),patch.object(m,'TOOLS',tools),patch.object(m,'validate'),patch.object(m,'checked_recovery_source',side_effect=lambda path,*args:(path.read_bytes() if path.name=='guest-proof.json' else b'original',0o600)),patch.object(m,'verify_recovery_bundle',return_value=(folder,{'helpers':expected,'launchAgents':launches,'guestProofSha256':'a'*64,'createdAt':'2026-10-26T00:00:00Z'})),patch.object(m,'current_launch_inventory',return_value=launches),patch.object(m,'image_command',return_value=MagicMock(stdout=json.dumps({'snapshots':[{'name':m.CURRENT_RECOVERY}]}))) as image,patch.object(m,'ssh',return_value=MagicMock(stdout=json.dumps({'mode':'improved','configDir':'/home/purge/.dsh-improved','modeFile':'improved','differentFiles':[],'filesChecked':len(files)}))):
     recovery=m.deployment_status()['recovery'];changed=variant!='matches'
     self.assertEqual(recovery['state'],'older' if changed else 'matches')
     self.assertEqual(recovery['helpersMatch'],not changed)
     self.assertEqual(recovery['groups']['tools']['differentFiles'],['host-tools/web-health.mjs'] if changed else [])
     self.assertEqual(recovery['groups']['tools']['filesChecked'],41)
     self.assertEqual(image.call_args.kwargs.get('helper'),b'original')
if __name__=='__main__':unittest.main()
