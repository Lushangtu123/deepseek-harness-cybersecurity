import {createHash} from 'node:crypto';
import {realpathSync} from 'node:fs';
import {join} from 'node:path';
import {readReviewFile,safeSnapshotName} from './personal-review-snapshot.mjs';

const FILE_BYTES=1048576,TOTAL_BYTES=8388608;
const hash=raw=>createHash('sha256').update(raw).digest('hex');
const sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const integer=(value,min,max)=>Number.isSafeInteger(value)&&value>=min&&value<=max;
const point=value=>value&&integer(value.line,1,FILE_BYTES+1)&&integer(value.col,1,FILE_BYTES+1)&&integer(value.offset,0,FILE_BYTES);
const span=value=>value?.version===1&&safeSnapshotName(value.path)&&point(value.start)&&point(value.end)&&
 value.end.offset>value.start.offset&&(value.end.line>value.start.line||value.end.line===value.start.line&&value.end.col>value.start.col);

export function semgrepSourceSpan(row){
 const path=typeof row?.path==='string'?row.path.replace(/^\/src\//,''):null;
 const value={version:1,path,start:row?.start,end:row?.end};
 return span(value)?{version:1,path,start:{line:value.start.line,col:value.start.col,offset:value.start.offset},end:{line:value.end.line,col:value.end.col,offset:value.end.offset}}:null;
}

function bytePositions(raw,offsets){
 const result=new Map();let cursor=0,line=1,start=0,next=raw.indexOf(10);
 for(const offset of [...new Set(offsets)].sort((a,b)=>a-b)){
  while(next>=0&&next<offset){line++;start=next+1;cursor=start;next=raw.indexOf(10,cursor)}
  result.set(offset,{line,col:offset-start+1});
 }
 return result;
}

// Bind only managed-copy bytes. This says nothing about AST calls, execution,
// original unredacted files, or vulnerability truth. Findings are never mutated.
export function bindSemgrepSourceLocations(snapshot,findings){
 if(!Array.isArray(findings)||findings.length>2000)throw Error('源码位置收录超出上限');
 const locations=findings.map(()=>({version:1,state:'unavailable',reason:'missing-or-invalid-span'}));
 const groups=new Map();let files;
 try{
  if(!sha(snapshot?.id)||typeof snapshot.sourceRoot!=='string'||realpathSync(snapshot.sourceRoot)!==snapshot.sourceRoot||
   !Array.isArray(snapshot.files)||snapshot.files.length>1000)throw Error();
  files=new Map();
  for(const file of snapshot.files){
   if(!safeSnapshotName(file?.path)||!sha(file.sha256)||!integer(file.bytes,0,FILE_BYTES)||typeof file.redacted!=='boolean'||files.has(file.path))throw Error();
   files.set(file.path,file);
  }
 }catch{files=null;for(const row of locations)row.reason='snapshot-unavailable'}
 if(files)for(const [index,finding] of findings.entries()){
  const value=finding?.scannerSpan;
  if(!span(value))continue;
  if(finding.location!==value.path+':'+value.start.line||!files.has(value.path)){locations[index].reason='span-not-in-snapshot';continue}
  if(!groups.has(value.path))groups.set(value.path,[]);
  groups.get(value.path).push({index,value});
 }
 let readBytes=0;
 for(const [path,requests] of groups){
  const file=files.get(path);let raw,positions,reason='source-unavailable';
  try{
   if(file.bytes>TOTAL_BYTES-readBytes){reason='source-read-budget';throw Error()}
   // Reserve the admitted size before reading, including failed reads. A changed
   // larger file is refused by the reader before its bytes are materialized.
   readBytes+=file.bytes;
   raw=readReviewFile(join(snapshot.sourceRoot,path),file.bytes);
   if(raw.length!==file.bytes||hash(raw)!==file.sha256){reason='source-digest-mismatch';throw Error()}
   new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw);
   for(let i=0;i<raw.length;i++)if(raw[i]===13&&raw[i+1]!==10){reason='source-range-mismatch';throw Error()}
   positions=bytePositions(raw,requests.flatMap(({value})=>[value.start.offset,value.end.offset]));
  }catch{for(const {index} of requests)locations[index].reason=reason;continue}
  for(const {index,value} of requests){
   const matches=p=>p.offset<=raw.length&&positions.get(p.offset)?.line===p.line&&positions.get(p.offset)?.col===p.col&&
    (p.offset===raw.length||(raw[p.offset]&0xc0)!==0x80);
   if(!matches(value.start)||!matches(value.end)){locations[index].reason='source-range-mismatch';continue}
   locations[index]={version:1,state:'bound',scope:'managed-source-copy',snapshotId:snapshot.id,path,
    sourceSha256:file.sha256,byteLength:raw.length,copyRedacted:file.redacted===true,
    start:{line:value.start.line,col:value.start.col,offset:value.start.offset},
    end:{line:value.end.line,col:value.end.col,offset:value.end.offset}};
  }
 }
 const bound=locations.filter(row=>row.state==='bound').length;
 for(const location of locations){if(location.start)Object.freeze(location.start);if(location.end)Object.freeze(location.end);Object.freeze(location)}
 return{findings:Object.freeze(findings.map((row,index)=>Object.freeze({...row,sourceLocation:locations[index]}))),
  summary:{version:1,state:bound===findings.length?'completed':bound===0?'unavailable':'partial',total:findings.length,bound,unavailable:findings.length-bound}};
}

export function sourceLocationKey(value){
 return value?.state==='bound'&&sha(value.snapshotId)&&sha(value.sourceSha256)&&span(value)?
  JSON.stringify([value.snapshotId,value.sourceSha256,value.path,value.start.line,value.start.col,value.start.offset,value.end.line,value.end.col,value.end.offset]):null;
}
