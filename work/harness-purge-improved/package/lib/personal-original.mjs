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
    // The legacy gate guesses network destinations from arbitrary text. Python
    // attributes, Docker templates and read-only references are not endpoints.
    // Keep it opt-in; personal/session controls, managed scope guards and VM
    // egress isolation remain the execution authority in the personal VM.
    if (name === 'region' && config?.legacyRegionGate !== true) continue;
    operations[name](ctx, config);
  }
  return true;
}
