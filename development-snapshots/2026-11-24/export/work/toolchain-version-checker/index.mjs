import { createRequire } from 'node:module';
import { runJson } from './process.mjs';
const require = createRequire('/home/purge/tools/harness-improved-runtime/node_modules/@deepseek-ai/dsh/package.json');
const { defineTool } = require('@deepseek-ai/dsh-tools');
export const name = 'personal-toolchain-versions';
export const inject = ['tools'];
export function apply(ctx) {
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'toolchain_versions_check',
    description: 'Check installed REA, reverse-skill and PentAGI against their fixed public GitHub repositories. Use when the user asks whether these VM tools are current. Read-only: no fetch, pull, install, container upgrade, credentials or permission changes. Returns JSON with checkedAt and per-project checkedAt, installed metadata, latest formal Release tag/commit, default branch commit, comparison status, queryState and fixed errorCode/unknown reasons. Use project to retry only the requested tool. Each project has an independent 18-second inspection budget; a timed-out project preserves other completed project results. Cooperative query timeouts retain confirmed fields; hard-killed local inspection remains unverified. Release match and development branch match are separate; different commits do not prove an upgrade is needed. Do not describe unverified fields as current. Retry connectivity failures after checking the VM GitHub connection; do not expand network access.',
    parameters: { project: { type: 'string', enum: ['all', 'rea', 'reverse-skill', 'pentagi'], default: 'all',
      description: 'Project to inspect. Omit for all three; no custom URLs or paths are accepted.' } },
    output: { schema: { type: 'object', additionalProperties: false, properties: {
      schemaVersion: { type: 'integer', required: true }, checkedAt: { type: 'string', required: true },
      readOnly: { type: 'boolean', required: true }, automaticUpdates: { type: 'boolean', required: true },
      localOnly: { type: 'boolean', required: true }, projects: { type: 'array', required: true }
    } }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
    timeoutMs: 55000,
    isConcurrencySafe: () => true,
    execute: async (args, exec) => {
      if (Object.keys(args).some(key => key !== 'project')) throw new Error('Only project is accepted; use all, rea, reverse-skill or pentagi.');
      return runJson('/usr/bin/python3', [
        '/home/purge/.dsh-improved/tooling/toolchain-version-checker/check_versions.py',
        '--project', args.project ?? 'all', '--json'
      ], { signal: exec.signal });
    }
  })));
}
