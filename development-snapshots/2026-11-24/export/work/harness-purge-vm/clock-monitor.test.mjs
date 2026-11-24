import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';
import * as entry from './web-entry.mjs';
test('Background calibration survives timer gaps and never overlaps or runs after disposal',async()=>{
 assert.equal(typeof entry.createClockMonitor,'function','automatic clock monitor is missing');
 let tick,cleared=false,runs=0,release;const stop=entry.createClockMonitor({run:()=>{runs++;return new Promise(resolve=>{release=resolve})},schedule:callback=>{tick=callback;return{unref(){}}},unschedule:()=>{cleared=true}});
 const first=tick();await tick();assert.equal(runs,1);release({stdout:'{"state":"current","adjusted":false}'});await first;
 await Promise.resolve();const resumed=tick();assert.equal(runs,2);release({stdout:'{"state":"adjusted","adjusted":true}'});await resumed;
 stop();await tick();assert.equal(runs,2);assert.equal(cleared,true);
});
test('Monitor failures are contained so a later timer can try again without exposing raw errors',async()=>{
 assert.equal(typeof entry.createClockMonitor,'function');let tick,runs=0;const events=[];
 const stop=entry.createClockMonitor({run:async()=>{runs++;if(runs===1)throw Error('secret raw stderr');return{stdout:'{"state":"skipped","reason":"stopped"}'}},schedule:cb=>{tick=cb;return{unref(){}}},unschedule(){},observe:value=>events.push(value)});
 await tick();await tick();stop();assert.equal(runs,2);assert.equal(events[0].state,'unavailable');assert.equal(events[1].state,'skipped');assert.ok(!JSON.stringify(events).includes('secret'));
});
