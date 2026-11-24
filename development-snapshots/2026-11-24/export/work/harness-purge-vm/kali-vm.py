#!/usr/bin/env python3
"""Use the dedicated Kali SSH connection from inside the Harness VM."""
from pathlib import Path
import os,shlex,sys

STATUS_SOURCE="import json,os,platform; from pathlib import Path; print(json.dumps({'hostname':platform.node(),'uid':os.getuid(),'kernel':platform.release(),'osRelease':Path('/etc/os-release').read_text(),'persistentInstall':Path('/var/lib/harness-kali-install-complete').is_file()}))"
TOOL_NAMES={'nmap': ['nmap'], 'nuclei': ['nuclei'], 'masscan': ['masscan'], 'fscan': ['fscan'], 'gogo': ['gogo'], 'suo5': ['suo5'], 'frpc': ['frpc'], 'frps': ['frps'], 'chisel': ['chisel'], 'ffuf': ['ffuf'], 'httpx': ['httpx-toolkit', 'pd-httpx', 'httpx'], 'dnsx': ['dnsx'], 'subfinder': ['subfinder'], 'ksubdomain': ['ksubdomain'], 'impacket': ['impacket-secretsdump', 'secretsdump.py'], 'curl': ['curl'], 'wget': ['wget'], 'dig': ['dig'], 'openssl': ['openssl'], 'tcpdump': ['tcpdump'], 'tshark': ['tshark'], 'whatweb': ['whatweb'], 'nikto': ['nikto'], 'sqlmap': ['sqlmap'], 'file': ['file'], 'strings': ['strings']}
DISCOVERY_SOURCE='names='+repr(TOOL_NAMES)+'\n'+r'''
import json,os,platform,shutil,sys
from pathlib import Path
def locate(identity):
 for name in names[identity]:
  home=Path.home()
  directories=[part for part in os.environ.get('PATH','').split(os.pathsep) if os.path.isabs(part)]
  directories.extend([str(home/'.local/bin'),str(home/'go/bin'),str(home/'.pdtm/go/bin')])
  search=os.pathsep.join(dict.fromkeys(directories))
  value=shutil.which(name,path=search)
  if not value:continue
  if identity=='httpx':
   try:
    with open(value,'rb') as file:head=file.read(256)
   except OSError:continue
   if head.startswith(b'#!') and b'python' in head.split(b'\n')[0].lower():continue
  return value
 return None
'''
INVENTORY_SOURCE=DISCOVERY_SOURCE+r'''
release={}
for line in Path('/etc/os-release').read_text().splitlines():
 key,sep,value=line.partition('=')
 if sep:release[key]=value.strip('"')
print(json.dumps({'hostname':platform.node(),'uid':os.getuid(),'kernel':platform.release(),'osId':release.get('ID'),'version':release.get('VERSION_ID'),'persistentInstall':Path('/var/lib/harness-kali-install-complete').is_file(),'tools':{key:locate(key) for key in names}}))
'''
TOOL_SOURCE=DISCOVERY_SOURCE+r'''
identity=sys.argv[1]
value=locate(identity)
if not value:
 print('Requested tool is not installed in Kali: '+identity,file=sys.stderr);sys.exit(127)
os.execv(value,[value,*sys.argv[2:]])
'''

def ssh_argv(arguments,home):
    argv=['/usr/bin/ssh','-F',str(home/'.config/harness-kali/ssh_config'),'--','kali-lab']
    if arguments==['shell']:return argv
    if arguments==['status']:return argv+[shlex.join(['python3','-c',STATUS_SOURCE])]
    if arguments==['inventory']:return argv+[shlex.join(['python3','-c',INVENTORY_SOURCE])]
    if arguments[:1]==['tool'] and len(arguments)>=2 and arguments[1] in TOOL_NAMES:
        return argv+[shlex.join(['python3','-c',TOOL_SOURCE,*arguments[1:]])]
    if arguments[:1]==['exec']:
        command=arguments[1:]
        if command[:1]==['--']:command=command[1:]
        if command:return argv+[shlex.join(command)]
    raise ValueError('Usage: kali-vm status | inventory | shell | tool ID [ARG ...] | exec -- COMMAND [ARG ...]')

def main():
    try:argv=ssh_argv(sys.argv[1:],Path.home())
    except ValueError as error:print(error,file=sys.stderr);return 2
    # Preserve stdin, terminal signals and exit code. No retries or elevation.
    os.execv(argv[0],argv)

if __name__=='__main__':raise SystemExit(main())
