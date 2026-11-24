import {constants,openSync,closeSync,lstatSync,fstatSync,readSync,realpathSync} from 'node:fs';
import {join,relative,isAbsolute,sep} from 'node:path';

const POLICY='parser-text-1',MAX_FILES=20,MAX_BYTES=1000000,MAX_TOTAL=8*1024*1024;
const checks=[['eval',/\beval\s*\(/,'eval 调用字样'],['innerhtml',/\.innerHTML\s*=/,'innerHTML 赋值字样'],['function-constructor',/\bnew\s+Function\s*\(/,'Function 构造字样']];
export function validParserTextSummary(s){
 return !!s&&typeof s==='object'&&!Array.isArray(s)&&Object.keys(s).sort().join(',')===['version','policy','candidateFiles','checkedFiles','skippedFiles','hints','truncated'].sort().join(',')&&s.version===1&&s.policy===POLICY&&['candidateFiles','checkedFiles','skippedFiles','hints'].every(k=>Number.isSafeInteger(s[k])&&s[k]>=0)&&s.candidateFiles<=20000&&s.checkedFiles<=MAX_FILES&&s.checkedFiles+s.skippedFiles===s.candidateFiles&&s.hints<=s.checkedFiles*checks.length&&typeof s.truncated==='boolean';
}
// Deliberately lexical: comments/strings can match; this never supplies semantic coverage.
export function supplementParserGaps(root,errors,{signal,deadline=Infinity,identity=null}={}){
 const pending=()=>{if(signal?.aborted)throw Object.assign(Error('文本补查已取消'),{name:'AbortError'});if(performance.now()>deadline)throw Object.assign(Error('文本补查超时'),{code:'SCAN_TIMEOUT'})};
 pending();
 const scopeChanged=()=>Object.assign(Error('仓库目录已变化，未执行文本补查'),{code:'SCAN_SCOPE_CHANGED'});
 const stableRoot=()=>{try{const info=lstatSync(root);if(!info.isDirectory()||info.isSymbolicLink()||realpathSync(root)!==root||identity&&(info.dev!==identity.dev||info.ino!==identity.ino))throw scopeChanged()}catch{throw scopeChanged()}};
 stableRoot();const canonical=root,candidates=new Set(),findings=[];let checkedFiles=0,skippedFiles=0,consideredFiles=0,totalBytes=0,truncated=false;
 let locationCount=0;
 locations:for(const error of errors.slice(0,20000)){
  const kind=Array.isArray(error?.type)?error.type[0]:error?.type;if(!['PartialParsing','ParseError','SyntaxError'].includes(kind))continue;
  const grouped=Array.isArray(error.type)&&Array.isArray(error.type[1])?error.type[1]:null;
  for(const location of grouped?.length?grouped:[null]){pending();if(locationCount++>=20000){truncated=true;break locations}const path=location?.path||error.path||'';candidates.add(typeof path==='string'?path:'')}
 }
 if(errors.length>20000)truncated=true;
 for(const candidate of candidates){
  pending();stableRoot();if(consideredFiles++>=MAX_FILES){skippedFiles++;truncated=true;continue}
  let fd;
  try{
   const file=candidate.startsWith('/src/')?candidate.slice(5):candidate;
   if(!file||file.length>400||isAbsolute(file)||file.includes('\\')||/[\x00-\x1f\x7f]/.test(file)||file.split('/').some(p=>!p||p==='.'||p==='..'))throw Error();
   const target=join(canonical,file),rel=relative(canonical,target);if(rel.startsWith('..'+sep)||isAbsolute(rel))throw Error();
   let at=canonical;for(const part of file.split('/')){at=join(at,part);if(lstatSync(at).isSymbolicLink())throw Error()}
   fd=openSync(target,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);const info=fstatSync(fd),pathInfo=lstatSync(target);
   if(!info.isFile()||info.nlink!==1||info.dev!==pathInfo.dev||info.ino!==pathInfo.ino||realpathSync(target)!==target)throw Error();
   if(info.size>MAX_BYTES||totalBytes+info.size>MAX_TOTAL){truncated=true;throw Error()}
   const buffer=Buffer.alloc(MAX_BYTES+1),length=readSync(fd,buffer,0,buffer.length,0);totalBytes+=length;
   if(length>MAX_BYTES||totalBytes>MAX_TOTAL){truncated=true;throw Error()}
   if(buffer.subarray(0,length).includes(0))throw Error();
   const source=buffer.subarray(0,length).toString('utf8');checkedFiles++;
   for(const [id,pattern,label] of checks){const match=pattern.exec(source);if(match)findings.push({rule:'harness-text.'+id,title:'有限文本提示：'+label,severity:'info',location:file+':'+(source.slice(0,match.index).split('\n').length),evidence:'仅文本匹配；注释和字符串也可能命中，未做语义确认，须人工复核',subject:null})}
  }catch{skippedFiles++}
  finally{if(fd!==undefined)closeSync(fd)}
 }
 stableRoot();return{summary:{version:1,policy:POLICY,candidateFiles:candidates.size,checkedFiles,skippedFiles,hints:findings.length,truncated},findings};
}
