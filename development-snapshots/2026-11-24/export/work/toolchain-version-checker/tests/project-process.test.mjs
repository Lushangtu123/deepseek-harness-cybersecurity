import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runJson } from '../process.mjs';
const checker = fileURLToPath(new URL('../check_versions.py', import.meta.url));
const python = process.platform === 'darwin' ? '/opt/homebrew/bin/python3' : '/usr/bin/python3';
const load = `import importlib.util,json,sys\np=${JSON.stringify(checker)}\nspec=importlib.util.spec_from_file_location('versions',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n`;
test('the real process wrapper returns completed projects when a local inspector blocks', async () => {
  const command = load + `m.PROJECT_BUDGET=.4
def command(name,local_only):
 code="import time,json;"+("time.sleep(3);" if name=='rea' else '')+"print(json.dumps({'project':"+repr(name)+",'queryState':'completed','comparison':{'matchesDefaultBranch':True}}))"
 return [sys.executable,'-B','-c',code]
m.worker_command=command
sys.argv=['check_versions.py','--json'];m.main()
`;
  const report = await runJson(python, ['-B', '-c', command], { timeoutMs: 2500 });
  assert.equal(report.projects.length, 3);
  assert.equal(report.projects[0].queryState, 'timeout');
  assert.ok(report.projects.slice(1).every(row => row.comparison.matchesDefaultBranch === true));
});
test('cancellation reaps the coordinator, detached project and its helper', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'versions-project-cancel-'));
  const pidFile = path.join(dir, 'pids');
  const childScript = `import os,subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\nopen(${JSON.stringify(pidFile)},'w').write(str(os.getpid())+' '+str(p.pid))\ntime.sleep(30)`;
  const command = load + `m.PROJECT_BUDGET=20
m.worker_command=lambda name,local_only:[sys.executable,'-B','-c',${JSON.stringify(childScript)}]
sys.argv=['check_versions.py','--project','rea','--json'];m.main()
`;
  const controller = new AbortController();
  const pending = runJson(python, ['-B', '-c', command], { signal: controller.signal });
  const rejected = assert.rejects(pending, /cancelled/);
  try {
    for (let i = 0; i < 150 && !fs.existsSync(pidFile); i++) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(fs.existsSync(pidFile), 'project and helper started');
    const pids = fs.readFileSync(pidFile, 'utf8').trim().split(' ').map(Number);
    controller.abort(); await rejected;
    for (let i = 0; i < 150; i++) {
      if (pids.every(pid => { try { process.kill(pid, 0); return false; } catch { return true; } })) return;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert.fail('a project/helper survived cancellation');
  } finally { controller.abort(); fs.rmSync(dir, { recursive: true, force: true }); }
});
