/** Declare the packaged redteam composition without running the upstream installer. */
import {fileURLToPath} from 'node:url';
import {readPresetDefinition} from './redteam/preset-composition.js';

export function redteamDefinition() {
 return readPresetDefinition('redteam',fileURLToPath(new URL('../presets/redteam/',import.meta.url)));
}
export const inject=['agentPresets'];
export async function apply(ctx) {
 if(process.platform!=='linux'||process.env.DSH_HOME!=='/home/purge/.dsh-improved')throw new Error('Redteam declaration is limited to the improved VM');
 const dispose=await ctx.agentPresets.register(redteamDefinition());
 ctx.effect(()=>dispose,'personal-redteam.preset');
}
