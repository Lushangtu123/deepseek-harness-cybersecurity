import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {RedteamStore} from './package/lib/redteam/store-core.js';
import {SecurityWorkbench} from './package/lib/redteam/personal-security-workbench.mjs';
const root=process.cwd(),controls=JSON.parse(fs.readFileSync(root+'/controls.json'));
const project=root+'/workspace/synthetic-project';fs.mkdirSync(project,{recursive:true,mode:0o700});
for(const [name,source] of Object.entries(controls.fixture)) {
  assert.equal(createHash('sha256').update(source).digest('hex'),controls.sourceSha256[name]);
  const target=path.join(project,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,source,{mode:0o600});
}
const store=new RedteamStore(root+'/state'),bench=new SecurityWorkbench(store,{workspaceRoot:root+'/workspace'});
try {
  const eng=store.openEngagement('native-import-namespace-20261110').id;
  assert.equal(eng,'native-import-namespace-20261110');
  const profile=bench.saveScope(eng,{requestId:'native-scope-20261110',revision:0,repoRoot:project,
    tools:['semgrep'],expiresAt:new Date(Date.now()+1200000).toISOString(),confirm:true});
  console.log(JSON.stringify({engagement:eng,profile,fixtureFiles:Object.keys(controls.fixture).length,newScannerCalls:0}));
} finally { await bench.dispose();await store.close() }
