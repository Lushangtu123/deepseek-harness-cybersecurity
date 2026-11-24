import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source=fs.readFileSync(new URL('../package/client.js',import.meta.url),'utf8')
test('Import confirmation is inside the page and includes an explicit cancel action',()=>{
 assert.ok(!source.includes('window.confirm(message)'),'Native confirmation dialogs block the in-app browser')
 assert.ok(source.includes('确认导入并打开'));assert.ok(source.includes('取消导入'))
})
test('The manager declares the official remote terminal namespace required for directory reads',()=>{
 const declaration=source.match(/const inject = (\[[^;]+\]);/)[1]
 const inject=vm.runInNewContext(declaration)
 assert.ok(inject.includes('remote'));assert.ok(inject.includes('remote.terminal'))
})
test('Escape in a busy manager cannot escape to the full-page close handler',()=>{
 let index=0,stopped=false,closed=false
 const scope={VmToolchainStatusCard:()=>null,vmShellWorkbenchHost:null,useState:value=>[index++===4?true:value,()=>{}],useRef:value=>({current:value}),useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node})}
 const start=source.indexOf('function VmWorkbenchManager('),end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start)
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope)
 vm.runInNewContext(source.slice(start,end)+'\nrender=VmWorkbenchManager;',scope)
 const panel=scope.render({onClose:()=>{closed=true}})
 panel.props.onKeyDown({key:'Escape',stopPropagation:()=>{stopped=true}})
 assert.equal(stopped,true);assert.equal(closed,false)
})
test('A busy import allows stopping the wait and closing the panel',()=>{
 let index=0,closed=false;
 const scope={VmToolchainStatusCard:()=>null,vmShellWorkbenchHost:null,useState:value=>{const i=index++;return[i===4||i===11?true:value,()=>{}]},useRef:value=>({current:value}),useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node})};
 const start=source.indexOf('function VmWorkbenchManager('),end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start);
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope);
 vm.runInNewContext(source.slice(start,end)+'\nrender=VmWorkbenchManager;',scope);
 const panel=scope.render({onClose:()=>{closed=true}}),buttons=[];
 const visit=node=>{if(Array.isArray(node))return node.forEach(visit);if(node?.tag){if(node.tag==='button')buttons.push(node);visit(node.children)}};visit(panel);
 assert.equal(buttons.find(node=>node.props?.['aria-label']==='关闭').props.disabled,false);
 assert.ok(buttons.some(node=>node.children.includes('停止等待')));
 panel.props.onKeyDown({key:'Escape',stopPropagation(){}});assert.equal(closed,true);
})
test('An exited terminal never offers an input takeover action',()=>{
 let index=0
 const dead=[{sessionId:'session-A',tabId:'dead',contentId:'dead',state:{phase:'connected',writable:false,info:{state:'exited',title:'dead terminal',cwd:'/home/purge/workspace'}}}]
 const scope={VmToolchainStatusCard:()=>null,vmShellWorkbenchHost:null,useState:value=>[index++===0?dead:value,()=>{}],useRef:value=>({current:value}),useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node})}
 const start=source.indexOf('function VmWorkbenchManager('),end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start)
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope)
 vm.runInNewContext(source.slice(start,end)+'\nrender=VmWorkbenchManager;',scope)
 const tree=scope.render({onClose(){}})
 const strings=[];function visit(value){if(Array.isArray(value))value.forEach(visit);else if(typeof value==='string')strings.push(value);else if(value?.children)visit(value.children)}visit(tree)
 assert.ok(strings.includes('已退出'));assert.ok(!strings.includes('接管输入'))
})

test('Unavailable records are folded separately while the usable terminal remains visible first',()=>{
 let index=0
 const rows=[{tabId:'dead',contentId:'dead',state:{phase:'failed'},processState:'missing'},{tabId:'good',contentId:'good',state:{phase:'connected',info:{state:'running',title:'usable shell'}},processState:'running'}]
 const scope={VmToolchainStatusCard:()=>null,vmShellWorkbenchHost:null,useState:value=>[index++===0?rows:value,()=>{}],useRef:value=>({current:value}),useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{}},require:()=>({createPortal:node=>node})}
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope)
 const start=source.indexOf('function VmWorkbenchManager('),end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start)
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope)
 vm.runInNewContext(source.slice(start,end)+'\nrender=VmWorkbenchManager;',scope)
 const tree=scope.render({onClose(){}}),all=[]
 function visit(value){if(Array.isArray(value))value.forEach(visit);else if(value?.tag){all.push(value);visit(value.children)}}visit(tree)
 const folded=all.find(node=>node.tag==='details');assert.ok(folded,'Unavailable terminals should not fill the first screen');assert.ok(!folded.props?.open)
 const cards=all.filter(node=>node.tag==='article');assert.equal(cards.length,2);assert.ok(JSON.stringify(cards[0]).includes('usable shell'));assert.ok(JSON.stringify(folded).includes('dead'))
})
test('Toolchain source links stay in the modal keyboard focus order',()=>{
 let prevented=false,refs=0;const first={focus(){}},link={focus(){}};
 const scope={VmToolchainStatusCard:()=>null,vmShellWorkbenchHost:null,useState:value=>[value,()=>{}],useRef:value=>({current:refs++===0?{querySelectorAll:selector=>selector.includes('a[href]')?[first,link]:[first]}:value}),useEffect(){},h:(tag,props,...children)=>({tag,props,children}),document:{body:{},activeElement:first},require:()=>({createPortal:node=>node})};
 vm.runInNewContext(source.slice(source.indexOf('function vmTerminalUnavailable('),source.indexOf('\n\t\tasync function importVmClone(')),scope);
 const start=source.indexOf('function VmWorkbenchManager('),end=source.indexOf('\n\t\tfunction ShellWorkbenchButton(',start);
 vm.runInNewContext(source.slice(start,end)+'\nrender=VmWorkbenchManager;',scope);
 scope.render({onClose(){}}).props.onKeyDown({key:'Tab',shiftKey:false,preventDefault(){prevented=true}});
 assert.equal(prevented,false,'Tab should reach the source link before wrapping to the first button');
});
