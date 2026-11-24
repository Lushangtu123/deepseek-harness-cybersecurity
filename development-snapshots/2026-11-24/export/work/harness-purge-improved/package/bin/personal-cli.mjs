#!/usr/bin/env node
import fs from 'node:fs';
const pkg=JSON.parse(fs.readFileSync(new URL('../package.json',import.meta.url)));
console.log(JSON.stringify({name:'dsh-purge personal',version:pkg.version,hostPatching:false,automaticElevation:false,upstreamOriginal:'preserved separately',message:'在 Harness 中使用原生审批、证据和演练台；完整原版使用独立原版入口。'},null,2));
if(process.argv.some(x=>['--apply','--revert','--uninstall','--update'].includes(x)))process.exitCode=1;
