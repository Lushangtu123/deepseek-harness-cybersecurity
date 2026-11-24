import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import * as health from './web-health.mjs';

function fixture(){
 const timers=[],events=new Map(),saved=new Map([['harness-pet-corner-v1','bottom-right']]);
 const style=()=>({setProperty(k,v){this[k]=v},getPropertyValue(k){return this[k]??''}});
 const el=tag=>({tag,style:style(),attrs:new Map(),children:[],parentElement:null,textContent:'',appendChild(c){c.parentElement=this;this.children.push(c);return c},insertBefore(c,b){c.parentElement=this;const i=this.children.indexOf(b);this.children.splice(i<0?this.children.length:i,0,c);return c},remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(c=>c!==this);this.parentElement=null},setAttribute(k,v){this.attrs.set(k,String(v))},getAttribute(k){return this.attrs.get(k)??null},removeAttribute(k){this.attrs.delete(k)},contains(c){return this===c||this.children.some(e=>e.contains?.(c))},addEventListener(k,v){this[k]=v},querySelector(q){return this.querySelectorAll(q)[0]??null},querySelectorAll(q){return this.children.flatMap(c=>[...(q==='button'&&c.tag==='button'||q==='span'&&c.tag==='span'||q==='[role="status"]'&&c.getAttribute('role')==='status'||q==='.harness-pet-dock'&&c.className==='harness-pet-dock'?[c]:[]),...c.querySelectorAll(q)])}});
 const app=el('root'),detail=el('detail'),sections=el('sections'),rows=el('section'),widget=el('widget'),menu=el('menu'),panel=el('details');app.appendChild(detail);detail.appendChild(sections);sections.appendChild(rows);detail.querySelector=q=>q==='[data-plugin-rows]'?rows:detail.querySelectorAll(q)[0]??null;
 panel.open=false;menu.classList={contains:()=>false};menu.getBoundingClientRect=()=>({left:0,top:0,width:200,height:200});
 widget.style.left='900px';widget.style.top='168px';
 const rect=(x,y,w,h)=>({left:x,top:y,right:x+w,bottom:y+h,x,y,width:w,height:h});
 widget.getBoundingClientRect=()=>{const w=Math.min(288,parseFloat(widget.style.maxWidth)||Infinity);return rect(parseFloat(widget.style.left),parseFloat(widget.style.top),w,w)};
 const image={getBoundingClientRect(){const r=widget.getBoundingClientRect(),w=r.width*.5945;return rect(r.right-w,r.bottom-w,w,w)}};
 widget.querySelector=()=>image;widget.querySelectorAll=()=>[];
 let available=true,detailVisible=true,pluginEnabled=true,componentEnabled=true;
 const controls=[{closest:()=>null,getBoundingClientRect:()=>rect(1180,650,45,24)}];
 const head=el('head');
 const document={head,body:{},activeElement:null,getElementById(id){if(id==='root')return app;if(id==='harness-vm-identity')return panel;return head.children.find(x=>x.id===id)||detail.children.find(x=>x.id===id)||null},createElement:el,querySelector(q){if(q==='.dshwv-root')return available?widget:null;if(q==='.dshwv-img')return available?image:null;if(q==='[data-plugin-detail="dsh-whale-widget"]')return detailVisible?detail:null;if(q==='[role="switch"][aria-label="Enable dsh-whale-widget"]')return{getAttribute:()=>String(pluginEnabled)};if(q==='[role="switch"][aria-label="Enable component dsh-whale-widget"]')return{getAttribute:()=>String(componentEnabled)};return null},querySelectorAll:q=>q==='.dshwv-menu'?[menu]:controls,addEventListener(k,v){events.set(k,v)}};
 const context={document,window:{addEventListener(k,v){events.set(k,v)}},innerWidth:1247,innerHeight:686,getComputedStyle:()=>({visibility:'visible',display:'block',opacity:'1'}),localStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},setTimeout(fn){timers.push(fn)}};
 vm.runInNewContext('('+health.installFloatingLayout.toString()+')('+health.chooseWidgetPlacement.toString()+','+health.planPetDock.toString()+','+health.dragPetCorner.toString()+','+(health.installPluginPetPanel?.toString()??'undefined')+')',context);
 return{document,widget,menu,detail,saved,panel,app,run(){let n=0;while(timers.length&&n++<20)timers.shift()();assert.ok(n<20)},refresh(){events.get('resize')();this.run()},button(text){return detail.querySelectorAll('button').find(b=>b.textContent===text)},status(){return detail.querySelector('[role="status"]')?.textContent},setAvailable(v){available=v;this.refresh()},setDetail(v){detailVisible=v;this.refresh()},zeroSize(){image.getBoundingClientRect=()=>rect(0,0,0,0);this.refresh()},setEnabled(plugin,component=plugin){pluginEnabled=plugin;componentEnabled=component;this.refresh()}};
}

test('An occluded pet has a recovery control outside its inert menu and Show restores a safe free position',()=>{
 const f=fixture();f.run();assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');
 const show=f.button('显示桌宠');assert.ok(show,'Recovery must be reachable on the plugin page while pet/menu are hidden');assert.equal(f.widget.contains(show),false);assert.equal(show.disabled,false);
 show.click();f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'free');assert.equal(f.widget.getAttribute('data-harness-occluded'),'false');assert.match(f.status(),/已显示/);
});
test('Reset keeps collision protection and reports hidden status instead of claiming success',()=>{
 const f=fixture();f.run();const reset=f.button('重置位置');assert.ok(reset);reset.click();f.run();assert.equal(f.saved.get('harness-pet-corner-v1'),'bottom-right');assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');assert.match(f.status(),/暂时隐藏/);
});
test('A disabled or absent pet is explained without enabling plugins or offering a false success',()=>{
 const f=fixture();f.run();f.setAvailable(false);assert.ok(f.button('显示桌宠'));assert.equal(f.button('显示桌宠').disabled,true);assert.equal(f.button('重置位置').disabled,true);assert.match(f.status(),/未运行/);
});
test('The recovery panel mounts once and leaves with the plugin detail',()=>{
 const f=fixture();f.run();f.refresh();assert.equal(f.detail.querySelectorAll('button').length,2);f.setDetail(false);assert.equal(f.detail.querySelectorAll('button').length,0);f.setDetail(true);assert.equal(f.detail.querySelectorAll('button').length,2);
});
test('Artwork losing its rendered size cannot leave an external success status behind',()=>{
 const f=fixture();f.run();f.button('显示桌宠').click();f.run();assert.match(f.status(),/已显示/);f.zeroSize();assert.doesNotMatch(f.status(),/已显示/);assert.match(f.status(),/暂时隐藏/);assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');
});
test('Turning the plugin or its component off hides an orphaned widget and disables recovery',()=>{
 const f=fixture();f.run();f.button('显示桌宠').click();f.run();assert.match(f.status(),/已显示/);
 f.setEnabled(false);assert.match(f.status(),/未运行/);assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');assert.equal(f.button('显示桌宠').disabled,true);assert.equal(f.app.style['--harness-pet-lane'],'0px');
 f.setEnabled(true);assert.match(f.status(),/已显示/);assert.equal(f.button('显示桌宠').disabled,false);
 f.setEnabled(true,false);assert.match(f.status(),/未运行/);assert.equal(f.widget.getAttribute('data-harness-occluded'),'true');
});
