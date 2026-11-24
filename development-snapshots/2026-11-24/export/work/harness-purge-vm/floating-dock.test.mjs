import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import * as health from './web-health.mjs';

function fixture(stored='bottom-right',denied=false){
 const timers=[],events=new Map(),saved=new Map(stored===null?[]:[['harness-pet-corner-v1',stored]]);
 const style=()=>({setProperty(k,v){this[k]=v},getPropertyValue(k){return this[k]??''}});
 const element=tag=>({tag,style:style(),children:[],attrs:new Map(),className:'',textContent:'',appendChild(child){this.children.push(child);return child},append(...children){this.children.push(...children)},setAttribute(k,v){this.attrs.set(k,String(v))},getAttribute(k){return this.attrs.get(k)??null},removeAttribute(k){this.attrs.delete(k)},contains(){return false},addEventListener(k,v){this[k]=v},querySelector(){return null},querySelectorAll(){return[]}});
 const app=element('app'),menu=element('menu'),widget=element('widget'),summary=element('summary');menu.classList={contains:()=>true};
 menu.getBoundingClientRect=()=>({left:parseFloat(menu.style.left)||900,top:parseFloat(menu.style.top)||-400,width:340,height:360});
 const panel={open:false,style:style(),querySelector:()=>summary};
 widget.style.left='900px';widget.style.top='168px';
 widget.getBoundingClientRect=()=>{const width=Math.min(288,parseFloat(widget.style.maxWidth)||Infinity),height=width,left=parseFloat(widget.style.left),top=parseFloat(widget.style.top);return{left,top,right:left+width,bottom:top+height,x:left,y:top,width,height}};
 const image={getBoundingClientRect(){const r=widget.getBoundingClientRect(),width=r.width*.5945,height=width;return{left:r.right-width,top:r.bottom-height,right:r.right,bottom:r.bottom,x:r.right-width,y:r.bottom-height,width,height}}};
 widget.querySelector=()=>image;widget.closest=()=>widget;
 const control={closest:()=>null,getBoundingClientRect:()=>({x:400,y:510,width:700-(parseFloat(app.style['--harness-pet-lane'])||0),height:90,right:1100,bottom:600})};
 const document={head:{appendChild(){}},body:{},activeElement:null,getElementById:id=>id==='root'?app:id==='harness-vm-identity'?panel:null,createElement:element,querySelector:()=>widget,querySelectorAll:q=>q==='.dshwv-menu'?[menu]:[control],addEventListener(k,v){events.set(k,v)}};
 const localStorage={getItem(k){if(denied)throw Error('denied');return saved.get(k)??null},setItem(k,v){if(denied)throw Error('denied');saved.set(k,v)}};
 vm.runInNewContext('('+health.installFloatingLayout.toString()+')('+health.chooseWidgetPlacement.toString()+','+(health.planPetDock?.toString()??'undefined')+','+(health.dragPetCorner?.toString()??'undefined')+')',{document,window:{addEventListener(k,v){events.set(k,v)}},innerWidth:1247,innerHeight:686,localStorage,getComputedStyle:()=>({visibility:'visible',display:'block',opacity:'1'}),setTimeout(fn){timers.push(fn)}});
 return{app,menu,widget,image,saved,events,removePet(){document.querySelector=()=>null;events.get('resize')()},run(){for(let n=0;timers.length&&n<20;n++)timers.shift()()},buttons(){return menu.children.flatMap(x=>[x,...x.children]).filter(x=>x.tag==='button')}};
}

test('Corner docking reserves a side lane and reaches the actual lower viewport corner',()=>{
 assert.equal(typeof health.planPetDock,'function','An explicit dock must not be sent through free-position avoidance');
 const p=health.planPetDock('bottom-right',1247,686,171.28,171.28);
 assert.equal(p.x+171.28,1247-12);assert.equal(p.y+171.28,686-12);
 assert.ok(p.lane>=171.28+24);assert.equal(p.leftLane,0);
});
test('Narrow docking fits the pet while retaining usable app width and mirrored corners',()=>{
 assert.equal(typeof health.planPetDock,'function');
 const p=health.planPetDock('top-left',425,664,106,106);
 assert.equal(p.x,12);assert.equal(p.y,12);assert.ok(p.width<=65);assert.ok(425-p.lane>=330);assert.equal(p.leftLane,p.lane);
 assert.equal(health.planPetDock('bad',425,664,100,100),null);
});
test('Manual drags select a corner or free placement without committing cancelled or small movements',()=>{
 assert.equal(typeof health.dragPetCorner,'function');
 const start={x:1062,y:285,width:171,height:171,pointerX:1165,pointerY:380};
 assert.equal(health.dragPetCorner(start,{clientX:1165,clientY:640},1247,686),'bottom-right');
 assert.equal(health.dragPetCorner(start,{clientX:1165,clientY:300},1247,686),'free');
 assert.equal(health.dragPetCorner(start,{clientX:1165,clientY:381},1247,686),null);
 assert.equal(health.dragPetCorner(start,{clientX:0,clientY:0},1247,686),null);
});
test('Actual floating installer restores a dock without letting input avoidance push it to the middle',()=>{
 const f=fixture();f.run();const r=f.image.getBoundingClientRect();
 assert.ok(parseFloat(f.app.style['--harness-pet-lane'])>190,'Reserve real app space');
 assert.ok(Math.abs(r.bottom-674)<.01);assert.ok(Math.abs(r.right-1235)<.01);
 assert.equal(f.widget.getAttribute('data-harness-occluded'),'false');
});
test('Pet menu offers all corners and free mode restores app width',()=>{
 const f=fixture(null);f.run();const buttons=f.buttons();
 assert.equal(buttons.length,5,'Four explicit corners plus free dragging');
 buttons.find(b=>b.textContent==='左上').click();f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'top-left');
 assert.ok(parseFloat(f.app.style['--harness-pet-left-lane'])>0);
 buttons.find(b=>b.textContent==='自由').click();f.run();assert.equal(f.app.style['--harness-pet-lane'],'0px');
 assert.equal(f.saved.get('harness-pet-corner-v1'),'free');
});
test('A top-corner dock keeps the original upward-opening pet menu inside the viewport',()=>{
 const f=fixture('top-left');f.run();const r=f.menu.getBoundingClientRect();
 assert.ok(r.top>=8&&r.top+r.height<=678,'Original upward menu must stay reachable');
 assert.ok(r.left>=8&&r.left+r.width<=1239);
});
test('Removing the pet releases its reserved lane',()=>{
 const f=fixture();f.run();assert.ok(parseFloat(f.app.style['--harness-pet-lane'])>0);
 f.removePet();f.run();assert.equal(f.app.style['--harness-pet-lane'],'0px');
});

test('Dropping the visible artwork near both viewport edges selects that corner',()=>{
 const start={x:500,y:250,width:160,height:160,pointerX:580,pointerY:330};
 for(const [clientX,clientY,corner] of [[92,92,'top-left'],[1156,92,'top-right'],[92,594,'bottom-left'],[1156,594,'bottom-right']]){
  assert.equal(health.dragPetCorner(start,{clientX,clientY},1247,686),corner);
 }
 assert.equal(health.dragPetCorner(start,{clientX:92,clientY:330},1247,686),'free','One edge alone must not select a corner');
 assert.equal(health.dragPetCorner(start,{clientX:700,clientY:400},1247,686),'free');
});
