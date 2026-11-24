import {installStartupDiagnostics} from './personal-startup-diagnostics.mjs';
// Runs before the main module, so an asset/import failure cannot leave only a
// blank root. Recovery is always an explicit reload, never an operation replay.
function browserStartupRecovery() {
  const id = 'dsh-startup-recovery'
  const endpoint='/dsh-purge/startup-diagnostics',key='dsh-startup-pending-v1',start=performance.now(),seen=new Set();let page=null,sequence=0,flushing=false,mounted=false,observer,emptyNotice=false;
  try{page=Array.from(window.crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('')}catch{}
  let pending=[];try{const raw=window.sessionStorage?.getItem(key);if(raw&&raw.length<16384){const v=JSON.parse(raw);if(Array.isArray(v))pending=v.slice(-24)}}catch{}
  const persist=()=>{try{window.sessionStorage?.setItem(key,JSON.stringify(pending))}catch{}};
  const flush=async()=>{
    if(flushing||!['http://127.0.0.1:49226','http://127.0.0.1:49224'].includes(window.location.origin)||!window.fetch)return;
    flushing=true;
    try{while(pending.length){const submitted=pending[0],controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);try{const r=await window.fetch(endpoint,{method:'POST',headers:{'content-type':'application/json','x-dsh-startup':'1'},body:JSON.stringify(submitted),credentials:'same-origin',redirect:'error',cache:'no-store',keepalive:true,signal:controller.signal});if(!r.ok||!(await r.json()).ok)break;const at=pending.indexOf(submitted);if(at>=0)pending.splice(at,1);persist()}finally{clearTimeout(timer)}}}catch{}finally{flushing=false}
  };
  const record=(code,resource=null)=>{
    if(!page||seen.has(code)||sequence>=12)return;seen.add(code);
    pending.push({page,sequence:++sequence,code,elapsedMs:Math.min(3600000,Math.max(0,Math.round(performance.now()-start))),ready:document.readyState,visible:document.visibilityState!=='hidden',rootChildren:document.getElementById('root')?.childElementCount?1:0,resource});if(pending.length>24){const firstFailure=pending.findIndex(e=>e.code!=='mounted');pending.splice(firstFailure===0?1:0,1)}persist();void flush();
  };
  const labels={'empty-root':'界面在启动等待期限内尚未显示。','script-error':'页面脚本资源加载失败。','style-error':'页面样式资源加载失败。','module-error':'页面模块导入失败。','runtime-error':'页面脚本发生启动错误。',rejection:'页面启动任务未完成。'};
  const show = (reason = 'empty-root') => {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => show(reason), { once: true })
      return
    }
    if (reason==='empty-root' && document.getElementById('root')?.childElementCount) return
    if (document.getElementById(id)) return
    const notice = document.createElement('aside')
    notice.id = id
    notice.setAttribute('role', 'alert')
    notice.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;box-sizing:border-box;max-width:420px;width:calc(100% - 32px);padding:16px;border:1px solid #bd903e;border-radius:10px;background:#fffdf5;color:#29251c;font:14px/1.6 system-ui,sans-serif;box-shadow:0 4px 24px #0002'
    const message = document.createElement('div')
    emptyNotice=reason==='empty-root';message.textContent = labels[reason]+' 可以手动重新加载；操作不会自动重放。'
    notice.appendChild(message)
    const identity=document.createElement('div');identity.textContent='诊断：'+reason+' · '+(page||'记录不可用');notice.appendChild(identity);
    if (window.location.origin === 'http://127.0.0.1:49226') {
      const link = document.createElement('a')
      link.href = '/__harness/health'
      link.textContent = '查看本机连接状态'
      link.style.cssText = 'display:block;color:#254e8c'
      notice.appendChild(link)
      const details=document.createElement('a');details.href=endpoint;details.target='_blank';details.rel='noopener';details.textContent='查看保留的启动诊断';details.style.cssText='display:block;color:#254e8c';notice.appendChild(details);
    }
    for (const [label, action] of [['重新加载页面', () => window.location.reload()], ['关闭提示', () => notice.remove()]]) {
      const button = document.createElement('button')
      button.textContent = label
      button.style.cssText = 'margin:12px 8px 0 0;padding:6px 12px;border:1px solid #85754e;border-radius:6px;background:#fff;color:#29251c;font:inherit;cursor:pointer'
      button.addEventListener('click', action)
      notice.appendChild(button)
    }
    document.body.appendChild(notice)
  }
  window.addEventListener('error', event => {
    const target = event.target
    if(target===window||!target?.tagName){if(!document.getElementById('root')?.childElementCount){record('runtime-error');show('runtime-error')}return}
    if (target?.tagName !== 'SCRIPT' && !(target?.tagName === 'LINK' && target.rel === 'stylesheet')) return
    const url = String(target.src || target.href || '')
    if (url.startsWith(window.location.origin + '/assets/') || url.startsWith(window.location.origin + '/plugins/')) {
      const code=target.tagName==='SCRIPT'?'script-error':'style-error';show(code);
      void(async()=>{let hash=null,status=0;try{const u=new URL(url),bytes=await window.crypto.subtle.digest('SHA-256',new TextEncoder().encode(u.pathname));hash=Array.from(new Uint8Array(bytes),n=>n.toString(16).padStart(2,'0')).join('');const timing=performance.getEntriesByName?.(url)?.at(-1);if(Number.isSafeInteger(timing?.responseStatus))status=timing.responseStatus}catch{}record(code,{category:url.startsWith(window.location.origin+'/assets/')?'assets':'plugins',hash,status})})();
    }
  }, true)
  window.addEventListener('unhandledrejection',event=>{if(mounted)return;const code=/dynamically imported module|module script|Importing a module/i.test(String(event.reason?.message||''))?'module-error':'rejection';record(code);show(code)});
  const watch=()=>{
    const check=()=>{if(mounted||!document.getElementById('root')?.childElementCount)return;mounted=true;record('mounted');if(emptyNotice)document.getElementById(id)?.remove();observer?.disconnect()};
    check();if(!mounted&&typeof MutationObserver==='function'){observer=new MutationObserver(check);observer.observe(document.getElementById('root')||document.body,{childList:true,subtree:true})}
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',watch,{once:true});else watch();
  setTimeout(() => {
    const root = document.getElementById('root')
    if (!root || !root.childElementCount){record('empty-root');show('empty-root')}
  }, 15000)
  void flush();
}

export function installStartupRecovery(ctx) {
  installStartupDiagnostics(ctx);
  ctx.on('webserver/index-inject', table => table.unshift({
    kind: 'script', placement: 'head', text: '(' + browserStartupRecovery.toString() + ')()',
  }))
}
