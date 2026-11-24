import { homedir } from 'node:os';

// The launcher selects an isolated copy of the retained, already-patched
// original runtime. A plugin setting alone cannot enable these hooks.
export function originalCapabilitiesEnabled(runtime = {
  platform: process.platform, home: homedir(), env: process.env,
}) {
  return runtime.platform === 'linux' && runtime.home === '/home/purge'
    && runtime.env?.DSH_HOME === '/home/purge/.dsh-improved'
    && runtime.env?.DSH_BASE === '/home/purge/tools/harness-original-capabilities/node_modules/@deepseek-ai'
    && runtime.env?.DSH_PERSONAL_ORIGINAL === 'enabled';
}

export function installOriginalCapabilities(ctx, config, operations, runtime) {
  if (!originalCapabilitiesEnabled(runtime)) return false;
  for (const name of ['identity', 'region', 'freshPermissions', 'rewind', 'cwd', 'mnemon', 'prompts', 'retry']) {
    operations[name](ctx, config);
  }
  return true;
}
