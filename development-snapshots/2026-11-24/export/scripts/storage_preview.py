#!/usr/bin/env python3
"""Read-only host/VM capacity and recovery cleanup preview; never starts or deletes."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,importlib.util,json,subprocess
from security_db_update import load_manager
GUEST='/home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-storage-preview.py'

def capacity(total,available):
 if type(total) is not int or type(available) is not int or total<=0 or not 0<=available<=total:raise ValueError('Invalid host filesystem counters')
 ratio=available/total;gib=1024**3;state='critical' if available<5*gib or ratio<.05 else 'warning' if available<10*gib or ratio<.15 else 'healthy'
 return {'state':state,'totalBytes':total,'availableBytes':available,'availablePercent':round(ratio*100,2)}

def collect(*,manager=None,archive_after=None,snapshot_after=None):
 manager=manager or load_manager();manager.validate();state=manager.vm_status();guest={'state':'not-running' if state=='stopped' else 'unavailable'}
 if state=='started':
  try:
   r=manager.ssh('python3 -B '+GUEST,timeout=45,phase='native-check')
   if len(r.stdout.encode())>131072:raise ValueError('Guest storage response exceeds bound')
   value=json.loads(r.stdout)
   if not isinstance(value,dict) or value.get('version')!=1 or value.get('readOnly') is not True or value.get('automaticChanges') is not False or value.get('deletionAvailable') is not False or not isinstance(value.get('objects'),list) or len(value['objects'])>10 or value.get('filesystem',{}).get('state') not in ['healthy','warning','critical','unknown']:raise ValueError('Invalid guest report')
   guest={'state':'observed','report':value}
  except (OSError,ValueError,subprocess.SubprocessError):guest={'state':'unavailable','reason':'VM用量未确认；不会自动启动或重试'}
 try:
  catalog=manager.recovery_catalog(after=archive_after,snapshot_after=snapshot_after)
  if not isinstance(catalog,dict) or catalog.get('readOnly') is not True:raise ValueError('Recovery catalog invalid')
 except (OSError,ValueError,subprocess.SubprocessError):catalog={'readOnly':True,'truncated':True,'snapshotState':'unavailable','snapshots':[],'images':[],'storage':None}
 storage=catalog.get('storage');host={'state':'unknown','totalBytes':None,'availableBytes':None}
 try:host=capacity(storage['totalBytes'],storage['freeBytes'])
 except (TypeError,KeyError,ValueError):pass
 recovery=[]
 for row in catalog.get('snapshots',[]):
  protected=row.get('protected') is True or row.get('current') is True or row.get('name')==catalog.get('currentRecovery')
  review=not protected and row.get('reviewCandidate') is True and row.get('present') is True
  recovery.append({'type':'snapshot','id':row['name'],'action':'review' if review else 'retain','deletionApproved':False,'protected':protected,'reason':'当前、基础或近期受保护恢复点，保留' if protected else '仅供人工核对；仍需确认恢复依赖，当前未获准删除','allocatedBytes':None,'reclaimableBytes':None,'present':row.get('present'),'bundleState':row.get('bundleState')})
 for row in catalog.get('images',[]):
  recovery.append({'type':'archived-image','id':row['id'],'action':'review' if row.get('reviewCandidate') is True else 'retain','deletionApproved':False,'reason':'归档候选，需确认没有运行引用及恢复依赖；本预览不批准删除','logicalBytes':row.get('logicalBytes'),'allocatedBytes':row.get('allocatedBytes'),'reclaimableBytes':None})
 return {'version':1,'readOnly':True,'automaticChanges':False,'deletionAvailable':False,'checkedAt':datetime.now(timezone.utc).isoformat(),'hostFilesystem':host,'primaryVmDisk':{'action':'retain','reason':'日常运行主盘，禁止作为清理候选','logicalBytes':storage.get('primaryLogicalBytes') if isinstance(storage,dict) else None,'allocatedBytes':storage.get('primaryAllocatedBytes') if isinstance(storage,dict) else None,'reclaimableBytes':None},'guest':guest,'recoveryPreview':recovery,'catalogComplete':not catalog.get('truncated',True) and catalog.get('snapshotState')=='observed' and not catalog.get('nextCursor') and not catalog.get('nextSnapshotCursor'),'catalogScan':catalog.get('archiveScan'),'nextArchiveCursor':catalog.get('nextCursor'),'nextSnapshotCursor':catalog.get('nextSnapshotCursor'),'notice':'按需预览，不后台监控、不自动清理；对象可能共享空间，不相加。快照和COW镜像的实际可释放量未知。'}

def render(value):
 def size(n):return '未确认' if type(n) is not int else f'{n/1024**3:.2f} GiB'
 lines=['存储监测与清理预览（只读） · '+value['checkedAt']]
 for title,space in [('承载VM的Mac文件系统',value['hostFilesystem']),('VM文件系统',value['guest'].get('report',{}).get('filesystem',{'state':value['guest']['state']}))]:lines.append(title+'：'+{'healthy':'正常','warning':'预警','critical':'紧急','unknown':'未确认','not-running':'VM未启动','unavailable':'未确认'}.get(space['state'],'未确认')+' · 可用 '+size(space.get('availableBytes'))+' / '+size(space.get('totalBytes')))
 lines.append('阈值：可用少于10GiB或15%为预警，少于5GiB或5%为紧急；VM inode亦按15%/5%检查。')
 lines.append('主盘：保留 · 已分配 '+size(value['primaryVmDisk']['allocatedBytes']))
 report=value['guest'].get('report',{})
 for row in report.get('objects',[]):lines.append(row['title']+'：'+size(row['usage']['allocatedBytes'])+' · '+row['usage']['state']+' · '+row['reason'])
 for row in report.get('reviewDirectories',{}).get('items',[]):lines.append('待核对目录 '+row['path']+'：'+size(row['usage']['allocatedBytes'])+' · '+row['usage']['state']+' · '+row['reason'])
 for row in value['recoveryPreview']:lines.append(('保留 ' if row['action']=='retain' else '待核对 ')+row['type']+' '+row['id']+' · 已分配 '+size(row.get('allocatedBytes'))+' · '+row['reason'])
 lines.append('VM目录候选列表：'+('本页完整' if report.get('reviewDirectories',{}).get('complete') is True else '未完整或未确认；最多列20个目录，详见JSON状态'))
 docker=report.get('docker',{});lines.append('Docker汇总：'+str(docker.get('state','unavailable')))
 for row in docker.get('rows',[]):lines.append(str(row['Type'])+' · '+str(row['Size'])+' · Docker估算可回收 '+str(row['Reclaimable'])+'（不代表获准删除）')
 lines.append('恢复目录完整性：'+('本页完整' if value['catalogComplete'] else '未完整；如有JSON游标可继续读取，读取错误或深度限制请查catalogScan，不能据此认定没有其他对象'))
 lines.append(value['notice']);lines.append('当前没有执行任何清理。实际删除需另行列明对象并取得确认。');return '\n'.join(lines)

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');parser.add_argument('--archive-after');parser.add_argument('--snapshot-after');args=parser.parse_args(argv)
 try:
  value=collect(archive_after=args.archive_after,snapshot_after=args.snapshot_after);print(json.dumps(value,ensure_ascii=False,indent=2) if args.json else render(value));return 0
 except Exception:print('存储预览未完成；不会启动VM、修改数据或执行清理。');return 1
if __name__=='__main__':raise SystemExit(main())
