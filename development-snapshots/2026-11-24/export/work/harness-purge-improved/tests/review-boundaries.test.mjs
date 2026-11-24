import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { apply as installUi } from '../package/lib/redteam/ui.js';
import { redactText } from '../package/lib/redteam/personal-evidence-redaction.mjs';

test('restart refuses before invoking original host patch readiness', async () => {
  const source=fs.readFileSync(new URL('../package/lib/index.js',import.meta.url),'utf8');
  const start=source.indexOf('function installWebServer(');
  const end=source.indexOf('\nfunction methodNotAllowed(',start);
  const routes=[]; let readiness=0;
  const host={effect:fn=>fn(),webServer:{register:spec=>{routes.push(spec);return ()=>{};}}};
  const scope={ctx:{inject:(_deps,fn)=>fn(host)},watchWebTreeReady(){},allowPluginRequest:()=>true,
    installRulesHttp(){},installSkillsHttp(){},ensureRestartReady:async()=>{readiness++;return {ok:false};},
    authenticatedWebServer:(_ctx,server)=>server,
    sendJson:(res,status,body)=>Object.assign(res,{status,body})};
  vm.runInNewContext(source.slice(start,end)+'\ninstallWebServer(ctx,{});',scope);
  const response={};
  await routes.find(x=>x.path==='/dsh-purge/restart').handler({method:'POST'},response);
  assert.equal(readiness,0);
  assert.equal(response.status,409);
});

test('raw HTTP bodies redact whole quoted secrets, including escaped quotes', () => {
  for(const raw of ['{"password":"alpha beta"}', "password='alpha beta,gamma'", '{"api_key":"alpha\\\" beta"}']) {
    const value=redactText(raw);
    assert.ok(!value.includes('alpha'),value);
    assert.ok(!value.includes('beta'),value);
    assert.ok(!value.includes('gamma'),value);
    assert.ok(value.includes('[REDACTED]'));
  }
});

function api(authenticated=true) {
  let route,mutations=0;
  const store={root:'/synthetic',openEngagement(){mutations++;return {id:'synthetic'};}};
  installUi({redteam:store,connection:{admit:()=>authenticated?{peer:{principal:{kind:'owner'}}}:{rejection:401}},__dshpEnvAdaptPreStep:true,effect:fn=>fn(),webServer:{register:spec=>{route=spec;}}});
  return {route,get mutations(){return mutations;}};
}
async function send(route,headers,remote='127.0.0.1') {
  const req={method:'POST',headers:{host:'127.0.0.1:49224','content-type':'application/json',...headers},
    socket:{remoteAddress:remote},async *[Symbol.asyncIterator](){yield Buffer.from('{"op":"openEngagement","name":"synthetic"}');},
    on(event,fn){if(event==='data')fn(Buffer.from('{"op":"openEngagement","name":"synthetic"}'));if(event==='end')fn();return this;}};
  const res={writeHead(status){this.status=status;},end(body){this.body=body;}};
  await route.handler(req,res);return res;
}
test('API rejects cross-origin, opaque and missing-origin writes even on loopback',async()=>{
  const fixture=api();
  for(const origin of ['https://outside.invalid','null',undefined,'app://harness','http://127.0.0.1:49999']) {
    const res=await send(fixture.route,{origin});
    assert.equal(res.status,403,String(origin));
  }
  assert.equal(fixture.mutations,0);
});
test('API requires JSON and valid fetch site and accepts authenticated same-origin transport',async()=>{
  const fixture=api();const origin='http://127.0.0.1:49224';
  assert.equal((await send(fixture.route,{origin,'content-type':'text/plain'})).status,415);
  assert.equal((await send(fixture.route,{origin,'sec-fetch-site':'cross-site'})).status,403);
  assert.equal(fixture.mutations,0);
  assert.equal((await send(fixture.route,{origin,'sec-fetch-site':'same-origin'},'10.0.2.2')).status,200);
  assert.equal(fixture.mutations,1);
});
test('same-origin headers do not replace a valid official owner session',async()=>{
  const fixture=api(false);
  assert.equal((await send(fixture.route,{origin:'http://127.0.0.1:49224'})).status,401);
  assert.equal(fixture.mutations,0);
});
