// Reuse the official cookie validation and Host/Origin fence. Never parse,
// copy or trust a browser-supplied identity/token in the plugin itself.
export function authorizeOwnerRequest(ctx, request, response) {
  let admission;
  try {
    const connection=typeof ctx.get==='function' ? ctx.get('connection') : ctx.connection;
    admission=connection?.admit?.(request);
    if (admission?.peer?.principal?.kind==='owner') return true;
  } catch { /* unavailable authentication fails closed */ }
  const status=admission?.rejection===403 ? 403 : 401;
  response.writeHead(status,{'cache-control':'no-store','content-type':'application/json; charset=utf-8'});
  response.end(JSON.stringify({ok:false,error:status===403?'forbidden':'Harness owner session required'}));
  return false;
}

export function authenticatedWebServer(ctx, server) {
  return { register(spec,label) {
    return server.register({...spec,handler:async(request,response)=>{
      if (!authorizeOwnerRequest(ctx,request,response)) return;
      return spec.handler(request,response);
    }},label);
  }};
}
