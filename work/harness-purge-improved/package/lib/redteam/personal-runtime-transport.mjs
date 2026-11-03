import {spawn as nodeSpawn} from 'node:child_process';
import {Duplex} from 'node:stream';
import {Agent} from 'node:http';
// This program receives only a controller-generated HTTP request. Its sole TCP
// destination is the original container's loopback, never the VM's network.
export const EXEC_HTTP_RELAY=`import sys,socket,signal,time
signal.alarm(6)
raw=b''
while not raw.endswith(b'\\r\\n\\r\\n'):
 line=sys.stdin.buffer.readline(32769-len(raw))
 if not line or len(raw)+len(line)>32768: raise SystemExit(2)
 raw+=line
lengths=[line.split(b':',1)[1].strip() for line in raw.split(b'\\r\\n')[1:] if line.lower().startswith(b'content-length:')]
if len(lengths)!=1 or not lengths[0].isdigit() or int(lengths[0])>65536:raise SystemExit(2)
length=int(lengths[0]);body=sys.stdin.buffer.read(length)
if len(body)!=length:raise SystemExit(2)
with socket.create_connection(('127.0.0.1',8080),timeout=2) as s:
 s.sendall(raw+body);size=0;deadline=time.monotonic()+4
 while time.monotonic()<deadline:
  data=s.recv(65536)
  if not data:break
  size+=len(data)
  if size>8421376:raise SystemExit(2)
  sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
`;
const clients=new Map();
export async function closeRuntimeExecClients(id){const items=[...(clients.get(id)??[])];for(const item of items)item.stream.destroy();let timer;try{await Promise.race([Promise.all(items.map(i=>i.closed)),new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('应用通道子进程清理未确认')),10000))])}finally{clearTimeout(timer)}}
export const runtimeExecClientCount=id=>clients.get(id)?.size??0;
export function createRuntimeExecSocket(containerId,{spawn=nodeSpawn,timeoutMs=6500}={}){
 if(!/^[a-f0-9]{64}$/.test(containerId??''))throw Error('运行容器编号无效');
 const set=clients.get(containerId)??new Set();if(set.size>=16)throw Error('应用通道并发已满');clients.set(containerId,set);
 const child=spawn('/usr/bin/sudo',['-n','/usr/bin/timeout','--signal=TERM','--kill-after=1','7','/usr/bin/docker','exec','-i','--user','1000:1000',containerId,'/usr/bin/python3','-I','-S','-B','-c',EXEC_HTTP_RELAY],{env:{PATH:'/usr/bin:/bin',HOME:'/home/purge'},stdio:['pipe','pipe','ignore']});
 const stream=Duplex.from({readable:child.stdout,writable:child.stdin});let idle,killer,closed;const item={stream,closed:new Promise(resolve=>closed=resolve)};set.add(item);const kill=signal=>{try{child.kill(signal)}catch{}};child.once('close',()=>{clearTimeout(killer);set.delete(item);if(!set.size)clients.delete(containerId);closed()});
 const deadline=setTimeout(()=>stream.destroy(Error('应用通道超时')),timeoutMs);
 stream.setNoDelay=()=>stream;stream.setKeepAlive=()=>stream;stream.setTimeout=(ms,callback)=>{clearTimeout(idle);if(callback)stream.once('timeout',callback);if(ms)idle=setTimeout(()=>stream.emit('timeout'),ms);return stream};
 stream.once('close',()=>{clearTimeout(deadline);clearTimeout(idle);kill('SIGTERM');killer=setTimeout(()=>kill('SIGKILL'),500)});child.once('error',()=>stream.destroy(Error('应用通道不可用')));child.once('exit',code=>{if(code&& !stream.destroyed)stream.destroy(Error('应用通道未完成'))});return stream;
}
export function runtimeHttpOptions({host,port=8080,connect}={}){
 if(!connect)return{host,port,agent:false};
 const agent=new Agent({keepAlive:false,maxSockets:1});agent.createConnection=(_options,callback)=>{try{callback(null,connect())}catch(e){callback(e)}};return{host:'runtime.invalid',port:8080,agent};
}
