import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import * as health from './web-health.mjs';

const rect=(x,y,width,height)=>({x,y,left:x,top:y,right:x+width,bottom:y+height,width,height});
function fixture({corner='bottom-right',controls=[],flipped=false}={}){
 let notify;const timers=[],events=new Map(),saved=new Map([['harness-pet-corner-v1',corner]]);
 const style=()=>({setProperty(k,v){this[k]=v},getPropertyValue(k){return this[k]??''}});
 const el=()=>({style:style(),attrs:new Map(),children:[],appendChild(e){this.children.push(e)},setAttribute(k,v){this.attrs.set(k,String(v))},getAttribute(k){return k==='style'?JSON.stringify(this.style):this.attrs.get(k)??null},removeAttribute(k){this.attrs.delete(k)},contains(){return false},querySelectorAll(){return[]},addEventListener(){}});
 const app=el(),widget=el(),popup=el(),panel=el();panel.open=false;let squash=1,transition=0,computedDimensions=true,nativeActive=true;
 widget.style.left='965px';widget.style.top='405px';widget.classList={contains:c=>c==='dshwv-left'&&flipped||c==='dshwv-dragging'&&nativeActive};
 const size=()=>Math.min(300,parseFloat(widget.style.maxWidth)||Infinity),art=()=>size()*.5945;
 widget.getBoundingClientRect=()=>rect(parseFloat(widget.style.left)+transition,parseFloat(widget.style.top),size(),size());
 const image={getBoundingClientRect(){const b=widget.getBoundingClientRect(),w=art();return rect(b.left+(flipped?0:size()-w)-(squash-1)*w/2,b.top+size()-w*squash,w*squash,w*squash)}};
 widget.querySelector=()=>image;widget.querySelectorAll=q=>q==='.dshwv-pop.dshwv-pop-open'?[popup]:[];
 popup.getBoundingClientRect=()=>{const b=widget.getBoundingClientRect(),w=size(),h=w*700/1026;return rect(b.left+(flipped?-parseFloat(popup.style.left||0):parseFloat(popup.style.left||0)),b.top+parseFloat(popup.style.top||0),w,h)};
 const document={head:{appendChild(){}},body:{},activeElement:null,getElementById:id=>id==='root'?app:id==='harness-vm-identity'?panel:null,createElement:el,querySelector:q=>q==='.dshwv-root'?widget:q==='.dshwv-img'?image:null,querySelectorAll:q=>q==='.dshwv-menu'?[]:controls.map(r=>({closest:()=>null,getBoundingClientRect:()=>r})),addEventListener:(n,f)=>events.set(n,f)};
 const getComputedStyle=e=>({visibility:'visible',display:'block',opacity:e.getAttribute?.('data-harness-occluded')==='true'?'0':'1',width:computedDimensions?(e===image?art():size())+'px':'auto',height:computedDimensions?(e===image?art():e===popup?size()*700/1026:size())+'px':'auto'});
 const context={MutationObserver:class{constructor(callback){notify=callback}observe(){}},document,window:{addEventListener:(n,f)=>events.set(n,f)},innerWidth:1280,innerHeight:720,getComputedStyle,localStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},queueMicrotask:f=>f(),setTimeout:f=>timers.push(f)};
 vm.runInNewContext('('+health.installFloatingLayout.toString()+')('+health.chooseWidgetPlacement.toString()+','+health.planPetDock.toString()+','+health.dragPetCorner.toString()+')',context);
 return{notify(records){notify(records)},timerCount(){return timers.length},nativeEnds(){nativeActive=false},panel,context,widget,popup,image,saved,events,run(){let n=0;while(timers.length&&n++<20)timers.shift()();assert.ok(n<20)},refresh(){events.get('resize')();this.run()},animate(s,t=0){squash=s;transition=t;this.refresh()},useNativeRectFallback(){computedDimensions=false;const read=image.getBoundingClientRect;image.getBoundingClientRect=()=>Object.create(read());this.refresh()}};
}

test('Native squish and root transition frames cannot feed back into dock coordinates',()=>{
 for(const corner of ['free','bottom-right'])for(const flipped of [false,true]){
  const f=fixture({flipped,corner});f.run();const position=[f.widget.style.left,f.widget.style.top];
  for(const [s,t]of [[1.12,-8],[.97,-2],[1.01,0],[1,0]]){f.animate(s,t);assert.deepEqual([f.widget.style.left,f.widget.style.top],position,'Animated paint bounds must not become new layout coordinates')}
 }
});
test('An open balance bubble moves independently of the pet and remains visible over a nearby control',()=>{
 const controls=[rect(940,400,110,40)];const f=fixture({controls});f.run();
 assert.equal(f.widget.getAttribute('data-harness-occluded'),'false');assert.equal(f.popup.getAttribute('data-harness-occluded'),'false','Opening the balance bubble must not make it transparent');
 assert.equal(f.popup.getAttribute('inert'),null);const r=f.popup.getBoundingClientRect();assert.ok(r.x>=8&&r.y>=8&&r.right<=1272&&r.bottom<=712);
 assert.ok(!controls.some(c=>r.left<c.right+4&&r.right>c.left-4&&r.top<c.bottom+4&&r.bottom>c.top-4),'Use an available gap for the popup');
});
test('A balance popup with no unoccupied gap falls back to the original visible overlay',()=>{
 const f=fixture({controls:[rect(0,0,1080,720),rect(1080,0,200,500)]});f.run();
 assert.equal(f.widget.getAttribute('data-harness-occluded'),'false');assert.equal(f.popup.getAttribute('data-harness-occluded'),'false');assert.equal(f.popup.getAttribute('inert'),null);
});
test('Top-corner balance bubbles stay inside the viewport in both native flip orientations',()=>{
 for(const flipped of [false,true]){const f=fixture({corner:'top-left',flipped});f.run();const r=f.popup.getBoundingClientRect();assert.ok(r.left>=8&&r.top>=8&&r.right<=1272&&r.bottom<=712,JSON.stringify(r));assert.equal(f.popup.getAttribute('data-harness-occluded'),'false')}
});
test('Manual drag near both edges commits a corner only after crossing the native movement threshold',()=>{
 const start={x:1088,y:528,width:180,height:180,pointerX:1178,pointerY:618};
 assert.equal(health.dragPetCorner(start,{clientX:1178,clientY:623},1280,720),'bottom-right');
 assert.equal(health.dragPetCorner(start,{clientX:1178,clientY:680},1280,720),'bottom-right');
 assert.equal(health.dragPetCorner(start,{clientX:1179,clientY:618},1280,720),null);assert.equal(health.dragPetCorner(start,{clientX:0,clientY:0},1280,720),null);
});
test('Interacting with a bubble cannot release a preset as though it were dragging the character',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')({target:{closest:q=>q==='.dshwv-root'?f.widget:null},clientX:1100,clientY:450});
 f.events.get('pointerup')({clientX:1120,clientY:450});f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
});
test('A drag crossing the native threshold and returning to its starting point still releases the preset',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')({target:{closest:q=>q==='.dshwv-img'?f.image:null},clientX:1180,clientY:620});
 f.events.get('pointermove')({clientX:1190,clientY:620});f.events.get('pointermove')({clientX:1181,clientY:620});f.events.get('pointerup')({clientX:1181,clientY:620});f.run();
 assert.equal(f.saved.get('harness-pet-corner-v1'),'free');
});
test('Cancelling a drag crossing the native threshold retains the explicit corner',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')({target:{closest:q=>q==='.dshwv-img'?f.image:null},clientX:1180,clientY:620});f.events.get('pointermove')({clientX:1190,clientY:620});
 f.events.get('pointercancel')({clientX:0,clientY:0});f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
});
test('Fallback geometry retains native DOMRect prototype properties when computed sizes are unavailable',()=>{
 const f=fixture();f.run();f.useNativeRectFallback();assert.equal(f.widget.getAttribute('data-harness-occluded'),'false');assert.equal(f.widget.getAttribute('data-harness-corner'),'bottom-right');
});

const pointerDown=f=>({target:{closest:q=>q==='.dshwv-img'?f.image:null},pointerType:'mouse',pointerId:1,button:0,buttons:1,clientX:1180,clientY:620});
test('A native drag dropped at a corner reserves space rather than being moved away by free avoidance',()=>{
 const f=fixture({corner:'free'});f.run();const image=f.image.getBoundingClientRect();
 const clientX=image.left+image.width/2,clientY=image.top+image.height/2;
 f.events.get('pointerdown')({...pointerDown(f),clientX,clientY});
 const end={pointerId:1,clientX:1270-image.width/2,clientY:710-image.height/2};
 f.events.get('pointermove')({...end,buttons:1});f.nativeEnds();f.events.get('pointerup')({...end,buttons:0});f.run();
 assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
 const final=f.image.getBoundingClientRect();assert.ok(Math.abs(final.right-1268)<.01);assert.ok(Math.abs(final.bottom-708)<.01);
 assert.ok(parseFloat(f.context.document.getElementById('root').style['--harness-pet-lane'])>0);
});
test('Re-grabbing during a press rebound uses stable artwork bounds for the next corner drop',()=>{
 const f=fixture({corner:'free'});f.run();const stable=f.image.getBoundingClientRect();
 f.animate(.88);const clientX=stable.left+stable.width/2,clientY=stable.top+stable.height/2;
 f.events.get('pointerdown')({...pointerDown(f),clientX,clientY});
 const end={pointerId:1,clientX:clientX+12-stable.left,clientY:clientY+12-stable.top};
 f.events.get('pointermove')({...end,buttons:1});f.nativeEnds();f.events.get('pointerup')({...end,buttons:0});f.run();
 assert.equal(f.saved.get('harness-pet-corner-v1'),'top-left');
 f.animate(1);const final=f.image.getBoundingClientRect();assert.ok(Math.abs(final.left-12)<.01);assert.ok(Math.abs(final.top-12)<.01);
});
test('A missed pointerup resumes layout on a released pointermove and releases a moved preset',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')(pointerDown(f));
 f.events.get('pointermove')({pointerId:1,buttons:1,clientX:1000,clientY:620});
 f.events.get('pointermove')({pointerId:1,buttons:0,clientX:1000,clientY:620});
 f.panel.open=true;f.refresh();assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');assert.equal(f.saved.get('harness-pet-corner-v1'),'free');
});
test('Only the initiating primary pointer can commit or cancel a pet gesture',()=>{
 for(const event of ['pointerup','pointercancel']){
  const f=fixture();f.run();f.events.get('pointerdown')(pointerDown(f));
  f.events.get('pointerdown')({...pointerDown(f),pointerId:2,isPrimary:false,clientX:500});
  f.events.get(event)({pointerId:2,buttons:0,clientX:500,clientY:300});
  assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
  f.events.get('pointermove')({pointerId:1,buttons:1,clientX:1000,clientY:620});f.events.get('pointerup')({pointerId:1,buttons:0,clientX:1000,clientY:620});f.run();
  assert.equal(f.saved.get('harness-pet-corner-v1'),'free');
 }
});
test('Right and middle mouse movement cannot release a corner preset',()=>{
 for(const button of [1,2]){const f=fixture();f.run();f.events.get('pointerdown')({...pointerDown(f),button});
  f.events.get('pointermove')({pointerId:1,buttons:2,clientX:1170,clientY:620});f.events.get('pointerup')({pointerId:1,button,buttons:0,clientX:1170,clientY:620});f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');}
});
test('Released hover without drag movement keeps the chosen corner',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')(pointerDown(f));f.events.get('pointermove')({pointerId:1,buttons:0,clientX:1181,clientY:620});
 f.panel.open=true;f.refresh();assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
});
test('Returning after the original plugin has ended a gesture restores layout without inventing a drag',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')(pointerDown(f));
 f.nativeEnds();f.panel.open=true;f.events.get('focus')?.();f.run();assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
});

test('A click rejected by the original hit or menu guard cannot become a host drag',()=>{
 const f=fixture();f.run();f.nativeEnds();f.events.get('pointerdown')(pointerDown(f));
 f.events.get('pointermove')({pointerId:1,buttons:1,clientX:1160,clientY:620});f.events.get('pointerup')({pointerId:1,buttons:0,clientX:1160,clientY:620});f.run();
 assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');
});

test('Native anchor replays cannot paint a docked pet at an old position while the menu resyncs',()=>{
 for(const corner of ['top-left','top-right','bottom-left','bottom-right']){
  const f=fixture({corner});f.run();f.nativeEnds();const stable=[f.widget.style.left,f.widget.style.top];
  for(const [left,top] of [['319px','193px'],['315px','190px']]){
   f.widget.style.left=left;f.widget.style.top=top;
   f.notify([{target:f.widget,attributeName:'style'}]);
   for(const [actual,want] of [f.widget.style.left,f.widget.style.top].map((v,i)=>[parseFloat(v),parseFloat(stable[i])]))assert.ok(Math.abs(actual-want)<.000001,'Reconcile before a delayed layout timer can paint the stale native anchor');
   f.notify([{target:f.widget,attributeName:'style'}]);
   assert.equal(f.timerCount(),0,'Our own correction must not schedule a feedback loop');
  }
 }
});

test('Immediate dock reconciliation leaves an accepted native drag in control',()=>{
 const f=fixture();f.run();f.events.get('pointerdown')(pointerDown(f));
 f.widget.style.left='500px';f.widget.style.top='270px';
 f.notify([{target:f.widget,attributeName:'style'}]);f.run();
 assert.equal(f.widget.style.left,'500px');assert.equal(f.widget.style.top,'270px');
 assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right','A moving gesture has not committed a new preset');
});
