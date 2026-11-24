from pathlib import Path
import importlib.util,io,json,os,subprocess,sys,tarfile,tempfile,unittest
import gzip,hashlib,sqlite3
from unittest.mock import patch

SCRIPT=Path(__file__).with_name('professional_guest.py')
spec=importlib.util.spec_from_file_location('professional',SCRIPT);professional=importlib.util.module_from_spec(spec);spec.loader.exec_module(professional)

class ProfessionalTests(unittest.TestCase):
 def test_default_plans_full_assets_without_accessing_host_tools_or_creating_files(self):
  with tempfile.TemporaryDirectory() as folder:
   result=subprocess.run([sys.executable,'-B',str(SCRIPT)],env={**os.environ,'HOME':folder},capture_output=True,text=True,timeout=10)
   self.assertEqual(result.returncode,0,result.stderr)
   value=json.loads(result.stdout);self.assertTrue(value['readOnly']);self.assertFalse(value['automaticChanges']);self.assertFalse(value['copiesCredentials'])
   self.assertEqual(set(value['components']),{'rea','reverse-skill','pentagi','security-scanners','original-capabilities','runtime-overrides','optional-plugins','codegraph'})
   self.assertTrue(value['requiresPristineBasicInstall']);self.assertEqual(list(Path(folder).iterdir()),[])

 def test_archive_validation_refuses_traversal_secrets_and_device_or_escaping_links_before_extracting(self):
  for name,kind,target in [('../outside','file',''),('.dsh-improved/.credentials.yaml','file',''),('tools/rea-runtime/secrets.env','file',''),('tools/rea-runtime/device','device',''),('tools/rea-runtime/link','link','/etc/passwd'),('tools/rea-runtime/link','link','../../../.ssh/id')]:
   with self.subTest(name=name,kind=kind),tempfile.TemporaryDirectory() as folder:
    root=Path(folder).resolve();archive=root/'payload.tgz'
    with tarfile.open(archive,'w:gz') as out:
     entry=tarfile.TarInfo(name)
     if kind=='link':entry.type=tarfile.SYMTYPE;entry.linkname=target;out.addfile(entry)
     elif kind=='device':entry.type=tarfile.CHRTYPE;out.addfile(entry)
     else:entry.size=1;out.addfile(entry,io.BytesIO(b'x'))
    stage=root/'stage';stage.mkdir()
    with self.assertRaises(ValueError):professional.extract_payload(archive,stage)
    self.assertEqual(list(stage.iterdir()),[])

 def test_archive_accepts_only_known_program_roots_and_relative_internal_links(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder).resolve();archive=root/'payload.tgz';name='tools/rea-runtime/node_modules/rea-agents/package.json'
   with tarfile.open(archive,'w:gz') as out:
    raw=b'{"version":"6.8.0"}';entry=tarfile.TarInfo(name);entry.size=len(raw);entry.mode=0o644;out.addfile(entry,io.BytesIO(raw))
    link=tarfile.TarInfo('tools/rea-runtime/package-link');link.type=tarfile.SYMTYPE;link.linkname='node_modules/rea-agents/package.json';out.addfile(link)
   stage=root/'stage';stage.mkdir();result=professional.extract_payload(archive,stage)
   self.assertEqual(result['files'],1);self.assertEqual(result['links'],1);self.assertEqual((stage/name).read_bytes(),raw)
   self.assertTrue((stage/'tools/rea-runtime/package-link').is_symlink())

 def test_archive_duplicate_or_link_parent_is_rejected_without_output(self):
  for defect in ['duplicate','link-parent']:
   with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
    root=Path(folder).resolve();archive=root/'payload.tgz'
    with tarfile.open(archive,'w:gz') as out:
     if defect=='link-parent':
      link=tarfile.TarInfo('tools/rea-runtime/nested');link.type=tarfile.SYMTYPE;link.linkname='elsewhere';out.addfile(link)
     for _ in range(2 if defect=='duplicate' else 1):
      entry=tarfile.TarInfo('tools/rea-runtime/nested/file');entry.size=1;out.addfile(entry,io.BytesIO(b'x'))
    stage=root/'stage';stage.mkdir()
    with self.assertRaises(ValueError):professional.extract_payload(archive,stage)
    self.assertEqual(list(stage.iterdir()),[])

 def test_bundle_digest_and_every_archive_are_verified_without_creating_stage(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder).resolve();bundle=root/'bundle';bundle.mkdir();files={}
   for name in ['programs.tgz','images.tar.gz']:
    raw=b'fixture';(bundle/name).write_bytes(raw);files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
   value={'schemaVersion':1,'scope':'professional-offline-assets','platform':'linux/arm64','archives':files,'components':professional.COMPONENTS,'images':professional.IMAGES,'payloadFiles':1,'payloadBytes':7}
   path=bundle/'manifest.json';path.write_text(json.dumps(value));want=hashlib.sha256(path.read_bytes()).hexdigest()
   self.assertEqual(professional.verify_bundle(bundle,want),value)
   for defect in ['manifest','archive','link','extra']:
    with self.subTest(defect=defect):
     if defect=='manifest':
      with self.assertRaises(ValueError):professional.verify_bundle(bundle,'0'*64)
     elif defect=='archive':
      (bundle/'programs.tgz').write_bytes(b'changed')
      with self.assertRaises(ValueError):professional.verify_bundle(bundle,want)
      (bundle/'programs.tgz').write_bytes(b'fixture')
     elif defect=='link':
      (bundle/'programs.tgz').rename(bundle/'outside');(bundle/'programs.tgz').symlink_to('outside')
      with self.assertRaises(ValueError):professional.verify_bundle(bundle,want)
      (bundle/'programs.tgz').unlink();(bundle/'outside').rename(bundle/'programs.tgz')
     else:
      (bundle/'secrets.env').write_text('do not read')
      with self.assertRaises(ValueError):professional.verify_bundle(bundle,want)
   self.assertEqual(sorted(p.name for p in root.iterdir()),['bundle'])

 def test_apply_refuses_mac_before_touching_target_or_bundle(self):
  with tempfile.TemporaryDirectory() as folder:
   r=subprocess.run([sys.executable,'-B',str(SCRIPT),'--bundle',folder,'--manifest-sha256','0'*64,'--apply'],env={**os.environ,'HOME':folder},capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,1,r.stderr);self.assertEqual(json.loads(r.stdout)['error'],'Pristine dedicated basic VM required');self.assertEqual(list(Path(folder).iterdir()),[])

 def test_professional_profile_keeps_the_default_workspace_directory(self):
  with tempfile.TemporaryDirectory() as folder:
   stage=Path(folder)
   professional.stage_configuration(stage)
   profile=(stage/'.dsh-improved/profiles/web/cordis.patch.yml').read_text()
   self.assertRegex(profile,r'(?m)^- id: workspace-controller\n  config:\n    documentsDirectory: /home/purge/workspace$')

 def test_pristine_basic_refuses_existing_credentials_professional_tools_and_modified_programs(self):
  def base(home):
   (home/'.harness-bootstrap').mkdir();(home/'.harness-bootstrap/complete.json').write_text('{"ok":true,"scope":"basic-harness-plugin-web"}')
   (home/'tools/harness-improved-runtime').mkdir(parents=True);(home/'.local/node').mkdir(parents=True)
   package=home/'tools/dsh-purge-personal-1.1.77-personal.1';package.mkdir();(package/'package.json').write_text('fixture')
   (home/'.dsh-improved/profiles/web').mkdir(parents=True)
   import bootstrap_guest
   for name in bootstrap_guest.BASIC_FILES:
    path=home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fresh basic')
   (home/'.harness-bootstrap/complete.json').write_text(json.dumps({'ok':True,'scope':'basic-harness-plugin-web','baseFiles':{name:hashlib.sha256((home/name).read_bytes()).hexdigest() for name in bootstrap_guest.BASIC_FILES}}))
   return {'package.json':hashlib.sha256(b'fixture').hexdigest()}
  for defect in ['clean','credential','tool','program','link','in-progress','config-link','tools-link','empty-store','used-store','config-changed','owned-marker','other-marker']:
   with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
    home=Path(folder).resolve();expected=base(home)
    if defect=='credential':(home/'.dsh-improved/.credentials.yaml').write_text('private')
    if defect=='tool':(home/'tools/rea-runtime').mkdir()
    if defect=='program':(home/'tools/dsh-purge-personal-1.1.77-personal.1/package.json').write_text('changed')
    if defect=='link':(home/'.dsh').symlink_to('/tmp')
    if defect=='config-changed':(home/'.config/systemd/user/dsh-original.service').write_text('changed service')
    if defect=='in-progress':(home/'.harness-professional').mkdir()
    owned=None
    if defect in ['owned-marker','other-marker']:
     marker=home/'.harness-professional';marker.mkdir(mode=0o700);info=marker.stat();owned=(info.st_dev,info.st_ino+(1 if defect=='other-marker' else 0))
    if defect in ['config-link','tools-link']:
     name='.config' if defect=='config-link' else 'tools';path=home/name
     if path.exists():path.rename(home/(name+'-preserved'))
     path.symlink_to('/tmp')
    if defect in ['empty-store','used-store']:
     root=home/'.dsh-improved/redteam';(root/'engagements').mkdir(parents=True)
     db=sqlite3.connect(root/'session-bindings.db');db.executescript('CREATE TABLE session_binding(session_id TEXT);CREATE TABLE session_lineage(session_id TEXT);CREATE TABLE root_archive(root_session TEXT);')
     if defect=='used-store':db.execute("INSERT INTO session_binding VALUES ('private-session')")
     db.commit();db.close()
    self.assertEqual(professional.pristine_basic(home,expected,**({'owned_marker':owned} if owned else {})),defect in ['clean','empty-store','owned-marker'])

 def test_payload_writer_rewrites_approved_absolute_links_and_excludes_credential_paths(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder).resolve();home=root/'home';home.mkdir();module=home/'tools/rea-runtime/bin';module.parent.mkdir(parents=True);module.write_text('program');link=module.parent/'link';link.symlink_to(module)
   output=root/'programs.tgz';summary=professional.write_payload(home,['tools/rea-runtime/bin','tools/rea-runtime/link'],output)
   self.assertEqual(summary['files'],1);self.assertEqual(summary['links'],1)
   stage=root/'stage';stage.mkdir();professional.extract_payload(output,stage)
   self.assertEqual((stage/'tools/rea-runtime/link').read_text(),'program');self.assertFalse((stage/'tools/rea-runtime/link').readlink().is_absolute())
   private=home/'tools/rea-runtime/secrets.env';private.write_text('private')
   with self.assertRaises(ValueError):professional.write_payload(home,['tools/rea-runtime/secrets.env'],root/'bad.tgz')
   self.assertFalse((root/'bad.tgz').exists())

 def test_install_rejects_occupied_target_before_subprocesses_or_staging(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder).resolve();(home/'.dsh').mkdir()
   with patch.object(professional,'HOME',home),patch.object(professional,'dedicated_environment',return_value=True),patch.object(professional.subprocess,'run',side_effect=AssertionError('No command authorized')):
    with self.assertRaisesRegex(ValueError,'Pristine dedicated basic VM required'):professional.install_bundle(home/'bundle','0'*64)
   self.assertEqual([p.name for p in home.iterdir()],['.dsh'])

 def test_build_cli_refuses_a_nondedicated_home_without_creating_output(self):
  with tempfile.TemporaryDirectory() as folder:
   out=Path(folder)/'bundle';r=subprocess.run([sys.executable,'-B',str(SCRIPT),'--build-bundle',str(out)],env={**os.environ,'HOME':folder},capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(out.exists());self.assertFalse(json.loads(r.stdout)['ok'])

 def test_runtime_only_java_cannot_reach_staging_or_docker_mutations(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder).resolve()
   with patch.object(professional,'HOME',home),patch.object(professional,'dedicated_environment',return_value=True),patch.object(professional,'pristine_basic',return_value=True),patch.object(professional,'verify_bundle',return_value={'payloadBytes':1}),patch.object(professional.os,'access',side_effect=lambda path,mode:not str(path).endswith('/javac')),patch.object(professional.subprocess,'check_output',side_effect=AssertionError('Must fail before Docker')):
    with self.assertRaisesRegex(ValueError,'Professional system prerequisite unavailable'):professional.install_bundle(home/'assets','0'*64)
   self.assertEqual(list(home.iterdir()),[])

 def test_payload_state_variants_are_not_program_assets(self):
  for name in ['.env.local','.npmrc','assets.db','session-bindings.db','notes.jsonl','private.key','credentials.yml','debug.log']:
   with self.subTest(name=name):self.assertFalse(professional.allowed('tools/rea-runtime/'+name))
  self.assertTrue(professional.allowed('tools/security-workbench/cache/db/trivy.db'))

 def test_sdk_session_modules_are_programs_but_runtime_session_data_is_excluded(self):
  self.assertTrue(professional.allowed('tools/harness-original-capabilities/node_modules/@anthropic-ai/sdk/lib/sessions/accumulate.js'))
  self.assertTrue(professional.allowed('tools/rea-runtime/node_modules/@modelcontextprotocol/sdk/dist/esm/server/sessions.js'))
  self.assertFalse(professional.allowed('tools/rea-runtime/sessions/private.json'))
  self.assertFalse(professional.allowed('.dsh-improved/storages/workspace.json'))
  self.assertFalse(professional.allowed('tools/rea-runtime/sessions/private-project/node_modules/internal/package.json'))
  self.assertFalse(professional.allowed('.dsh/profiles/web/node_modules/dsh-purge/storages/private.json'))
  self.assertFalse(professional.allowed('tools/rea-runtime/node_modules/@anthropic-ai/sdk/lib/sessions/private.json'))
  self.assertTrue(professional.allowed('tools/harness-original-capabilities/node_modules/@deepseek-ai/dsh-api-session-controller/lib/types/client/sessions/manager.js'))
  self.assertTrue(professional.allowed('tools/harness-original-capabilities/node_modules/openai/resources/beta/agents/sessions/turns.js'))
  self.assertFalse(professional.allowed('tools/harness-original-capabilities/node_modules/openai/resources/beta/agents/sessions/private.json'))

 def test_large_pax_metadata_is_rejected_before_tarfile_member_parsing(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder).resolve();archive=root/'payload.tgz'
   with tarfile.open(archive,'w:gz') as out:
    entry=tarfile.TarInfo('tools/rea-runtime/file');entry.pax_headers={'comment':'x'*20000};entry.size=1;out.addfile(entry,io.BytesIO(b'x'))
   stage=root/'stage';stage.mkdir()
   with patch.object(tarfile.TarFile,'getmembers',side_effect=AssertionError('Metadata must be bounded first')):
    with self.assertRaises(ValueError):professional.extract_payload(archive,stage)
   self.assertEqual(list(stage.iterdir()),[])

 def test_readiness_cannot_pass_when_a_fixed_local_tool_is_missing(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder).resolve()
   with patch.object(professional.subprocess,'run',side_effect=AssertionError('Missing file must fail before processes')):
    with self.assertRaises((ValueError,OSError)):professional.verify_installation(home)

 def test_zero_trailer_and_pax_size_cannot_bypass_raw_archive_limits(self):
  for defect in ['zero-trailer','pax-size']:
   with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
    root=Path(folder).resolve();archive=root/'payload.tgz'
    with tarfile.open(archive,'w:gz') as out:
     entry=tarfile.TarInfo('tools/rea-runtime/file');entry.size=1
     if defect=='pax-size':entry.pax_headers={'size':'1'}
     out.addfile(entry,io.BytesIO(b'x'))
    if defect=='zero-trailer':
     with gzip.open(archive,'ab') as out:out.write(b'\0'*2*1024*1024)
    stage=root/'stage';stage.mkdir()
    with patch.object(tarfile.TarFile,'getmembers',side_effect=AssertionError('Reject before tarfile interpretation')):
     with self.assertRaises(ValueError):professional.extract_payload(archive,stage)
    self.assertEqual(list(stage.iterdir()),[])

 def test_original_runtime_verification_checks_content_and_link_inventory(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder).resolve();runtime=home/'tools/harness-original-capabilities';runtime.mkdir(parents=True);(runtime/'module.js').write_bytes(b'original');(runtime/'link.js').symlink_to('module.js')
   value={'source':'/home/purge/.local/lib/node_modules/@deepseek-ai/dsh','files':{'module.js':{'sha256':hashlib.sha256(b'original').hexdigest()},'link.js':{'link':'module.js'}}};(runtime/'.personal-runtime-manifest.json').write_text(json.dumps(value))
   self.assertEqual(professional.verify_original_runtime(home),2)
   (runtime/'module.js').write_bytes(b'changed')
   with self.assertRaises(ValueError):professional.verify_original_runtime(home)
   (runtime/'module.js').write_bytes(b'original');(runtime/'link.js').unlink();(runtime/'link.js').symlink_to('/etc/passwd')
   with self.assertRaises(ValueError):professional.verify_original_runtime(home)

if __name__=='__main__':unittest.main()
