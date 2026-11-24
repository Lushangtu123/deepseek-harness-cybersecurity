import {homedir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {createRuntimeInspector} from '../lib/redteam/personal-security-runtime.mjs';
export function preflight({maintenanceValidation=false}={}){
 if(process.platform!=='linux'||homedir()!=='/home/purge')return{ok:false,readOnly:true,automaticChanges:false,error:'运行资源预检只在专用VM中执行',tools:{}};
 const tools=createRuntimeInspector().read({force:true,maintenanceValidation});
 return{ok:Object.values(tools).every(row=>row.ready),readOnly:true,automaticChanges:false,scope:'local pinned images, rules and database identity; no scanner execution, model call, network download or GitHub latest check',tools};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 const result=preflight({maintenanceValidation:process.argv.slice(2).length===1&&process.argv[2]==='--validating-update'});console.log(JSON.stringify(result,null,2));process.exitCode=result.ok?0:1;
}
