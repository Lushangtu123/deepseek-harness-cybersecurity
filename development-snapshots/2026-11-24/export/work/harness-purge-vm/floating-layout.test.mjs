import test from 'node:test';
import assert from 'node:assert/strict';
import * as health from './web-health.mjs';
const rect=(x,y,w,h)=>({x,y,width:w,height:h});
test('A widget covering a settings switch moves to an unoccupied edge',()=>{
 assert.equal(typeof health.chooseWidgetPlacement,'function','Missing floating occlusion guard');
 const result=health.chooseWidgetPlacement(rect(1090,470,180,180),[rect(1180,570,36,20)],1280,720);
 assert.ok(result);assert.ok(result.x+180<=1280&&result.y+180<=656);
 assert.ok(!(result.x<1216&&result.x+180>1180&&result.y<590&&result.y+180>570));
});
test('When every candidate is obstructed, the widget yields instead of covering controls',()=>{
 assert.equal(typeof health.chooseWidgetPlacement,'function');
 assert.equal(health.chooseWidgetPlacement(rect(10,10,180,180),[rect(0,0,425,664)],425,664),null);
});
test('An already clear widget is stable and a narrow viewport stays within the page',()=>{
 assert.equal(typeof health.chooseWidgetPlacement,'function');
 assert.deepEqual(health.chooseWidgetPlacement(rect(240,200,160,160),[],425,664),{x:240,y:200});
 assert.equal(health.chooseWidgetPlacement(rect(0,0,500,500),[],425,664),null);
});
test('Chat content can use a free vertical gap between header and composer',()=>{
 const image=rect(230,510,180,150),controls=[rect(0,0,425,96),rect(0,260,425,350),rect(0,0,65,600)];
 const chosen=health.chooseWidgetPlacement(image,controls,425,664);assert.ok(chosen,'A free middle gap must not hide the pet');assert.ok(chosen.x>=69&&chosen.y>=100&&chosen.y+150<=256)
});
test('A vertical drag close to one control moves the pet minimally rather than snapping to the bottom',()=>{
 const image=rect(1088,250,180,180),controls=[rect(1180,350,36,20)];
 const chosen=health.chooseWidgetPlacement(image,controls,1280,720);assert.ok(chosen);assert.ok(Math.abs(chosen.y-image.y)<100,'Avoid a distant bottom/top preset when a nearby gap is free');assert.ok(Math.hypot(chosen.x-image.x,chosen.y-image.y)<100)
});
test('Gap selection agrees with a bounded independent pixel-grid oracle',()=>{
 let seed=7391;const next=n=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed%n};
 for(let sample=0;sample<60;sample++){
  const width=125,height=160,w=15+next(12),h=15+next(12),image=rect(12+next(80),12+next(65),w,h),controls=Array.from({length:5},()=>rect(next(125),next(100),5+next(45),5+next(40)));
  let nearest=Infinity;
  for(let y=12;y+h<=height-64;y++)for(let x=12;x+w<=width-12;x++)if(!controls.some(r=>x<r.x+r.width+4&&x+w>r.x-4&&y<r.y+r.height+4&&y+h>r.y-4))nearest=Math.min(nearest,(x-image.x)**2+(y-image.y)**2);
  const result=health.chooseWidgetPlacement(image,controls,width,height);
  if(nearest===Infinity)assert.equal(result,null);else{assert.ok(result);assert.equal((result.x-image.x)**2+(result.y-image.y)**2,nearest);assert.ok(!controls.some(r=>result.x<r.x+r.width+4&&result.x+w>r.x-4&&result.y<r.y+r.height+4&&result.y+h>r.y-4))}
 }
});
