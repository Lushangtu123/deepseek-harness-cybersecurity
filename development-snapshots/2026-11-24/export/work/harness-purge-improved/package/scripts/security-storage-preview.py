#!/usr/bin/env python3
"""Read-only VM storage metadata and cleanup preview. No deletion or apply mode."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,re,stat,subprocess,sys,time
HOME=Path('/home/purge');GIB=1024**3

def capacity(total,available,*,inode_total=0,inode_available=0):
 if any(type(v) is not int or v<0 for v in [total,available,inode_total,inode_available]) or total<=0 or available>total or inode_available>inode_total:raise ValueError('Invalid filesystem counters')
 ratio=available/total;state='critical' if available<5*GIB or ratio<.05 else 'warning' if available<10*GIB or ratio<.15 else 'healthy'
 if inode_total:
  free=inode_available/inode_total
  if free<.05:state='critical'
  elif free<.15 and state=='healthy':state='warning'
 return {'state':state,'totalBytes':total,'availableBytes':available,'availablePercent':round(ratio*100,2),'inodeTotal':inode_total,'inodeAvailable':inode_available,'policy':{'warningFreeBytes':10*GIB,'criticalFreeBytes':5*GIB,'warningFreePercent':15,'criticalFreePercent':5,'warningFreeInodePercent':15,'criticalFreeInodePercent':5}}

def directory_fd(path):
 path=Path(path)
 if not path.is_absolute() or any(part in ['.','..'] for part in path.parts):raise ValueError('Absolute directory required')
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC;fd=os.open('/',flags)
 try:
  for part in path.parts[1:]:
   child=os.open(part,flags,dir_fd=fd);os.close(fd);fd=child
  return fd
 except BaseException:os.close(fd);raise

def measure(path,*,max_entries=30000,seconds=2):
 path=Path(path);deadline=time.monotonic()+seconds;seen=set();reasons=set();counts={'entries':0,'fileCount':0,'apparentBytes':0,'allocatedBytes':0,'linksSkipped':0};flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC
 def walk(fd,depth,device):
  if depth>32:reasons.add('depth-limit');return
  before=os.fstat(fd)
  try:
   with os.scandir(fd) as listing:
    for entry in listing:
     if counts['entries']>=max_entries:reasons.add('entry-limit');break
     if time.monotonic()>=deadline:reasons.add('time-limit');break
     counts['entries']+=1
     try:
      info=entry.stat(follow_symlinks=False)
      if stat.S_ISLNK(info.st_mode):counts['linksSkipped']+=1;continue
      if info.st_dev!=device:reasons.add('other-filesystem');continue
      if stat.S_ISDIR(info.st_mode):
       child=os.open(entry.name,flags,dir_fd=fd)
       try:
        actual=os.fstat(child)
        if (actual.st_dev,actual.st_ino)!=(info.st_dev,info.st_ino):reasons.add('changed');continue
        walk(child,depth+1,device)
        after=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
        if (after.st_dev,after.st_ino)!=(info.st_dev,info.st_ino):reasons.add('changed')
       finally:os.close(child)
      elif stat.S_ISREG(info.st_mode):
       key=(info.st_dev,info.st_ino)
       if key in seen:continue
       seen.add(key);counts['fileCount']+=1;counts['apparentBytes']+=info.st_size;counts['allocatedBytes']+=info.st_blocks*512
     except OSError:reasons.add('read-error')
  except OSError:reasons.add('read-error')
  after=os.fstat(fd)
  if (before.st_mtime_ns,before.st_ctime_ns)!=(after.st_mtime_ns,after.st_ctime_ns):reasons.add('changed')
 try:
  if path.resolve()!=path:raise ValueError('Linked root')
  fd=directory_fd(path)
  try:initial=os.fstat(fd);walk(fd,0,initial.st_dev)
  finally:os.close(fd)
  after=path.lstat()
  if path.resolve()!=path:reasons.add('changed')
  if (after.st_dev,after.st_ino)!=(initial.st_dev,initial.st_ino):reasons.add('changed')
  return {'state':'observed' if not reasons else 'partial','complete':not reasons,**counts,'reasons':sorted(reasons),'sizeBasis':'regular file metadata; hardlinks deduplicated within object; excludes directory metadata; lower bound when partial'}
 except FileNotFoundError:return {'state':'missing','complete':False,'allocatedBytes':None,'apparentBytes':None,'reasons':['not-present']}
 except (OSError,ValueError):return {'state':'unavailable','complete':False,'allocatedBytes':None,'apparentBytes':None,'reasons':['not-observed']}

GROUPS=[('workspace','项目文件','项目源码和用户文件，保留'),('.dsh-improved/redteam','审计与报告','包含数据库、发现与运行记录，保留'),('tools','程序与扫描资产','运行程序、固定镜像配置及漏洞库，保留'),('downloads','下载与验收目录','来源与依赖未逐项确认，保留'),('tools/security-workbench/backups','漏洞库备份','回滚备份，需逐项确认依赖后再决定'),('tools/security-workbench/scanner-backups','扫描器清单备份','回滚事务记录，保留'),('.dsh-improved/security-auth','私有会话','账号相关目录，仅计元数据，不展示子项，保留')]

def children(path,limit=20):
 path=Path(path);items=[];names=[];complete=True;flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK
 try:
  if path.resolve()!=path:raise ValueError('Unsafe preview root')
  fd=directory_fd(path);identity=os.fstat(fd)
  try:
   with os.scandir(fd) as listing:
    for index,entry in enumerate(listing):
     if index>=512:complete=False;break
     if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}',entry.name) or re.search('credential|secret|token|provider',entry.name,re.I):continue
     if entry.is_dir(follow_symlinks=False):names.append(entry.name)
  finally:os.close(fd)
  current=path.lstat()
  if path.resolve()!=path or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):complete=False
  if len(names)>limit:complete=False
  for name in sorted(names)[:limit]:
   items.append({'id':name,'path':str(path/name),'action':'review','deletionApproved':False,'reason':'仅列入人工核对；尚未确认任务、回滚或恢复依赖，禁止直接按预览删除','usage':measure(path/name,max_entries=10000,seconds=.15)})
  current=path.lstat()
  if path.resolve()!=path or (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):complete=False
  complete=complete and all(row['usage']['complete'] for row in items)
  return {'state':'observed' if complete else 'partial','complete':complete,'items':items,'notice':'最多列20个安全名称目录；这不是获准清理清单，不估算可释放量'}
 except FileNotFoundError:return {'state':'missing','complete':False,'items':[]}
 except (OSError,ValueError):return {'state':'unavailable','complete':False,'items':[]}

def docker_summary():
 try:
  result=subprocess.run(['sudo','-n','/usr/bin/docker','system','df','--format','{{json .}}'],capture_output=True,text=True,timeout=8)
  if result.returncode or len(result.stdout)>16384:raise ValueError('Docker summary unavailable')
  rows=[]
  for line in result.stdout.splitlines():
   value=json.loads(line)
   if value.get('Type') not in ['Images','Containers','Local Volumes','Build Cache'] or len(rows)>=4:raise ValueError('Unexpected Docker summary')
   row={key:value.get(key) for key in ['Type','TotalCount','Active','Size','Reclaimable']}
   if any(not isinstance(v,(str,int)) or isinstance(v,bool) or len(str(v))>128 or re.search(r'[\x00-\x1f]',str(v)) for v in row.values()):raise ValueError('Invalid Docker fields')
   rows.append(row)
  if not rows:raise ValueError('Missing Docker counters')
  return {'state':'observed','rows':rows,'action':'retain','reason':'Docker估算可回收量不代表获准删除；固定镜像、容器和卷仍保留'}
 except (OSError,ValueError,subprocess.SubprocessError):return {'state':'unavailable','rows':[],'action':'retain','reason':'Docker用量未确认，不能推断为零或据此清理'}

def preview(home=HOME,*,docker=True,capacity_only=False):
 home=Path(home)
 if home.resolve()!=home or not home.is_dir():raise ValueError('Ordinary home required')
 try:
  fd=directory_fd(home)
  try:
   initial=os.fstat(fd);space=os.fstatvfs(fd);current=home.lstat()
   if home.resolve()!=home or (current.st_dev,current.st_ino)!=(initial.st_dev,initial.st_ino):raise ValueError('Changed home')
   filesystem=capacity(space.f_blocks*space.f_frsize,space.f_bavail*space.f_frsize,inode_total=space.f_files,inode_available=space.f_favail)
  finally:os.close(fd)
 except (OSError,ValueError):filesystem={'state':'unknown','totalBytes':None,'availableBytes':None}
 if capacity_only:return {'version':1,'readOnly':True,'automaticChanges':False,'deletionAvailable':False,'checkedAt':datetime.now(timezone.utc).isoformat(),'filesystem':filesystem}
 objects=[]
 for relative,title,reason in GROUPS:
  objects.append({'id':relative,'title':title,'path':str(home/relative),'action':'retain','reason':reason,'usage':measure(home/relative)})
 return {'version':1,'readOnly':True,'automaticChanges':False,'checkedAt':datetime.now(timezone.utc).isoformat(),'filesystem':filesystem,'objects':objects,'reviewDirectories':children(home/'downloads'),'docker':docker_summary() if docker else {'state':'not-requested'},'notice':'按需只读预览；不读取文件内容，不自动清理。目录可能重叠，不相加；allocatedBytes不等于实际可释放空间。','deletionAvailable':False}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--without-docker',action='store_true');parser.add_argument('--capacity-only',action='store_true');args=parser.parse_args()
 try:
  if sys.platform!='linux' or Path.home()!=HOME or os.getuid()!=1000:raise ValueError('Dedicated VM required')
  print(json.dumps(preview(docker=not args.without_docker,capacity_only=args.capacity_only),ensure_ascii=False,indent=2));return 0
 except Exception:print(json.dumps({'version':1,'readOnly':True,'automaticChanges':False,'error':'存储状态未确认；不会清理或启动其他操作。'},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
