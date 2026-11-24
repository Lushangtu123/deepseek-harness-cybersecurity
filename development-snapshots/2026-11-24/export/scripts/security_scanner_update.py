#!/usr/bin/env python3
"""Mac entry to offline Semgrep candidate admission in the dedicated VM."""
import argparse,json,re,shlex,subprocess,sys
from security_db_update import load_manager
GUEST='/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-scanner-update.py'
# Keep in sync with the VM updater. Parser readiness does not establish publisher trust.
VERIFIED_SEMGREP_PUBLISHER_PINS=frozenset()

class PublisherEvidenceMissing(ValueError):pass


def run_candidate(*,image_id=None,version=None,expected_manifest=None,apply=False,recover=False,confirm=False,manager=None):
 if recover:
  if not confirm or any([image_id,version,expected_manifest,apply]):raise ValueError('Explicit isolated recovery required')
  args=['--recover-last','--confirm']
 else:
  if not isinstance(image_id,str) or not re.fullmatch('sha256:[a-f0-9]{64}',image_id) or not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise ValueError('Immutable local candidate and exact version required')
  args=['--image-id',image_id,'--version',version]
  if apply:
   if not confirm or not isinstance(expected_manifest,str) or not re.fullmatch('[a-f0-9]{64}',expected_manifest):raise ValueError('Expected manifest and confirmation required')
   if (image_id,version) not in VERIFIED_SEMGREP_PUBLISHER_PINS:raise PublisherEvidenceMissing('Semgrep 候选缺少已验证的发布者证据，保留现用版本。')
   args+=['--apply','--expected-manifest-sha256',expected_manifest,'--confirm']
  elif confirm or expected_manifest:raise ValueError('Unexpected check arguments')
 manager=manager or load_manager();command='python3 -B '+shlex.join([GUEST,*args])
 def invoke():
  code=0
  try:r=manager.ssh(command,timeout=170,phase='program-update' if apply or recover else 'native-check');raw=r.stdout
  except subprocess.CalledProcessError as error:code=error.returncode;raw=error.stdout or ''
  if len(raw.encode())>32768:raise ValueError('Candidate response exceeds bound')
  value=json.loads(raw)
  if not isinstance(value,dict) or code not in [0,1,2,130]:raise ValueError('Candidate result unconfirmed')
  if code==0 and (apply and type(value.get('changed')) is not bool or recover and value.get('recovered') is not True or not apply and not recover and (value.get('admitted') is not True or value.get('changed') is not False)):raise ValueError('Candidate result unconfirmed')
  return value,code
 if apply or recover:
  with manager.vm_operation('switch'):
   manager.validate()
   try:return invoke()
   finally:manager.start(quiet=True)
 return invoke()

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image-id');parser.add_argument('--version');parser.add_argument('--expected-manifest-sha256');mode=parser.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--recover-last',action='store_true');parser.add_argument('--confirm',action='store_true');args=parser.parse_args(argv)
 try:
  value,code=run_candidate(image_id=args.image_id,version=args.version,expected_manifest=args.expected_manifest_sha256,apply=args.apply,recover=args.recover_last,confirm=args.confirm);print(json.dumps(value,ensure_ascii=False,indent=2));return code
 except PublisherEvidenceMissing as error:print(str(error));return 2
 except KeyboardInterrupt:print('已中断；请先核对维护状态，不自动重试。');return 130
 except Exception:print('扫描器候选操作未确认；请检查 VM 与维护记录，不自动下载、切换或重试。');return 1
if __name__=='__main__':raise SystemExit(main())
