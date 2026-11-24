import http from 'node:http'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { Transform } from 'node:stream'
import { createHash, randomUUID } from 'node:crypto'
import { createDiagnostics, HEALTH_HTML, ENVIRONMENT_BANNER, RECOVERY_HTML, STORAGE_HTML, STORAGE_SCRIPT } from './web-health.mjs'

const executeFile = promisify(execFile)
export function createStorageMonitor({run=signal=>executeFile('/opt/homebrew/bin/python3',[fileURLToPath(new URL('./manage.py',import.meta.url)),'storage-capacity'],{timeout:10000,maxBuffer:8192,signal}),schedule=callback=>setInterval(callback,60000),unschedule=clearInterval,now=()=>performance.now(),wallNow=Date.now}={}){
 const policy={warningFreeBytes:10*1024**3,criticalFreeBytes:5*1024**3,warningFreePercent:15,criticalFreePercent:5,warningFreeInodePercent:15,criticalFreeInodePercent:5};
 let pending,latest,checked,attempted,timer,controller,failed=false,stopped=false;
 const stamp=()=>({mono:now(),wall:wallNow()});
 const age=at=>{if(!at)return Infinity;const mono=now()-at.mono,wall=wallNow()-at.wall;return mono<0||wall<0?Infinity:Math.max(mono,wall)};
 function filesystem(value,inodes=false){
  if(value==null)return null;
  const keys=['totalBytes','availableBytes',...(inodes?['inodeTotal','inodeAvailable']:[])];
  if(keys.some(key=>!Number.isSafeInteger(value[key])||value[key]<0)||!value.totalBytes||value.availableBytes>value.totalBytes||inodes&&value.inodeAvailable>value.inodeTotal)throw Error('Invalid capacity');
  const ratio=value.availableBytes/value.totalBytes;
  let state=value.availableBytes<policy.criticalFreeBytes||ratio<.05?'critical':value.availableBytes<policy.warningFreeBytes||ratio<.15?'warning':'healthy';
  if(inodes&&value.inodeTotal){const free=value.inodeAvailable/value.inodeTotal;if(free<.05)state='critical';else if(free<.15&&state==='healthy')state='warning'}
  return{state,...Object.fromEntries(keys.map(key=>[key,value[key]])),availablePercent:Math.round(ratio*10000)/100};
 }
 function snapshot(){
  const elapsed=age(checked),current=latest&&elapsed<90000&&!failed;
  return{version:1,readOnly:true,automaticChanges:false,deletionAvailable:false,monitoring:timer!==undefined&&!stopped,intervalSeconds:60,staleAfterSeconds:90,policy,
   state:stopped?'stopped':failed?'unavailable':!latest?'not-observed':!current?'stale':!latest.hostFilesystem||latest.guest.state==='unavailable'?'partial':'current',sampling:!!pending,checkedAt:checked?new Date(checked.wall).toISOString():null,ageMs:Number.isFinite(elapsed)?Math.round(elapsed):null,
   hostFilesystem:latest?.hostFilesystem??null,guest:latest?.guest??{state:'unavailable'}};
 }
 function refresh(){
  if(stopped)return Promise.resolve(snapshot());
  if(pending)return pending;
  if(age(attempted)<5000)return Promise.resolve(snapshot());
  attempted=stamp();controller=new AbortController();
  const task=(async()=>{
   try{
    const result=await run(controller.signal);
    if(age(attempted)>15000)throw Error('Capacity observation crossed a timer gap');
    if(typeof result.stdout!=='string'||Buffer.byteLength(result.stdout)>8192)throw Error('Capacity response limit');
    const value=JSON.parse(result.stdout);
    if(value?.version!==1||value.readOnly!==true||value.automaticChanges!==false||value.deletionAvailable!==false||!['observed','not-running','unavailable'].includes(value.guest?.state))throw Error('Invalid capacity report');
    const guest=value.guest.state==='observed'?{state:'observed',filesystem:filesystem(value.guest.filesystem,true)}:{state:value.guest.state};
    if(guest.state==='observed'&&!guest.filesystem)throw Error('Missing VM counters');
    const host=filesystem(value.hostFilesystem);
    if(!stopped){latest={hostFilesystem:host,guest};checked=attempted;failed=false}
   }catch{if(!stopped)failed=true}
  })();
  pending=task.finally(()=>{pending=undefined;controller=undefined}).then(snapshot);
  return pending;
 }
 return{snapshot,refresh,start(){if(stopped||timer!==undefined)return;timer=schedule(()=>pending?undefined:refresh());timer?.unref?.();void refresh()},stop(){stopped=true;if(timer!==undefined)unschedule(timer);timer=undefined;controller?.abort()}};
}
export function createClockMonitor({run=()=>executeFile('/opt/homebrew/bin/python3',[fileURLToPath(new URL('./manage.py',import.meta.url)),'clock-maintain'],{timeout:20000,maxBuffer:8192}),schedule=callback=>setInterval(callback,60000),unschedule=clearInterval,observe=()=>{}}={}) {
  let stopped=false,pending=false
  const tick=async()=>{
    if(stopped||pending)return
    pending=true
    try{
      const value=JSON.parse((await run()).stdout)
      if(!['current','adjusted','skipped'].includes(value?.state))throw Error('Invalid clock result')
      if(!stopped)observe({state:value.state,adjusted:value.adjusted===true,...(Number.isFinite(value.offsetSeconds)?{offsetSeconds:value.offsetSeconds}:{})})
    }catch(error){if(!stopped)observe({state:'unavailable',failure:typeof error?.stderr==='string'&&error.stderr.includes('.vm-operation.lock')&&error.stderr.includes('Operation not permitted')?'vm-lock-denied':typeof error?.stderr==='string'&&error.stderr.includes('utmctl')?'vm-controller-unavailable':'clock-command-failed',...(Number.isInteger(error?.code)?{exitCode:error.code}:{})})}
    finally{pending=false}
  }
  const timer=schedule(tick);timer?.unref?.()
  return()=>{stopped=true;unschedule(timer)}
}
const publicCursor=value=>typeof value==='string'&&value.length<=240&&(value===''||/^[A-Za-z0-9][A-Za-z0-9 ._-]*$/.test(value)&&!/credential|secret|token|provider/i.test(value));
const archiveCursor=value=>publicCursor(value)||typeof value==='string'&&value.length<=4096&&/^v1:[A-Za-z0-9_-]+$/.test(value);
const catalogParts=new Set(['all','snapshots','images']);
const catalogError=(code,phase,details={})=>Object.assign(Error('Recovery catalog unavailable'),{catalogCode:code,catalogPhase:phase,...details});
function controllerError(error){
  const details={};
  if(Number.isInteger(error?.code)&&error.code>=0&&error.code<=255)details.exitCode=error.code;
  if(['SIGTERM','SIGKILL','SIGINT','SIGABRT'].includes(error?.signal))details.signal=error.signal;
  const code=error?.code==='ERR_CHILD_PROCESS_STDIO_MAXBUFFER'?'output-limit':error?.killed?'controller-terminated':['ENOENT','EACCES'].includes(error?.code)?'controller-unavailable':'controller-failed';
  return catalogError(code,'controller',details);
}
export function createRecoveryReader({run=(after,snapshotAfter,part)=>executeFile('/opt/homebrew/bin/python3',[fileURLToPath(new URL('./manage.py',import.meta.url)),'recoveries','--catalog-part',part,...(after?['--archive-after',after]:[]),...(snapshotAfter?['--snapshot-after',snapshotAfter]:[])],{timeout:9000,maxBuffer:131072}),now=()=>performance.now(),wallNow=Date.now}={}) {
  const pending=new Map(),cache=new Map()
  const name=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,240}$/.test(value)&&!value.split('/').some(part=>!part||part==='.'||part==='..'||part.startsWith('.')||/credential|secret|token|provider/i.test(part))
  const number=value=>Number.isSafeInteger(value)&&value>=0?value:null
  const date=value=>typeof value==='string'&&/^[0-9T:Z.+-]{1,40}$/.test(value)&&Number.isFinite(Date.parse(value))?value:null
  return (after='',snapshotAfter='',part='all')=>{
    if(!catalogParts.has(part)||!archiveCursor(after)||!publicCursor(snapshotAfter)||part==='images'&&snapshotAfter||part==='snapshots'&&after)return Promise.reject(Error('Invalid recovery cursor'))
    const key=JSON.stringify([after,snapshotAfter,part]),saved=cache.get(key)
    if(saved&&now()-saved.mono>=0&&wallNow()-saved.wall>=0&&now()-saved.mono<5000&&wallNow()-saved.wall<5000)return Promise.resolve(saved.value)
    if(pending.has(key))return pending.get(key)
    if(pending.size>=4)return Promise.reject(catalogError('catalog-busy','queue'))
    const request=Promise.resolve().then(()=>run(after,snapshotAfter,part)).catch(error=>{throw controllerError(error)}).then(result=>{
      let value;try{value=JSON.parse(result.stdout)}catch{throw catalogError('invalid-json','parse')}
      const wantsSnapshots=part!=='images',wantsImages=part!=='snapshots';
      if(!value||value.readOnly!==true||!name(value.currentRecovery)||value.part!==undefined&&value.part!==part||wantsSnapshots&&(!Array.isArray(value.snapshots)||!['observed','unavailable'].includes(value.snapshotState))||wantsImages&&!Array.isArray(value.images))throw catalogError('invalid-catalog','validate')
      const validSnapshots=wantsSnapshots?value.snapshots.filter(row=>row&&name(row.name)&&!row.name.includes('/')):[];
      const validImages=wantsImages?value.images.filter(row=>row&&name(row.id)&&row.id.endsWith('.qcow2')):[];
      const snapshots=validSnapshots.slice(0,80).map(row=>({name:row.name,present:typeof row.present==='boolean'?row.present:null,current:row.current===true,protected:row.protected===true,reviewCandidate:row.reviewCandidate===true&&!row.protected&&row.present===true,bundleState:['verified','missing','invalid','not-reviewed'].includes(row.bundleState)?row.bundleState:'unknown',createdAt:date(row.createdAt)}))
      const images=validImages.slice(0,80).map(row=>({id:row.id,logicalBytes:number(row.logicalBytes),allocatedBytes:number(row.allocatedBytes),reviewCandidate:row.reviewCandidate===true}))
      const nextCursor=wantsImages?value.nextCursor??null:null
      if(nextCursor!==null&&(!archiveCursor(nextCursor)||nextCursor===after||publicCursor(nextCursor)&&publicCursor(after)&&nextCursor<=after))throw Object.assign(Error('Invalid next archive cursor'),{catalogCode:'invalid-catalog',catalogPhase:'validate'})
      const nextSnapshotCursor=wantsSnapshots?value.nextSnapshotCursor??null:null
      if(nextSnapshotCursor!==null&&(!publicCursor(nextSnapshotCursor)||nextSnapshotCursor<=snapshotAfter))throw Object.assign(Error('Invalid next snapshot cursor'),{catalogCode:'invalid-catalog',catalogPhase:'validate'})
      const scan=value.archiveScan,reasons=new Set();
      if(scan!=null&&(typeof scan!=='object'||Array.isArray(scan)||['reasons','continuationReasons'].some(key=>scan[key]!==undefined&&!Array.isArray(scan[key]))))throw catalogError('invalid-catalog','validate');
      for(const reason of Array.isArray(scan?.reasons)?scan.reasons:[])reasons.add(['snapshot-limit','snapshot-name-limit','entry-limit','directory-entry-limit','depth-limit','read-error','invalid-root'].includes(reason)?reason:'unknown-limit');
      if(wantsSnapshots&&validSnapshots.length!==value.snapshots.length)reasons.add('snapshot-invalid-record');
      if(wantsImages&&validImages.length!==value.images.length)reasons.add('image-invalid-record');
      if(validSnapshots.length>80)reasons.add('snapshot-limit');
      if(validImages.length>80)reasons.add('image-record-limit');
      const archiveScan={...Object.fromEntries(['entriesScanned','entriesRemaining','visitedDirectories','skippedMetadataDirectories'].map(key=>[key,number(scan?.[key])])),reasons:[...reasons],continuationReasons:[...new Set((Array.isArray(scan?.continuationReasons)?scan.continuationReasons:[]).filter(reason=>['directory-limit','image-limit','time-limit'].includes(reason)))]};
      const cached={part,archiveScan,readOnly:true,currentRecovery:value.currentRecovery,observedAt:date(value.observedAt),truncated:value.truncated===true||reasons.size>0||validSnapshots.length>80||validImages.length>80,
        ...(wantsSnapshots?{nextSnapshotCursor,snapshotState:value.snapshotState,snapshots}:{}),
        ...(wantsImages?{nextCursor,images,storage:Object.fromEntries(['freeBytes','totalBytes','primaryLogicalBytes','primaryAllocatedBytes'].map(key=>[key,number(value.storage?.[key])]))}:{})};
      cache.delete(key);cache.set(key,{value:cached,mono:now(),wall:wallNow()});if(cache.size>8)cache.delete(cache.keys().next().value);return cached
    }).finally(()=>{pending.delete(key)})
    pending.set(key,request);return request
  }
}
export function createEnvironmentReader({ run = () => executeFile('/opt/homebrew/bin/python3', [fileURLToPath(new URL('./manage.py', import.meta.url)), 'environment'], { timeout: 10000, maxBuffer: 32768 }), now = () => performance.now(), wallNow = Date.now } = {}) {
  let pending, cached, checkedMono, checkedWall
  return () => {
    const monoAge = now() - checkedMono, wallAge = wallNow() - checkedWall
    if (cached && monoAge >= 0 && wallAge >= 0 && monoAge < 5000 && wallAge < 5000) return Promise.resolve(cached)
    if (pending) return pending
    pending = Promise.resolve().then(run).then(result => {
      const value = JSON.parse(result.stdout)
      if (!['original', 'improved', 'unknown'].includes(value.mode) || !['/home/purge/.dsh', '/home/purge/.dsh-improved', 'unverified'].includes(value.configDir) || !['matches', 'older', 'missing', 'invalid'].includes(value.recovery?.state)) throw Error('Invalid local status')
      // Fixed public metadata only; command stderr, credentials and arbitrary fields never reach HTTP.
      const allowedPaths = new Set(['.config/harness-original-capabilities', '.dsh-improved/cordis.patch.yml', '.dsh-improved/profiles/web/package.json', '.dsh-improved/profiles/web/cordis.patch.yml', '.dsh-improved/AGENTS.md', '.config/harness-vm-mode', '.local/bin/harness-vm-web', '.local/bin/toolchain-versions', ...['index.mjs', 'process.mjs', 'check_versions.py', 'catalog.json'].map(name => '.dsh-improved/tooling/toolchain-version-checker/' + name)])
      const pluginRoot='tools/imported-dsh-plugins-20261027T185822Z/'
      for(const name of ['dsh-context','dsh-whale-widget','dshmarket'])allowedPaths.add('.dsh-improved/profiles/web/node_modules/'+name)
      const pluginPath=path=>typeof path==='string'&&path.startsWith(pluginRoot)&&['dsh-context','dsh-whale-widget','dshmarket'].some(name=>path.startsWith(pluginRoot+name+'/'))&&/^[A-Za-z0-9._/-]{1,240}$/.test(path)&&!path.split('/').some(part=>!part||part==='.'||part==='..'||(part.startsWith('.')&&part!=='.gitkeep')||/credential|secret|token|provider/i.test(part))
      for (const name of ['dsh-tools', 'dsh-tool-bash', 'dsh-permission-presets', 'dsh-user-approval']) allowedPaths.add('tools/harness-improved-runtime/node_modules/@deepseek-ai/' + name + '/lib/index.js')
      for (const name of ['package.json', 'lib/bin.js']) allowedPaths.add('tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/' + name)
      for (const name of ['.personal-runtime-manifest.json','lib/bin.js','package.json']) allowedPaths.add('tools/harness-original-capabilities/'+name)
      for (const name of ['dsh-tools','dsh-tool-bash','dsh-permission-presets','dsh-user-approval']) allowedPaths.add('tools/harness-original-capabilities/node_modules/@deepseek-ai/'+name+'/lib/index.js')
      for (const name of ['manage.py', 'egress_proxy.py', 'qemu-image.py', 'web-entry.mjs', 'web-health.mjs']) allowedPaths.add('host-tools/' + name)
      for (const label of ['com.personal.harness-purge-original-egress', 'com.personal.harness-purge-original-web-entry']) allowedPaths.add('host-launch-agents/' + label + '.plist')
      const approvedPath = path => typeof path === 'string' && (allowedPaths.has(path) || pluginPath(path) || (path.startsWith('tools/dsh-purge-personal-1.1.77-personal.1/') && /^[A-Za-z0-9._/-]{1,240}$/.test(path) && !path.split('/').some(part => !part || part === '.' || part === '..' || /credential|secret|token|provider/i.test(part))))
      const paths = value => Array.isArray(value) ? [...new Set(value.filter(approvedPath))] : []
      const allChanged = []
      let changedCount=0,truncated=false
      const groups = Object.fromEntries(['program', 'runtime', 'tools', 'config', 'plugins'].map(key => {
        const group = value.recovery.groups?.[key]
        const differentFiles = paths(group?.differentFiles); allChanged.push(...differentFiles)
        changedCount+=Number.isSafeInteger(group?.differentFileCount)&&group.differentFileCount>=differentFiles.length&&group.differentFileCount<=50000?group.differentFileCount:differentFiles.length
        truncated||=group?.differenceDetailsTruncated===true
        return [key, { state: ['matches', 'older', 'missing', 'invalid', 'uncovered'].includes(group?.state) ? group.state : 'unknown', filesChecked: Number.isSafeInteger(group?.filesChecked) && group.filesChecked >= 0 && group.filesChecked <= 50000 ? group.filesChecked : 0, differentFiles: differentFiles.slice(0, 80) }]
      }))
      const uncoveredFiles = paths(value.recovery.uncoveredFiles)
      const changed = [...new Set(allChanged)]
      const runtimePackageVersion = typeof value.runtimePackageVersion === 'string' && /^[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}$/.test(value.runtimePackageVersion) ? value.runtimePackageVersion : null
      cached = { originalCapabilities: value.mode === "improved" && value.originalCapabilities === true, mode: value.mode, configDir: value.configDir, runtimePackageVersion, modeFileMatches: value.modeFileMatches === true, observedAt: value.observedAt, recovery: { state: value.recovery.state, name: value.recovery.name, createdAt: value.recovery.createdAt, scope: 'improved-program-tools-config', groups, uncoveredFiles, helpersMatch: value.recovery.helpersMatch === true, launchAgentsMatch: typeof value.recovery.launchAgentsMatch === 'boolean' ? value.recovery.launchAgentsMatch : null, differentFiles: changed.slice(0, 80), differentFileCount: Math.max(changed.length,changedCount), differenceDetailsTruncated: changed.length > 80||truncated } }
      checkedMono = now(); checkedWall = wallNow()
      return cached
    }).finally(() => { pending = undefined })
    return pending
  }
}

function bannerTransform() {
  let buffered = Buffer.alloc(0), done = false
  const tag = Buffer.from('<script defer src="/__harness/banner.js"></script><script defer src="/__harness/storage.js"></script>')
  return new Transform({ transform(chunk, _encoding, next) {
    if (done) { this.push(chunk); next(); return }
    buffered = Buffer.concat([buffered, chunk])
    const at = buffered.indexOf('</head>')
    if (at >= 0) { this.push(Buffer.concat([buffered.subarray(0, at), tag, buffered.subarray(at)])); done = true; buffered = Buffer.alloc(0) }
    else if (buffered.length > 65536) { this.push(buffered); done = true; buffered = Buffer.alloc(0) }
    next()
  }, flush(next) { if (buffered.length) this.push(buffered); next() } })
}

// Private loopback entry for the existing VM service. One reusable HTTP socket
// serializes initial connections through SLiRP. Upgraded sockets leave the
// agent's pool, so long-lived Harness WebSockets do not block ordinary requests.
export function createWebEntry({ upstreamPort = 49224, responseTimeoutMs = 30000, bodyIdleTimeoutMs = 15000, environmentReader = createEnvironmentReader(), recoveryReader = createRecoveryReader(), storageMonitor = createStorageMonitor(), capabilityRun = action => executeFile('/opt/homebrew/bin/python3',[fileURLToPath(new URL('./manage.py',import.meta.url)),'capabilities','--capability-mode',action],{timeout:150000,maxBuffer:32768}) } = {}) {
  const agent = new http.Agent({ keepAlive: true, maxSockets: 1, maxFreeSockets: 1 })
  const sockets = new Set()
  const diagnostics = createDiagnostics()
  const upstreamOrigin = 'http://127.0.0.1:49224'
  const entryOrigin = () => 'http://127.0.0.1:' + server.address().port
  let capabilityOperation, capabilityAdmissionBusy = false
  const cookieIdentity = req => typeof req.headers.cookie === 'string' && req.headers.cookie.length > 0 && req.headers.cookie.length <= 16384 ? createHash('sha256').update(req.headers.cookie).digest('hex') : null
  const publicOperation = operation => operation ? Object.fromEntries(['id','state','targetEnabled'].map(key=>[key,operation[key]])) : null
  const readOwnerPlugin = req => new Promise((resolve,reject)=>{
    const request=http.request({host:'127.0.0.1',port:upstreamPort,path:'/dsh-purge/status',method:'GET',headers:{host:'127.0.0.1:49224',cookie:req.headers.cookie||''},agent:false},response=>{
      const chunks=[];let bytes=0
      response.on('data',chunk=>{bytes+=chunk.length;if(bytes>2097152)request.destroy(Error('Invalid plugin response'));else chunks.push(chunk)})
      response.on('end',()=>{
        if(response.statusCode===401||response.statusCode===403){resolve({rejected:response.statusCode});return}
        try {
          const data=JSON.parse(Buffer.concat(chunks).toString())
          if(response.statusCode!==200||data?.ok!==true||data.ready!==true||data.originalCapabilities?.managed!==true||typeof data.originalCapabilities.enabled!=='boolean')throw Error('Plugin unavailable')
          resolve({ok:true,ready:true,originalCapabilities:{enabled:data.originalCapabilities.enabled,managed:true},...Object.fromEntries(['patches_applied','patches_total','patches_skipped'].map(key=>[key,Number.isSafeInteger(data[key])?data[key]:0]))})
        }catch{reject(Error('Plugin unavailable'))}
      })
      response.on('error',reject)
    })
    request.setTimeout(6000,()=>request.destroy(Error('Owner check deadline')))
    request.on('error',reject);request.end()
  })
  async function capabilities(req,res) {
    const send=(status,value)=>{if(!res.destroyed){res.writeHead(status,{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'});res.end(JSON.stringify(value))}}
    if(!['GET','POST'].includes(req.method)){send(405,{ok:false,error:'Method not allowed'});return}
    if(req.url!=='/__harness/capabilities'||req.headers['x-harness-local']!=='1'||req.headers['sec-fetch-site']==='cross-site'){send(403,{ok:false,error:'Local request required'});return}
    const owner=cookieIdentity(req)
    if(!owner){send(401,{ok:false,error:'Harness owner session required'});return}
    if(req.method==='GET'&&capabilityOperation?.state==='running'&&capabilityOperation.owner===owner){send(200,{ok:true,enabled:null,operation:publicOperation(capabilityOperation)});return}
    if(req.method==='POST'){
      if(req.headers.origin!==entryOrigin()){send(403,{ok:false,error:'Same-origin confirmation required'});return}
      if(String(req.headers['content-type']||'').split(';')[0].trim().toLowerCase()!=='application/json'){send(415,{ok:false,error:'JSON required'});return}
      if(capabilityAdmissionBusy||capabilityOperation?.state==='running'){send(409,{ok:false,error:'A capability switch is already running'});return}
      capabilityAdmissionBusy=true
    }
    try{
      let body
      if(req.method==='POST'){
        let text='',length=0
        for await(const chunk of req){length+=chunk.length;if(length>512){send(413,{ok:false,error:'Request too large'});return}text+=chunk}
        try{body=JSON.parse(text)}catch{send(400,{ok:false,error:'Invalid JSON'});return}
        if(!body||Array.isArray(body)||typeof body.enabled!=='boolean'||typeof body.expectedEnabled!=='boolean'||Object.keys(body).some(key=>!['enabled','expectedEnabled'].includes(key))){send(400,{ok:false,error:'Explicit boolean mode required'});return}
      }
      const plugin=await readOwnerPlugin(req)
      if(plugin.rejected){send(plugin.rejected,{ok:false,error:'Harness owner session required'});return}
      if(req.method==='GET'){send(200,{ok:true,enabled:plugin.originalCapabilities.enabled,pluginStatus:plugin,operation:capabilityOperation?.owner===owner?publicOperation(capabilityOperation):null});return}
      if(plugin.originalCapabilities.enabled!==body.expectedEnabled){send(409,{ok:false,error:'Current mode changed; refresh before confirming'});return}
      if(body.enabled===body.expectedEnabled){send(409,{ok:false,error:'Requested mode is already active'});return}
      if(req.aborted||res.destroyed)return
      const operation={id:randomUUID(),state:'running',targetEnabled:body.enabled,owner}
      capabilityOperation=operation
      Promise.resolve().then(()=>capabilityRun(body.enabled?'enable':'disable')).then(result=>{
        const value=JSON.parse(result.stdout)
        operation.state=value.enabled===body.enabled&&value.configured===body.enabled?'succeeded':'unconfirmed'
      }).catch(()=>{operation.state='unconfirmed'})
      send(202,{ok:true,operation:publicOperation(operation)})
    }catch{send(503,{ok:false,error:'Capability state unavailable; read status before trying again'})}
    finally{if(req.method==='POST')capabilityAdmissionBusy=false}
  }
  const upstreamHeaders = req => {
    const headers = { ...req.headers, host: '127.0.0.1:49224' }
    // Cross-origin requests are rejected at the entry before this mapping.
    // An absent origin remains absent for the guest's normal checks.
    if (headers.origin === entryOrigin()) headers.origin = upstreamOrigin
    return headers
  }
  const allowed = (req, res) => {
    if (req.headers.host !== '127.0.0.1:' + server.address().port) {
      res.writeHead(421); res.end('Use the private local Harness entry.'); return false
    }
    if (req.headers.origin !== undefined && req.headers.origin !== entryOrigin()) {
      res.writeHead(403); res.end('Cross-origin request rejected.'); return false
    }
    if (!req.url.startsWith('/') || req.url.startsWith('//')) {
      res.writeHead(400); res.end('Invalid local request target.'); return false
    }
    return true
  }
  function forward(req, res, attempt = 0, deadline = Date.now() + responseTimeoutMs) {
    const observation = diagnostics.begin(req.url, req.method)
    let observed = false, assignedMs = 0, bodyTimer, responseStatus
    const clearBodyTimer = () => { clearTimeout(bodyTimer); bodyTimer = undefined }
    const record = (status, error, phase = 'headers') => { if (!observed) { observed = true; diagnostics.finish(observation, status, error, assignedMs, phase) } }
    const headers = upstreamHeaders(req)
    if (req.method === 'GET' && req.url.split('?', 1)[0] === '/') delete headers['accept-encoding']
    for (const key of ['connection', 'proxy-connection', 'proxy-authorization', 'proxy-authenticate']) delete headers[key]
    const upstream = http.request({ host: '127.0.0.1', port: upstreamPort, path: req.url, method: req.method, headers, agent }, response => {
      clearTimeout(timer)
      responseStatus = response.statusCode
      if (res.destroyed || res.writableEnded) { response.destroy(); return }
      const stream = String(response.headers['content-type']).split(';', 1)[0].trim().toLowerCase() === 'text/event-stream'
      if (stream) {
        // Harness keeps a plugin subscription open for the page lifetime. Like
        // an upgraded WebSocket, it must leave the ordinary HTTP request pool.
        const peer = response.socket
        sockets.add(peer)
        peer.once('close', () => sockets.delete(peer))
        peer.emit('agentRemove')
        diagnostics.stream('sse', peer)
        record(response.statusCode, undefined, 'stream')
      } else {
        diagnostics.headers(observation, response.statusCode, assignedMs)
        const failBody = error => {
          clearBodyTimer()
          record(response.statusCode, error, 'body')
          response.destroy(); upstream.destroy(); res.destroy()
        }
        const progress = () => { clearBodyTimer(); bodyTimer = setTimeout(() => failBody('body-timeout'), bodyIdleTimeoutMs) }
        response.on('data', progress)
        response.once('end', () => { clearBodyTimer(); record(response.statusCode, response.complete ? undefined : 'body-incomplete', response.complete ? 'complete' : 'body') })
        response.once('aborted', () => failBody('body-incomplete'))
        response.once('error', () => failBody('body-incomplete'))
        response.once('close', () => { clearBodyTimer(); if (!response.complete) failBody('body-incomplete') })
        progress()
      }
      const outgoing = { ...response.headers }
      delete outgoing.connection
      const injectBanner = req.method === 'GET' && req.url.split('?', 1)[0] === '/' && response.statusCode === 200 && String(outgoing['content-type']).toLowerCase().startsWith('text/html') && !outgoing['content-encoding']
      if (injectBanner) { delete outgoing['content-length']; delete outgoing.etag }
      if (typeof outgoing.location === 'string' && (outgoing.location === upstreamOrigin || outgoing.location.startsWith(upstreamOrigin + '/'))) {
        outgoing.location = entryOrigin() + outgoing.location.slice(upstreamOrigin.length)
      }
      res.writeHead(response.statusCode, outgoing)
      response.on('error', () => res.destroy())
      if (injectBanner) { const transform = bannerTransform(); transform.on('error', () => res.destroy()); response.pipe(transform).pipe(res) }
      else response.pipe(res)
    })
    // Queue/header deadline and ordinary-body idle deadline are independent.
    // SSE and upgraded WebSockets keep their native long-lived lifetime.
    const unavailable = () => {
      if (res.destroyed || res.writableEnded) return
      if (!res.headersSent) {
        res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' })
        res.end('虚拟机连接暂时中断。请确认 VM 已启动，再重新加载页面。')
      } else res.destroy()
    }
    const timer = setTimeout(() => {
      record(undefined, 'deadline')
      upstream.destroy(new Error('Upstream response deadline'))
      // A request still queued in an Agent may not emit error until assigned a
      // socket. Respond now; the destroyed request must never execute later.
      unavailable()
    }, Math.max(0, deadline - Date.now()))
    upstream.once('close', () => clearTimeout(timer))
    upstream.once('socket', () => { assignedMs = performance.now() - observation.started })
    upstream.on('error', error => {
      record(undefined, error.code === 'ECONNRESET' ? 'connection-reset' : 'upstream-unavailable')
      clearTimeout(timer)
      if (res.destroyed || res.writableEnded) return
      // No replay of POSTs (including JSON APIs), uploads, or partial responses.
      if (!res.destroyed && !res.headersSent && attempt === 0 && Date.now() < deadline && ['GET', 'HEAD'].includes(req.method)
          && ['/assets/', '/plugins/'].some(prefix => req.url.startsWith(prefix))
          && !req.headers['transfer-encoding'] && !(Number(req.headers['content-length']) > 0)) {
        forward(req, res, 1, deadline); return
      }
      unavailable()
    })
    req.once('aborted', () => upstream.destroy())
    res.once('close', () => { clearBodyTimer(); if (!res.writableFinished) { record(responseStatus, 'client-cancelled', responseStatus === undefined ? 'headers' : 'body'); upstream.destroy() } })
    if (attempt) upstream.end()
    else req.pipe(upstream)
  }
  const server = http.createServer(async (req, res) => {
    if (!allowed(req, res)) return
    const recoveryPath=req.url.split('?',1)[0]
    if(['/__harness/storage','/__harness/storage/status','/__harness/storage.js'].includes(recoveryPath)){
      if(req.method!=='GET'){res.writeHead(405);res.end();return}
      const json=recoveryPath.endsWith('/status'),script=recoveryPath.endsWith('.js');
      if(req.headers['sec-fetch-site']==='cross-site'||json&&req.headers['x-harness-local']!=='1'){res.writeHead(403);res.end();return}
      const query=new URL(req.url,entryOrigin()).searchParams;
      if(query.size&&(!json||query.size!==1||query.get('refresh')!=='1')){res.writeHead(400);res.end();return}
      const headers={'cache-control':'no-store','x-content-type-options':'nosniff','content-type':json?'application/json; charset=utf-8':script?'application/javascript; charset=utf-8':'text/html; charset=utf-8'};
      if(!json){res.writeHead(200,headers);res.end(script?STORAGE_SCRIPT:STORAGE_HTML);return}
      let timer;
      try{
        const value=query.size?await Promise.race([storageMonitor.refresh(),new Promise((_resolve,reject)=>{timer=setTimeout(()=>reject(Error('Capacity deadline')),11000)})]):storageMonitor.snapshot();
        if(!res.destroyed){res.writeHead(200,headers);res.end(JSON.stringify(value))}
      }catch{if(!res.destroyed){res.writeHead(503,headers);res.end('{"error":"Capacity unavailable"}')}}
      finally{clearTimeout(timer)}
      return
    }
    if(recoveryPath==='/__harness/capabilities'){await capabilities(req,res);return}
    if(recoveryPath==='/__harness/recoveries'||recoveryPath==='/__harness/recovery'){
      if(req.method!=='GET'){res.writeHead(405);res.end();return}
      const json=recoveryPath.endsWith('/recoveries')
      if(req.headers['sec-fetch-site']==='cross-site'||json&&req.headers['x-harness-local']!=='1'){res.writeHead(403);res.end();return}
      const query=new URL(req.url,entryOrigin()).searchParams,after=query.get('after')??'',snapshotAfter=query.get('snapshotAfter')??'',part=query.get('part')??'all'
      if([...query.keys()].some(key=>!['after','snapshotAfter','part'].includes(key))||['after','snapshotAfter','part'].some(key=>query.getAll(key).length>1)||!archiveCursor(after)||!publicCursor(snapshotAfter)||!catalogParts.has(part)||part==='images'&&snapshotAfter||part==='snapshots'&&after||!json&&query.size){res.writeHead(400);res.end();return}
      const headers={'cache-control':'no-store','x-content-type-options':'nosniff','content-type':json?'application/json; charset=utf-8':'text/html; charset=utf-8'}
      if(!json){res.writeHead(200,headers);res.end(RECOVERY_HTML);return}
      let timer;const requestId=randomUUID(),observation=diagnostics.begin('/__harness/recoveries','GET');headers['x-harness-request-id']=requestId;
      try{
        const value=await Promise.race([recoveryReader(after,snapshotAfter,...(part==='all'?[]:[part])),new Promise((_resolve,reject)=>{timer=setTimeout(()=>reject(catalogError('catalog-timeout','deadline')),10000)})])
        diagnostics.catalog(observation,200,{requestId,part,phase:'complete'});
        if(!res.destroyed){res.writeHead(200,headers);res.end(JSON.stringify(value))}
      }catch(error){
        const code=['catalog-timeout','catalog-busy','output-limit','controller-terminated','controller-unavailable','controller-failed','invalid-json','invalid-catalog'].includes(error?.catalogCode)?error.catalogCode:'catalog-unavailable';
        const phase=['queue','controller','parse','validate','deadline'].includes(error?.catalogPhase)?error.catalogPhase:'reader';
        const detail={requestId,part,code,phase};
        if(Number.isInteger(error?.exitCode)&&error.exitCode>=0&&error.exitCode<=255)detail.exitCode=error.exitCode;
        if(['SIGTERM','SIGKILL','SIGINT','SIGABRT'].includes(error?.signal))detail.signal=error.signal;
        diagnostics.catalog(observation,503,detail);
        if(!res.destroyed){res.writeHead(503,headers);res.end(JSON.stringify({error:'Recovery catalog unavailable',diagnostic:detail}))}
      }
      finally{clearTimeout(timer)}
      return
    }
    if (req.url === '/__harness/environment' || req.url === '/__harness/banner.js') {
      if (req.method !== 'GET') { res.writeHead(405); res.end(); return }
      if (req.headers['sec-fetch-site'] === 'cross-site' || (req.url.endsWith('/environment') && req.headers['x-harness-local'] !== '1')) { res.writeHead(403); res.end(); return }
      const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'content-type': req.url.endsWith('.js') ? 'application/javascript; charset=utf-8' : 'application/json' }
      if (req.url.endsWith('.js')) { res.writeHead(200, headers); res.end(ENVIRONMENT_BANNER); return }
      let timer
      try {
        const value = await Promise.race([environmentReader(), new Promise((_resolve, reject) => { timer = setTimeout(() => reject(Error('Status deadline')), 10500) })])
        if (!res.destroyed) { res.writeHead(200, headers); res.end(JSON.stringify(value)) }
      } catch { if (!res.destroyed) { res.writeHead(503, headers); res.end('{"error":"VM status unavailable"}') } }
      finally { clearTimeout(timer) }
      return
    }
    if (req.url === '/__harness/diagnostics' || req.url === '/__harness/health') {
      if (req.method !== 'GET') { res.writeHead(405); res.end(); return }
      const json = req.url.endsWith('/diagnostics')
      res.writeHead(200, { 'content-type': json ? 'application/json' : 'text/html; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      res.end(json ? JSON.stringify(diagnostics.snapshot()) : HEALTH_HTML)
      return
    }
    forward(req, res)
  })
  server.on('upgrade', (req, socket, head) => {
    const reject = status => { if (!socket.destroyed && !socket.writableEnded) socket.end('HTTP/1.1 ' + status + '\r\nConnection: close\r\n\r\n') }
    if (req.headers.host !== '127.0.0.1:' + server.address().port || !req.url.startsWith('/') || req.url.startsWith('//')) {
      reject('400 Bad Request'); return
    }
    if (req.headers.origin !== undefined && req.headers.origin !== entryOrigin()) { reject('403 Forbidden'); return }
    const upstream = http.request({ host: '127.0.0.1', port: upstreamPort, path: req.url, method: req.method, headers: upstreamHeaders(req), agent })
    const timer = setTimeout(() => { upstream.destroy(new Error('Upgrade response deadline')); reject('502 Bad Gateway') }, responseTimeoutMs)
    upstream.once('close', () => clearTimeout(timer))
    upstream.on('upgrade', (response, peer, received) => {
      clearTimeout(timer)
      if (socket.destroyed || socket.writableEnded) { peer.destroy(); return }
      sockets.add(peer)
      diagnostics.stream('websocket', peer)
      peer.on('close', () => sockets.delete(peer))
      const lines = []
      for (let i = 0; i < response.rawHeaders.length; i += 2) lines.push(response.rawHeaders[i] + ': ' + response.rawHeaders[i + 1])
      socket.write('HTTP/1.1 101 Switching Protocols\r\n' + lines.join('\r\n') + '\r\n\r\n')
      if (received.length) socket.write(received)
      if (head.length) peer.write(head)
      peer.on('error', () => socket.destroy()); socket.on('error', () => peer.destroy())
      peer.on('close', () => socket.destroy()); socket.on('close', () => peer.destroy())
      peer.pipe(socket); socket.pipe(peer)
    })
    upstream.on('response', response => { clearTimeout(timer); response.resume(); diagnostics.streamFailure('websocket'); reject('502 Bad Gateway') })
    upstream.on('error', () => { clearTimeout(timer); diagnostics.streamFailure('websocket'); reject('502 Bad Gateway') })
    socket.once('close', () => upstream.destroy())
    socket.on('error', () => upstream.destroy())
    upstream.end()
  })
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)) })
  server.shutdown = () => {
    storageMonitor.stop();agent.destroy()
    for (const socket of sockets) socket.destroy()
    server.close()
  }
  return server
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const storageMonitor=createStorageMonitor();const server = createWebEntry({storageMonitor})
  server.once('listening',()=>storageMonitor.start());server.once('close',()=>storageMonitor.stop())
  const stopClock=createClockMonitor({observe:value=>{if(value.state==='adjusted'||value.state==='unavailable')console.log('VM clock maintenance:',JSON.stringify(value))}})
  server.on('error', error => { console.error('Local web entry stopped:', error.code || 'unknown'); process.exitCode = 1 })
  server.listen({ host: '127.0.0.1', port: 49226, backlog: 128 })
  for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {stopClock();server.shutdown()})
}
