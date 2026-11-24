from pathlib import Path
from tempfile import TemporaryDirectory
import base64,gzip,hashlib,json,subprocess
payload=json.loads(gzip.decompress(base64.b64decode(PAYLOAD)))
runtime=Path('/home/purge/tools/security-workbench')
manifest_bytes=(runtime/'images.json').read_bytes();rules_before=(runtime/'rules.json').read_bytes()
manifest=json.loads(manifest_bytes);image=next(row for row in manifest['tools'] if row['tool']=='semgrep')
candidate=payload['candidateRules'].encode()
with TemporaryDirectory(prefix='ordinary-rules-',dir='/home/purge/.cache') as temporary:
 root=Path(temporary);root.chmod(0o755);samples=root/'samples';samples.mkdir(mode=0o755)
 for case in payload['cases']:
  if Path(case['file']).name!=case['file']:raise ValueError('Unsafe fixture name')
  (samples/case['file']).write_text(case['source'])
 pin=root/'rules.json';pin.write_bytes(rules_before if payload['phase']=='baseline' else candidate);pin.chmod(0o444)
 policy=root/'policy-output.sh';policy.write_text(payload['outputPolicy']);policy.chmod(0o444)
 name=root.name;docker=['/usr/bin/sudo','-n','/usr/bin/docker']
 args=[*docker,'run','--rm','--pull','never','--name',name,'--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','768m','--memory-swap','768m','--cpus','1','--pids-limit','64','--log-driver','none','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=134217728,mode=1777','--tmpfs','/out:rw,nosuid,nodev,noexec,size=16777216,uid=1000,gid=1000,mode=0700','--env','HOME=/tmp','--env','SEMGREP_SEND_METRICS=off','--mount',f'type=bind,src={samples},dst=/src,readonly','--mount',f'type=bind,src={pin},dst=/policy/rules.json,readonly','--mount',f'type=bind,src={policy},dst=/policy-output.sh,readonly','--entrypoint','/bin/sh',image['imageId'],'/policy-output.sh','/out','--deadline-seconds','60','semgrep','scan','--config','/policy/rules.json','--json','--output','/out/result.json','--metrics=off','--disable-version-check','--jobs','1','--timeout','5','--max-target-bytes','1000000','/src']
 try:
  scan=subprocess.run(args,capture_output=True,text=True,timeout=80)
 finally:
  subprocess.run([*docker,'rm','-f',name],capture_output=True,timeout=10)
 native=json.loads(scan.stdout) if scan.stdout.strip() else None
 result={'phase':payload['phase'],'imageId':image['imageId'],'rulesSha256':hashlib.sha256(pin.read_bytes()).hexdigest(),'datasetSha256':payload['datasetSha256'],'caseIds':[case['id'] for case in payload['cases']],'scannerExitCode':scan.returncode,'native':native,'stderr':scan.stderr[-2000:]}
result['temporaryRemoved']=not root.exists()
remaining=subprocess.run([*docker,'ps','-aq','--filter',f'name=^{name}$'],capture_output=True,text=True,check=True,timeout=10)
result['containerAbsent']=not remaining.stdout.strip()
result['runtimeRulesUnchanged']=(runtime/'rules.json').read_bytes()==rules_before
result['scannerManifestUnchanged']=(runtime/'images.json').read_bytes()==manifest_bytes
print(json.dumps(result))
raise SystemExit(0 if scan.returncode==0 and all(result[key] for key in ['temporaryRemoved','containerAbsent','runtimeRulesUnchanged','scannerManifestUnchanged']) else 1)
