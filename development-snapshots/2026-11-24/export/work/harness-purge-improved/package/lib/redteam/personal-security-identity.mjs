import {createHash} from 'node:crypto';
const fields={name:240,version:240,path:800,purl:1200,key:64,family:64};
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const text=(value,max)=>typeof value==='string'&&value.length<=max&&!/[\x00-\x1f]/.test(value);
export function validSubject(value){return value===null||(object(value)&&value.kind==='package'&&Object.keys(value).every(key=>key==='kind'||Object.hasOwn(fields,key))&&Object.entries(fields).every(([key,max])=>text(value[key],max))&&!!value.name&&/^[a-f0-9]{64}$/.test(value.key)&&/^[a-f0-9]{64}$/.test(value.family))}
export function normalizeSubject(value){if(value===undefined)return null;if(!validSubject(value))throw Error('依赖包身份结构无效');return value===null?null:{kind:'package',...Object.fromEntries(Object.keys(fields).map(key=>[key,value[key]]))}}
export function packageSubject(row,clean){
 const raw=value=>{if(value===undefined||value===null)return'';if(!text(value,8192))throw Error('Trivy包身份字段无效');return value};
 if(row.PkgIdentifier!==undefined&&!object(row.PkgIdentifier))throw Error('Trivy包标识结构无效');
 const name=raw(row.PkgName),version=raw(row.InstalledVersion),path=raw(row.PkgPath),pkgId=raw(row.PkgID),purl=raw(row.PkgIdentifier?.PURL);
 if(!name.trim())throw Error('Trivy漏洞缺少包名，不能确认依赖身份');
 return normalizeSubject({kind:'package',name:clean(name,240),version:clean(version,240),path:clean(path,800),purl:clean(purl,1200),key:hash([name,version,path,pkgId,purl]),family:hash([name,path])});
}
export function decorateFinding(db,row){
 const stored=db.prepare('SELECT data FROM security_finding_subject WHERE finding_id=?').get(row.id);
 if(!stored)return{...row,subject:null,identityVersion:0};
 if(typeof stored.data!=='string'||Buffer.byteLength(stored.data)>16384)throw Error('依赖包身份记录无效');
 return{...row,subject:normalizeSubject(JSON.parse(stored.data)),identityVersion:1};
}
export const subjectKey=value=>normalizeSubject(value)?.key||'';
export const subjectLabel=value=>{const subject=normalizeSubject(value);return subject?subject.name+'@'+(subject.version||'版本未记录')+(subject.path?' · '+subject.path:''):''};
export const literalSecurityText=value=>String(value).replace(/[\r\n\t]+/g,' ').replace(/\\/g,'\\\\').replace(/([`*_\[\]#|])/g,'\\$1').replace(/</g,'&lt;').replace(/>/g,'&gt;');
