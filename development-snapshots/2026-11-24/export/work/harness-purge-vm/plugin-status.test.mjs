import test from 'node:test';
import assert from 'node:assert/strict';
import {createEnvironmentReader} from './web-entry.mjs';
test('Public recovery status includes scoped plugin differences without revealing unrelated paths',async()=>{
 const prefix='tools/imported-dsh-plugins-20261027T185822Z/';
 const value={mode:'improved',configDir:'/home/purge/.dsh-improved',recovery:{state:'older',groups:{plugins:{state:'older',filesChecked:1320,differentFiles:[prefix+'dsh-context/lib/index.js',prefix+'other-plugin/private.txt',prefix+'dsh-context/.env'],differentFileCount:200,differenceDetailsTruncated:true}},uncoveredFiles:[prefix+'dshmarket/package.json']}};
 const result=await createEnvironmentReader({run:async()=>({stdout:JSON.stringify(value)})})();
 assert.ok(result.recovery.groups.plugins,'Plugin group missing from public status');
 assert.equal(result.recovery.groups.plugins.filesChecked,1320);
 assert.deepEqual(result.recovery.groups.plugins.differentFiles,[prefix+'dsh-context/lib/index.js']);
 assert.deepEqual(result.recovery.uncoveredFiles,[prefix+'dshmarket/package.json']);
 assert.equal(result.recovery.differenceDetailsTruncated,true);
});
