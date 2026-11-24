import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const target = new URL('../package/lib/personal-original.mjs', import.meta.url);
const load = async () => fs.existsSync(target) ? import(target.href) : {};
const runtime = {
  platform: 'linux', home: '/home/purge',
  env: { DSH_HOME: '/home/purge/.dsh-improved',
    DSH_BASE: '/home/purge/tools/harness-original-capabilities/node_modules/@deepseek-ai',
    DSH_PERSONAL_ORIGINAL: 'enabled' },
};

test('original capabilities default off and require the dedicated VM overlay', async () => {
  const { originalCapabilitiesEnabled } = await load();
  assert.equal(typeof originalCapabilitiesEnabled, 'function');
  assert.equal(originalCapabilitiesEnabled(runtime), true);
  for (const changed of [
    {platform: 'darwin'}, {home: '/root'},
    {env: {...runtime.env, DSH_PERSONAL_ORIGINAL: ''}},
    {env: {...runtime.env, DSH_HOME: '/home/purge/.dsh'}},
    {env: {...runtime.env, DSH_BASE: '/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai'}},
  ]) assert.equal(originalCapabilitiesEnabled({...runtime, ...changed}), false);
});

test('original composition includes all original runtime hooks only in explicit mode', async () => {
  const { installOriginalCapabilities } = await load();
  assert.equal(typeof installOriginalCapabilities, 'function');
  const calls = [], names = ['identity', 'region', 'freshPermissions', 'rewind', 'cwd', 'mnemon', 'prompts', 'retry'];
  const ops = Object.fromEntries(names.map(name => [name, () => calls.push(name)]));
  installOriginalCapabilities({}, {}, ops, {...runtime, env: {}});
  assert.deepEqual(calls, []);
  installOriginalCapabilities({}, {}, ops, runtime);
  assert.deepEqual(calls, names);
});

test('the normal settings page never mounts legacy patch or prompt editors', () => {
  const source = fs.readFileSync(new URL('../package/client.js', import.meta.url), 'utf8');
  const start = source.indexOf('function SettingsRoot('), end = source.indexOf('\n\t\tconst REWIND_CSS', start);
  const state = ['light', null]; let index = 0, mounts = 0;
  const scope = {useState: initial => [state[index++] ?? (typeof initial === 'function' ? initial() : initial), () => {}],
    useEffect() {}, readTheme: () => 'light', translate: null, PURGE_CSS: '', OriginalCapabilitiesSwitch:()=>null,
    PurgifySection: () => {mounts++;}, RulesSection: () => {mounts++;},
    OriginalCapabilitiesPanel: () => 'ORIGINAL_MODE_CONTROLS',
    h: (type, props, ...children) => typeof type === 'function' ? type(props || {}) : {type, props, children},
  };
  vm.runInNewContext(source.slice(start, end) + '\nresult=SettingsRoot({});', scope);
  assert.equal(mounts, 0);
  assert.match(JSON.stringify(scope.result), /原版能力/);
});

test('enabled mode explains original permission semantics instead of promising daily approval behavior', () => {
  const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8');
  const start=source.indexOf('function SettingsRoot('),end=source.indexOf('\n\t\tconst REWIND_CSS',start);
  let index=0;
  const state=['light',{originalCapabilities:{enabled:true},patches_applied:58,patches_total:63,patches_skipped:5}];
  const scope={readTheme:()=> 'light',useState:()=>[state[index++],()=>{}],useEffect(){},translate:null,PURGE_CSS:'',OriginalCapabilitiesSwitch:()=>null,
    RulesSection:()=>null,OriginalPromptEditor:()=>null,
    h:(type,props,...children)=>typeof type==='function'?type(props||{}):{type,props,children}};
  vm.runInNewContext(source.slice(start,end)+'\nresult=SettingsRoot({});',scope);
  const rendered=JSON.stringify(scope.result);
  assert.match(rendered,/按原版补丁运行/);
  assert.doesNotMatch(rendered,/人工审批档位仍逐次确认/);
});
