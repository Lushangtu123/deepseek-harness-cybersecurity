/** VM-only daily composition. The native standard and existing sessions stay intact. */
export function dailyDefinition(standard) {
 if(!standard||!Array.isArray(standard.plugins))throw new Error('Native standard preset is unavailable');
 const plugins=structuredClone(standard.plugins);
 const persona=plugins.find(row=>row.id==='persona');
 if(persona)persona.config={...persona.config,suffix:[persona.config?.suffix,'当前为日常精简工具模式。终端、文件、技能、浏览器和 CodeGraph 保留。REA 与演练工具在完整 Standard/红队模式可用；需要这些原生工具时，请在新会话选择对应模式。现有 CLI 仍可按任务使用。'].filter(Boolean).join('\n')};
 plugins.push({id:'personal-daily-tool-filter',name:'dsh-purge/personal-daily-filter'});
 return {id:'personal-daily',name:'日常精简',description:'保留常用工具；完整 REA 与演练工具请在新会话选择 Standard 或红队模式',order:0,plugins};
}
export function professionalToolNames(schemas) {
 return schemas.map(tool=>tool.name).filter(name=>name.startsWith('mcp__rea__')||name.startsWith('redteam_')).sort();
}
export const inject=['agentPresets','tools'];
export async function apply(ctx) {
 if(process.env.DSH_HOME!=='/home/purge/.dsh-improved'||process.platform!=='linux')throw new Error('Daily preset is limited to the improved VM');
 // The boot carrier is not projected into the plugin namespace; use this VM's
 // pinned installation, the same anchor that owns the running launcher.
 const {loadProfileDirectory,loadOverlayPatches,composeEntries}=await import('file:///home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js');
 const profile=loadProfileDirectory('personal-daily','/home/purge/.dsh-improved/profiles/web','/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json');
 const rows=composeEntries([...profile.layers.map(layer=>layer.patches),profile.patches,loadOverlayPatches('personal-daily','/home/purge/.dsh-improved/cordis.patch.yml')]);
 const standard=rows.find(row=>row.id==='preset-standard')?.config;
 const dispose=await ctx.agentPresets.register(dailyDefinition(standard));
 ctx.effect(()=>dispose,'personal-daily.preset');
}
