import {createHash} from 'node:crypto';
import {mkdirSync,readdirSync,lstatSync,realpathSync,openSync,closeSync,readSync,fstatSync,writeFileSync,constants} from 'node:fs';
import {join,dirname} from 'node:path';
import {sanitizePythonSource} from './personal-review-python.mjs';
import {redactText,SECRET_KEY} from './personal-evidence-redaction.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');
const extensions=/\.(?:py|js|mjs|cjs|ts|tsx|jsx|java|go|rs|c|h|cpp|hpp|cs|kt|swift|rb|php|scala|sh|sql|html|css|vue|svelte|md|json|yaml|yml|toml|txt|lock)$/i;
const secretName=/(?:^|\/)(?:credentials?|secrets?|id_rsa|id_dsa|id_ecdsa|id_ed25519|known_hosts)(?:[._-]|$)|\.(?:pem|key|p8|p12|pfx|jks|keystore|env)$/i;
export function safeSnapshotName(name){return typeof name==='string'&&name.length<=400&&!/[\\\x00-\x1f]/.test(name)&&name.split('/').every(part=>part&&!part.startsWith('.')&&!['node_modules','vendor','__pycache__','dist','build'].includes(part))&&extensions.test(name)&&!secretName.test(name)}
function gitState(root){
 const unavailable={head:null,dirty:null,statusHash:null};
 try{if(!lstatSync(join(root,'.git')).isDirectory()||realpathSync(join(root,'.git'))!==join(root,'.git'))return unavailable}catch{return unavailable}
 // No Git subprocess: status can invoke fsmonitor and clean/process filters.
 try{
  const raw=readReviewFile(join(root,'.git/HEAD')).toString('utf8').trim();let head=raw;
  if(raw.startsWith('ref: ')){
   const ref=raw.slice(5);if(!/^refs\/[A-Za-z0-9_./-]{1,300}$/.test(ref)||ref.split('/').some(p=>!p||p==='.'||p==='..'))return unavailable;
   try{head=readReviewFile(join(root,'.git',ref)).toString('utf8').trim()}
   catch{const lines=readReviewFile(join(root,'.git/packed-refs')).toString('utf8').split('\n');head=lines.find(line=>line.endsWith(' '+ref))?.split(' ')[0]}
  }
  return /^[a-f0-9]{40,64}$/.test(head??'')?{head,dirty:null,statusHash:null}:unavailable;
 }catch{return unavailable}
}
export function readReviewFile(file,maxBytes=1048576){
 if(realpathSync(file)!==file)throw Error('项目路径发生变化');let fd;
 try{fd=openSync(file,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);const st=fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.size>maxBytes)throw Error('不是有界普通文件');const buffer=Buffer.alloc(st.size+1);let used=0;while(used<buffer.length){const count=readSync(fd,buffer,used,buffer.length-used,used);if(!count)break;used+=count}const raw=buffer.subarray(0,used),after=fstatSync(fd);if(raw.length!==st.size||after.mtimeMs!==st.mtimeMs||after.ctimeMs!==st.ctimeMs||lstatSync(file).ino!==st.ino||realpathSync(file)!==file)throw Error('项目文件读取期间变化');return raw}finally{if(fd!==undefined)closeSync(fd)}
}
function uniqueJSONKeys(text,sanitize){
 let unsafeNumbers=false;const stack=[];for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){let end=i+1;for(;end<text.length;end++){if(text[end]==='\\'){end++;continue}if(text[end]==='"')break}const top=stack.at(-1);if(top?.keys&&top.key){const key=JSON.parse(text.slice(i,end+1));if(top.keys.has(key))throw Error('JSON包含重复键，不能脱敏复制');top.keys.add(key);top.key=false}i=end}else if(c==='{')stack.push({keys:new Set(),key:true});else if(c==='[')stack.push({});else if(c==='}'||c===']')stack.pop();else if(c===','&&stack.at(-1)?.keys)stack.at(-1).key=true;else if(c==='-'||c>='0'&&c<='9'||c==='t'||c==='f'||c==='n'){let end=i+1;while(end<text.length&&!/[\s,\]\}]/.test(text[end]))end++;const raw=text.slice(i,end);if(String(sanitize(raw))!==raw)throw Error('JSON标量包含需脱敏值，不能安全复制');const value=JSON.parse(raw);if(typeof value==='number'&&(!Number.isFinite(value)||Number.isInteger(value)&&!Number.isSafeInteger(value)))unsafeNumbers=true;i=end-1}}return unsafeNumbers;
}
export function sanitizeReviewText(text,name,sanitize=redactText,sanitizeKnown=sanitize===redactText?String:sanitize){
 if(/\.py$/i.test(name))return sanitizePythonSource(text,sanitize,sanitizeKnown);
 if(!/\.(?:json|map)$/i.test(name))return String(sanitize(text));
 let value;try{value=JSON.parse(text)}catch{return String(sanitize(text))}const unsafeNumbers=uniqueJSONKeys(text,sanitize);
 const visit=v=>{if(typeof v==='string')return String(sanitize(v));if(v===null||typeof v!=='object'){const raw=JSON.stringify(v);if(String(sanitize(raw))!==raw)throw Error('JSON标量包含需脱敏值，不能安全复制');return v}if(Array.isArray(v))return v.map(visit);const out=Object.create(null);for(const [key,item] of Object.entries(v)){const safe=String(sanitize(key));if(Object.hasOwn(out,safe))throw Error('JSON脱敏后键名冲突');out[safe]=SECRET_KEY.test(key)?'[REDACTED]':visit(item)}return out};
 const safe=visit(value);if(JSON.stringify(value)===JSON.stringify(safe))return text;if(unsafeNumbers)throw Error('JSON数字超出安全精度，不能脱敏复制');return JSON.stringify(safe,null,2)+'\n';
}
export function createReviewSnapshot(profile,target,{sanitize=redactText,sanitizeKnown=sanitize===redactText?String:sanitize}={}){
 if(!profile||Date.parse(profile.expiresAt)<=Date.now()||realpathSync(profile.repoRoot)!==profile.repoRoot||!lstatSync(profile.repoRoot).isDirectory())throw Error('有效项目范围未确认');
 const root=profile.repoRoot,before=lstatSync(root),git=gitState(root),files=[],excluded={total:0,items:[],truncated:false};let bytes=0,seen=0,redactedFiles=0;
 mkdirSync(target,{mode:0o700});const sourceRoot=join(target,'source');mkdirSync(sourceRoot,{mode:0o700});
 const skip=(name,reason)=>{excluded.total++;if(excluded.items.length<20)excluded.items.push({path:name,reason});else excluded.truncated=true};
 const visit=(dir,prefix='',depth=0)=>{
  if(depth>20)throw Error('项目目录深度超出上限');
  for(const entry of readdirSync(dir,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){
   if(++seen>10000)throw Error('项目目录超过10000项上限');const name=prefix+entry.name,file=join(dir,entry.name),st=lstatSync(file);
   if(entry.name.startsWith('.')||['node_modules','vendor','__pycache__','dist','build'].includes(entry.name)){skip(name,'excluded-directory-or-hidden-path');continue}
   if(st.isDirectory()){if(realpathSync(file)!==file)throw Error('项目目录已变化');visit(file,name+'/',depth+1);continue}
   if(!safeSnapshotName(name)||!st.isFile()||st.nlink!==1||st.size>1048576){skip(name,'unsupported-or-nonordinary-file');continue}
   let raw,text;try{raw=readReviewFile(file);if(raw.includes(0))throw Error();text=new TextDecoder('utf-8',{fatal:true}).decode(raw)}catch{skip(name,'unreadable-or-changing-file');continue}
   if(/-----BEGIN [^\r\n]{0,48}PRIVATE KEY|AWS_SECRET_ACCESS_KEY\s*[:=]/i.test(text)){skip(name,'credential-material');continue}
   const safe=sanitizeReviewText(text,name,sanitize,sanitizeKnown),content=Buffer.from(safe);if(content.length>1048576){skip(name,'redacted-file-exceeds-1MiB');continue}bytes+=content.length;if(bytes>8388608||files.length>=1000)throw Error('项目副本超过1000文件或8MiB上限');
   const destination=join(sourceRoot,name);mkdirSync(dirname(destination),{recursive:true,mode:0o700});writeFileSync(destination,content,{flag:'wx',mode:0o400});const redacted=!raw.equals(content);if(redacted)redactedFiles++;
   files.push({path:name,sha256:hash(content),originalSha256:hash(raw),bytes:content.length,redacted});
  }
 };
 visit(root);const after=lstatSync(root);if(after.ino!==before.ino||after.dev!==before.dev||realpathSync(root)!==root||JSON.stringify(gitState(root))!==JSON.stringify(git))throw Error('项目在固定副本期间变化，请重试新请求');
 if(!files.length)throw Error('项目没有可交接的可见源码文件');
 // Recheck all admitted source bytes, including modifications that do not affect git status.
 for(const file of files)if(hash(readReviewFile(join(root,file.path)))!==file.originalSha256)throw Error('项目文件在固定副本期间变化');
 const id=hash(JSON.stringify({version:1,scopeRevision:profile.revision,git,files}));
 const result={version:1,id,scopeRevision:profile.revision,git,files,bytes,redactedFiles,excluded,coverageComplete:false,sourceRoot,notice:'仅固定列明的可见文本文件；隐藏目录、构建产物、二进制和敏感材料未覆盖。脱敏可能改变语法；不执行项目代码。'};
 writeFileSync(join(target,'manifest.json'),JSON.stringify(result),{flag:'wx',mode:0o400});return result;
}
export function safeRuntimeAssetName(name){return typeof name==='string'&&name.length<=400&&!/[\\\x00-\x1f]/.test(name)&&name.split('/').every(p=>p&&!p.startsWith('.')&&p!=='..')&&!secretName.test(name)&&(name==='website/static/favicon.svg'||name.startsWith('website/static/vendor/'))&&/\.(?:m?js|cjs|json|css|html|txt|md|svg|wasm|gz|png|jpe?g|ico|woff2?|ttf|map)$/i.test(name)}
export function verifyReviewSnapshot(snapshot,{runtimeAssets=false}={}){
 if(!snapshot||realpathSync(snapshot.sourceRoot)!==snapshot.sourceRoot)throw Error('项目副本路径已变化');
 const assets=runtimeAssets?snapshot.runtimeAssets??[]:[];if(!Array.isArray(assets)||assets.length>500||assets.some(f=>!safeRuntimeAssetName(f.path)||!Number.isSafeInteger(f.bytes)||f.bytes<0||f.bytes>8388608)||assets.reduce((a,f)=>a+f.bytes,0)>33554432)throw Error('运行资源清单无效');const all=[...snapshot.files,...assets],expected=new Set(all.map(f=>f.path)),actual=[];if(expected.size!==all.length)throw Error('项目副本重复路径');
 const visit=(dir,prefix='',depth=0)=>{if(depth>20)throw Error('项目副本目录已变化');for(const entry of readdirSync(dir,{withFileTypes:true})){const name=prefix+entry.name,file=join(dir,entry.name);if(realpathSync(file)!==file)throw Error('项目副本路径已变化');if(entry.isDirectory()){if(!all.some(f=>f.path.startsWith(name+'/')))throw Error('项目副本目录集合不匹配');visit(file,name+'/',depth+1)}else{if(!entry.isFile()||!expected.has(name))throw Error('项目副本文件集合不匹配');actual.push(name)}}};
 visit(snapshot.sourceRoot);if(actual.length!==all.length)throw Error('项目副本文件集合不匹配');
 for(const file of all)if(!(safeSnapshotName(file.path)||runtimeAssets&&safeRuntimeAssetName(file.path))||hash(readReviewFile(join(snapshot.sourceRoot,file.path),assets.includes(file)?8388608:1048576))!==file.sha256)throw Error('项目副本内容不匹配或已变化');
 return true;
}
