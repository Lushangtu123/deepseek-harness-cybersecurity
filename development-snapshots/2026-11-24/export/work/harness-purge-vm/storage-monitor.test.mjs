import test from 'node:test';import assert from 'node:assert/strict';import * as entry from './web-entry.mjs';
const gib=1024**3;
const sample=(available=9*gib)=>({version:1,readOnly:true,automaticChanges:false,deletionAvailable:false,hostFilesystem:{totalBytes:500*gib,availableBytes:100*gib},guest:{state:'observed',filesystem:{totalBytes:100*gib,availableBytes:available,inodeTotal:1000,inodeAvailable:900}},secret:'must-not-leak'});
test('Concurrent manual refreshes each receive the shared completed snapshot',async()=>{
 let release,calls=0;const monitor=entry.createStorageMonitor({run:()=>{calls++;return new Promise(resolve=>release=resolve)}});
 const first=monitor.refresh(),second=monitor.refresh();release({stdout:JSON.stringify(sample())});const values=await Promise.all([first,second]);assert.equal(calls,1);for(const value of values)assert.equal(value?.state,'current');monitor.stop();
});
test('A sample crossing sleep or a clock jump is discarded instead of renewed at completion',async()=>{
 for(const jump of [3600000,-3600000]){
  let wall=100000,mono=0,release;const monitor=entry.createStorageMonitor({run:()=>new Promise(resolve=>release=resolve),now:()=>mono,wallNow:()=>wall});
  const pending=monitor.refresh();wall+=jump;release({stdout:JSON.stringify(sample(30*gib))});await pending;
  assert.equal(monitor.snapshot().state,'unavailable');assert.equal(monitor.snapshot().guest.state,'unavailable');monitor.stop();
 }
});
test('One capacity sampler coalesces reads, labels thresholds and stops cleanly',async()=>{
 assert.equal(typeof entry.createStorageMonitor,'function','Capacity monitor missing');let wall=100000,mono=0,calls=0,release,tick,cleared=false;
 const monitor=entry.createStorageMonitor({run:()=>{calls++;return new Promise(resolve=>release=resolve)},now:()=>mono,wallNow:()=>wall,schedule:fn=>{tick=fn;return{unref(){}}},unschedule:()=>cleared=true});
 assert.equal(monitor.snapshot().state,'not-observed');monitor.start();const pending=monitor.refresh();await tick();assert.equal(calls,1);
 release({stdout:JSON.stringify(sample())});await pending;assert.equal(monitor.snapshot().guest.filesystem.state,'warning');assert.equal(monitor.snapshot().hostFilesystem.state,'healthy');assert.ok(!JSON.stringify(monitor.snapshot()).includes('secret'));
 wall+=91000;assert.equal(monitor.snapshot().state,'stale');mono+=91000;const next=tick();assert.equal(calls,2);release({stdout:JSON.stringify(sample(30*gib))});await next;assert.equal(monitor.snapshot().guest.filesystem.state,'healthy');monitor.stop();await tick();assert.equal(calls,2);assert.equal(cleared,true);
});
test('A failed sample retains old counters only as history; next tick can recover',async()=>{
 assert.equal(typeof entry.createStorageMonitor,'function');let count=0,now=0;
 const monitor=entry.createStorageMonitor({run:async()=>{if(++count===2)throw Error('private stderr');return{stdout:JSON.stringify(sample())}},now:()=>now,wallNow:()=>now,schedule:()=>({unref(){}}),unschedule(){}});
 await monitor.refresh();now+=60000;await monitor.refresh();assert.equal(monitor.snapshot().state,'unavailable');assert.ok(!JSON.stringify(monitor.snapshot()).includes('private'));
 now+=60000;await monitor.refresh();assert.equal(monitor.snapshot().state,'current');monitor.stop();
});
test('Malformed counters fail closed and valid inode shortage triggers critical',async()=>{
 assert.equal(typeof entry.createStorageMonitor,'function');let value=sample();value.guest.filesystem.inodeAvailable=20;
 const monitor=entry.createStorageMonitor({run:async()=>({stdout:JSON.stringify(value)}),schedule:()=>({unref(){}}),unschedule(){}});await monitor.refresh();assert.equal(monitor.snapshot().guest.filesystem.state,'critical');monitor.stop();
 for(const available of [-1,NaN,'9',101*gib]){
  value=sample();value.guest.filesystem.availableBytes=available;
  const invalid=entry.createStorageMonitor({run:async()=>({stdout:JSON.stringify(value)}),schedule:()=>({unref(){}}),unschedule(){}});await invalid.refresh();assert.equal(invalid.snapshot().state,'unavailable');assert.equal(invalid.snapshot().guest.state,'unavailable');invalid.stop();
 }
});
