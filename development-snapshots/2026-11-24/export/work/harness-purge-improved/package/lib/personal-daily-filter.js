import {professionalToolNames} from './personal-daily.js';
export const inject=['tools'];
export function apply(ctx) {
 let signature,release,disposed=false;
 const sync=()=>{
  if(disposed)return;
  const deny=professionalToolNames(ctx.root.tools.schemas());
  const key=deny.join('\n');if(signature===key)return;
  const previous=release;signature=key;
  // Both visibility and dispatch use the native scope restriction. No schema-only shim.
  const next=deny.length?ctx.tools.restrict({deny}):undefined;
  release=next;previous?.();
 };
 ctx.on('tools/change',sync);
 ctx.effect(()=>()=>{disposed=true;release?.()},'personal-daily.tool-filter');
 sync();
}
