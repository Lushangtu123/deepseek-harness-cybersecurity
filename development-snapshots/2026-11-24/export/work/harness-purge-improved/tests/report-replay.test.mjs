import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs';import os from 'node:os';import path from 'node:path'
import {buildHttpRequest,buildCurlCommand,parseTarget} from '../package/lib/redteam/report-replay.js'
import {RedteamStore} from '../package/lib/redteam/store-core.js'
test('Synthesized HTTP preserves query, one Host, IPv6 and body byte length',()=>{
  const body=' {"字":"owned"} \n'
  const raw=buildHttpRequest({url:'https://[::1]:8443/check?mode=owned#fragment',method:'POST',data:body})
  assert.match(raw,/^POST \/check\?mode=owned HTTP\/1.1\r\n/)
  assert.match(raw,/\r\nHost: \[::1\]:8443\r\n/);assert.equal((raw.match(/\r\nHost:/gi)||[]).length,1)
  assert.match(raw,new RegExp('Content-Length: '+Buffer.byteLength(body)));assert.ok(raw.endsWith('\r\n\r\n'+body));assert.doesNotMatch(raw,/#fragment/)
  assert.equal(parseTarget('https://example.invalid?x=1#f').path,'/?x=1')
  assert.equal((buildHttpRequest({url:'https://example.invalid/a',headers:['Host: virtual.invalid']}).match(/Host:/g)||[]).length,1)
})
test('Generated curl keeps headers and literal shell arguments, raw curl stays unchanged',()=>{
  const raw="curl --data @owned-file 'https://example.invalid/a?x=1'"
  assert.equal(buildCurlCommand({tool:raw}),raw)
  const cmd=buildCurlCommand({url:"https://example.invalid/a?x=o'ne#frag",method:'GET',headers:["X-Owned: o'ne",'Content-Type: application/json'],cookie:"sid=o'ne",data:' \nowned\n '})
  assert.match(cmd,/-X GET/);assert.match(cmd,/-H 'Content-Type: application\/json'/);assert.match(cmd,/--data-(raw|binary)/)
  assert.ok(cmd.includes("'\\''"));assert.doesNotMatch(cmd,/#frag/);assert.match(cmd,/\?x=/)
})
test('Synthesized leading-at body is literal and never becomes a local file read',()=>{
  const cmd=buildCurlCommand({url:'https://example.invalid/',method:'POST',data:'@owned-payload'})
  assert.match(cmd,/--data-raw '@owned-payload'/)
})
test('Real report preserves HTTPS JSON request headers and exact captured body',t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'replay-report-')),s=new RedteamStore(root);t.after(()=>{s.close();fs.rmSync(root,{recursive:true,force:true})})
  const id=s.openEngagement('owned',[],{bindCurrent:false}).id,body=' {"owned":true}\r\n ```\n '
  const v=s.addVuln(id,{title:'owned',severity:'high',status:'confirmed',target:'https://example.invalid:8443/a?x=1'})
  s.addHttpEvidence(id,{vuln_id:v.id,url:'https://example.invalid:8443/a?x=1',method:'POST',request:'POST /a?x=1 HTTP/1.1\r\nHost: example.invalid:8443\r\nContent-Type: application/json\r\nAccept: application/json\r\n\r\n'+body})
  s.addScoreHit(id,{code:'web-app',vuln_id:v.id,target:'https://example.invalid:8443/a?x=1',evidence:'owned'})
  const report=s.scoreReport(id),r=report.items[0];assert.match(r.replay_cmd,/https:\/\/example.invalid:8443\/a\?x=1/)
  assert.match(r.replay_cmd,/-H 'Content-Type: application\/json'/);assert.match(r.replay_cmd,/-H 'Accept: application\/json'/)
  assert.ok(r.replay_cmd.includes("'"+body+"'"));assert.ok(r.replay_http.endsWith(body))
  assert.ok(report.markdown.includes(r.replay_cmd));assert.ok(report.markdown.includes(r.replay_http))
})
for(const variant of ['long-body','chunked'])test('Captured '+variant+' never becomes a false equivalent curl',t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'replay-framing-')),s=new RedteamStore(root);t.after(()=>{s.close();fs.rmSync(root,{recursive:true,force:true})})
  const id=s.openEngagement('owned',[],{bindCurrent:false}).id,url='https://example.invalid/a'
  const v=s.addVuln(id,{title:'owned',severity:'high',status:'confirmed',target:url})
  const body=variant==='long-body'?'x'.repeat(21000)+'OWNED_TAIL':'5\r\nowned\r\n0\r\n\r\n'
  const request='POST /a HTTP/1.1\r\nHost: example.invalid\r\n'+(variant==='chunked'?'Transfer-Encoding: chunked\r\n':'Content-Type: text/plain\r\n')+'\r\n'+body
  s.addHttpEvidence(id,{vuln_id:v.id,url,method:'POST',request});s.addScoreHit(id,{code:'web-app',vuln_id:v.id,target:url,evidence:'owned'})
  const r=s.scoreReport(id),item=r.items[0]
  assert.equal(item.replay_http,request)
  if(variant==='long-body'){assert.ok(item.replay_cmd.includes('OWNED_TAIL'));assert.doesNotMatch(item.replay_cmd,/truncated; see/)}
  else{assert.notEqual(item.replay_cmd_kind,'synthesized');assert.ok(item.replay_conversion_note);assert.ok(r.markdown.includes(item.replay_conversion_note))}
})
