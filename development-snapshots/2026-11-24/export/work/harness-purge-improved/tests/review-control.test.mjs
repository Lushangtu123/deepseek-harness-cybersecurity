import test from 'node:test'
import assert from 'node:assert/strict'
import {runReviewParser} from '../package/lib/redteam/personal-review-control.mjs'
test('a monotonic parser deadline stops and reaps an owned synthetic child',async()=>{
 const start=performance.now()
 await assert.rejects(()=>runReviewParser('/usr/bin/python3',['-I','-S','-B','-c','import time;time.sleep(10)'],'',{deadline:start+100}),e=>e.code==='REVIEW_DEADLINE')
 assert.ok(performance.now()-start<2500)
})
test('bounded parser output fails explicitly and nonzero syntax-check status remains available',async()=>{
 await assert.rejects(()=>runReviewParser('/usr/bin/python3',['-I','-S','-B','-c','print("x"*10000)'],'',{maxBuffer:100}),e=>e.code==='REVIEW_PARSE_LIMIT')
 const result=await runReviewParser(process.execPath,['--check','--input-type=module'],'const = ;')
 assert.equal(result.code,1);assert.match(result.stderr,/SyntaxError/)
})
