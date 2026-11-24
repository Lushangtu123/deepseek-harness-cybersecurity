import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { installFloatingLayout } from './web-health.mjs';

function fixture(initial = {}) {
 const attrs=new Map(Object.entries(initial)),timers=[],events=new Map();
 const summary={focus(){document.activeElement=summary}};
 const panel={open:true,querySelector:()=>summary};
 const image={getBoundingClientRect:()=>({left:100,top:100,right:200,bottom:200,width:100,height:100})};
 const widget={style:{},getBoundingClientRect:()=>({left:100,top:100,width:100,height:100}),contains:el=>el===button,querySelector:()=>image,querySelectorAll:()=>[],getAttribute:name=>attrs.get(name)??null,hasAttribute:name=>attrs.has(name),setAttribute:(name,value)=>attrs.set(name,String(value)),removeAttribute:name=>attrs.delete(name)};
 const button={blur(){document.activeElement=null}};
 const menuAttrs=new Map(),menuButton={};
 const menu={opened:false,contains:el=>el===menuButton,classList:{contains:()=>menu.opened},getAttribute:name=>menuAttrs.get(name)??null,setAttribute:(name,value)=>menuAttrs.set(name,String(value)),removeAttribute:name=>menuAttrs.delete(name)};
 const document={activeElement:button,head:{appendChild(){}},body:{},getElementById:id=>id==='root'?{}:id==='harness-vm-identity'?panel:null,createElement:()=>({}),querySelector:()=>widget,querySelectorAll:selector=>selector==='.dshwv-menu'?[menu]:[],addEventListener(name,fn){events.set(name,fn)}};
 vm.runInNewContext('('+installFloatingLayout.toString()+')(()=>({x:100,y:100}))',{document,window:{addEventListener(name,fn){events.set(name,fn)}},getComputedStyle:()=>({}),innerWidth:425,innerHeight:664,setTimeout(fn){timers.push(fn)}});
 return{attrs,widget,document,summary,panel,menu,menuAttrs,menuButton,run(){timers.shift()?.()},resize(){events.get('resize')();this.run()}};
}

test('An occluded widget becomes inert and moves an existing focus to the visible summary',()=>{
 const f=fixture();f.run();
 assert.equal(f.attrs.has('inert'),true,'Transparent controls must leave the tab sequence');
 assert.equal(f.attrs.get('aria-hidden'),'true');
 assert.equal(f.document.activeElement,f.summary);
 f.panel.open=false;f.resize();
 assert.equal(f.attrs.has('inert'),false);assert.equal(f.attrs.has('aria-hidden'),false);
 assert.equal(f.document.activeElement,f.summary,'Reappearing must not steal focus');
});
test('A widget owner\'s original inert and aria-hidden values survive hide/show',()=>{
 const f=fixture({'inert':'','aria-hidden':'false'});f.run();f.panel.open=false;f.resize();
 assert.equal(f.attrs.get('inert'),'');assert.equal(f.attrs.get('aria-hidden'),'false');
});
test('The independently mounted menu leaves the tab sequence while closed or occluded, and restores when opened',()=>{
 const f=fixture();f.panel.open=false;f.run();
 assert.equal(f.menuAttrs.has('inert'),true,'The detached transparent menu must also be inert');
 f.menu.opened=true;f.resize();assert.equal(f.menuAttrs.has('inert'),false);
 f.document.activeElement=f.menuButton;f.panel.open=true;f.resize();
 assert.equal(f.menuAttrs.get('aria-hidden'),'true');assert.equal(f.document.activeElement,f.summary);
 f.panel.open=false;f.resize();assert.equal(f.menuAttrs.has('inert'),false);
 f.menu.opened=false;f.resize();assert.equal(f.menuAttrs.has('inert'),true);
});
