import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('personal settings presents consent boundaries without mounting original patch or injection editors',()=>{
 const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
 const start=source.indexOf('function SettingsRoot(');
 const end=source.indexOf('\n\t\tconst REWIND_CSS',start);
 let legacyMounts=0;
 const scope={useState:initial=>[typeof initial==='function'?initial():initial,()=>{}],
  useEffect(){},readTheme:()=> 'light',translate:null,PURGE_CSS:'',OriginalCapabilitiesSwitch:()=>null,
  PurgifySection:()=>{legacyMounts++;return 'LEGACY_HOST_PATCH_CONTROLS';},
  RulesSection:()=>{legacyMounts++;return 'LEGACY_INJECTION_CONTROLS';},
  h:(type,props,...children)=>typeof type==='function'?type(props||{}):({type,props,children})};
 vm.runInNewContext(source.slice(start,end)+'\nresult=SettingsRoot({});',scope);
 const rendered=JSON.stringify(scope.result);
 assert.equal(legacyMounts,0,'Legacy controls must not be mounted in the improved profile');
 assert.match(rendered,/人工审批/);
 assert.match(rendered,/完全访问/);
 assert.match(rendered,/原版/);
 assert.doesNotMatch(rendered,/LEGACY_/);
});
