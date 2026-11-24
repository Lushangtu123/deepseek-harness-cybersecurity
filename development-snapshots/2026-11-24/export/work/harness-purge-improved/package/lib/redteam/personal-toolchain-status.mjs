import { homedir } from 'node:os';

// Called only behind the existing authenticated, same-origin JSON API.
export async function handleToolchainOp(request, { signal, runtime = {
  platform: process.platform, home: homedir(), dshHome: process.env.DSH_HOME
}, loadRunner = () => import('/home/purge/.dsh-improved/tooling/toolchain-version-checker/process.mjs') } = {}) {
  if (request?.op !== 'toolchainVersions') return undefined;
  if (runtime.platform !== 'linux' || runtime.home !== '/home/purge' || runtime.dshHome !== '/home/purge/.dsh-improved') {
    return { ok: false, error: '工具版本检查仅在专用 VM 改进版中可用。' };
  }
  const project = request.project ?? 'all';
  if (!['all', 'rea', 'reverse-skill', 'pentagi'].includes(project) || Object.keys(request).some(key => !['op', 'project'].includes(key))) {
    return { ok: false, error: '仅支持固定项目 all、rea、reverse-skill、pentagi。' };
  }
  try {
    const { runJson } = await loadRunner();
    const report = await runJson('/usr/bin/python3', [
      '/home/purge/.dsh-improved/tooling/toolchain-version-checker/check_versions.py',
      '--project', project, '--json'
    ], { signal, timeoutMs: 25000 });
    return { ok: true, report };
  } catch {
    return { ok: false, error: signal?.aborted ? '版本查询已取消。' : '版本查询未完成。请检查 VM 的 GitHub 连接及检查器安装后重试。' };
  }
}
