#!/usr/bin/env python3
"""Loopback VM proxy: exact public origins and one pinned-identity Kali SSH route."""
import http.server,ipaddress,select,socket,socketserver,threading,time,urllib.parse
ALLOWED=frozenset({'nodejs.org','registry.npmjs.org','github.com','codeload.github.com','raw.githubusercontent.com','objects.githubusercontent.com','release-assets.githubusercontent.com','api.deepseek.com','ports.ubuntu.com','archive.ubuntu.com','security.ubuntu.com','auth.docker.io','registry-1.docker.io','production.cloudfront.docker.com'})
PORTS=frozenset({80,443})
BIND=('127.0.0.1',49222)
MAX_CONNECTIONS=16
MAX_BYTES=256*1024*1024
MAX_SECONDS=600
IDLE_SECONDS=60
HEADER_SECONDS=10
KALI_HOST='kali.harness.internal'
# Host-reviewed IP/MAC pin for the dedicated Kali VM. SSH verifies its pinned
# host key before client authentication. Revalidate this value if DHCP changes;
# never discover other LAN addresses or spawn children in this bounded proxy.
KALI_IPV4='192.168.64.7'

def connect_tunnel(host,port):
    if host!=KALI_HOST or port!=443:return connect_public(host,port)
    address=KALI_IPV4;upstream=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:upstream.settimeout(5);upstream.connect((address,22));return upstream
    except BaseException:upstream.close();raise

def validate_authority(host,port):
    if not isinstance(host,str) or host.lower() not in ALLOWED or port not in PORTS:raise ValueError('Origin outside VM egress allowlist')
    return host.lower(),port

def public_addresses(host,port):
    host,port=validate_authority(host,port)
    entries=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    if not entries:raise ValueError('No public address')
    for family,kind,proto,canon,addr in entries:
        ip=ipaddress.ip_address(addr[0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_unspecified:raise ValueError('Non-public destination denied')
    return entries

def connect_public(host,port):
    entries=public_addresses(host,port)
    for family,kind,proto,canon,addr in entries:
        s=socket.socket(family,kind,proto)
        try:s.settimeout(15);s.connect(addr);return s
        except OSError:s.close()
    raise OSError('Public origin unavailable')

def relay(left,right,read_only=False):
    start=last=time.monotonic();count=0
    # Blocking sends have a deadline; no unbounded user-controlled queues.
    for s in (left,right):s.settimeout(15)
    while time.monotonic()-start<MAX_SECONDS and time.monotonic()-last<IDLE_SECONDS and count<MAX_BYTES:
        ready,_,_=select.select([right] if read_only else [left,right],[],[],1)
        for source in ready:
            data=source.recv(65536)
            if not data:return {'reason':'peer-eof','bytes':count,'seconds':round(time.monotonic()-start,2)}
            (right if source is left else left).sendall(data)
            count+=len(data);last=time.monotonic()
    return {'reason':'byte-limit' if count>=MAX_BYTES else 'time-limit','bytes':count,'seconds':round(time.monotonic()-start,2)}

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    server_version='DedicatedVMProxy'
    sys_version=''
    def setup(self):
        self.request.settimeout(15);super().setup()
        def expire():
            try:self.request.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.header_timer=threading.Timer(HEADER_SECONDS,expire);self.header_timer.daemon=True;self.header_timer.start()
    def finish(self):
        self.header_timer.cancel();super().finish()
    def log_message(self,*a):pass # Never log headers, keys, URLs, or tunneled data.
    def do_CONNECT(self):
        self.header_timer.cancel()
        upstream=None
        try:
            target=urllib.parse.urlsplit('//'+self.path)
            if target.username or target.password or target.path or target.query or target.fragment or target.port!=443:raise ValueError('CONNECT443 only')
            upstream=connect_tunnel(target.hostname,target.port)
            self.send_response(200,'Connection established');self.end_headers();self.wfile.flush()
            relay(self.connection,upstream)
        except (ValueError,TypeError):self.send_error(403,'Destination not permitted')
        except (OSError,TimeoutError):
            if upstream is None:self.send_error(502,'Origin unavailable')
        finally:
            if upstream is not None:upstream.close()
            self.close_connection=True
    def do_GET(self):self.forward()
    def do_HEAD(self):self.forward()
    def forward(self):
        self.header_timer.cancel()
        upstream=None
        try:
            u=urllib.parse.urlsplit(self.path)
            if u.scheme!='http' or u.username or u.password or u.fragment or (u.port or 80)!=80:raise ValueError('Absolute HTTP80 URL required')
            if self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length','0'))!=0:raise ValueError('HTTP request bodies disabled')
            host,port=validate_authority(u.hostname,u.port or 80);upstream=connect_public(host,port)
            target=urllib.parse.urlunsplit(('','',u.path or '/',u.query,''))
            lines=[f'{self.command} {target} HTTP/1.0',f'Host: {host}','Connection: close']
            # Only install metadata headers; no proxy or client authorization leaks.
            for key in ['User-Agent','Accept','Accept-Encoding','Range','If-Modified-Since']:
                value=self.headers.get(key)
                if value and '\r' not in value and '\n' not in value:lines.append(key+': '+value)
            upstream.sendall(('\r\n'.join(lines)+'\r\n\r\n').encode('ascii'))
            relay(self.connection,upstream,read_only=True)
        except (ValueError,TypeError,UnicodeError):self.send_error(403,'Destination not permitted')
        except (OSError,TimeoutError):
            if upstream is None:self.send_error(502,'Origin unavailable')
        finally:
            if upstream is not None:upstream.close()
            self.close_connection=True

class Server(socketserver.ThreadingMixIn,http.server.HTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    request_queue_size=16
    def __init__(self,*a,**kw):self.slots=threading.BoundedSemaphore(MAX_CONNECTIONS);super().__init__(*a,**kw)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):request.close();return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,*a):
        try:super().process_request_thread(*a)
        finally:self.slots.release()

if __name__=='__main__':
    with Server(BIND,Handler) as server:server.serve_forever()
