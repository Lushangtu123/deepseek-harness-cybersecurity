import { spawn } from 'node:child_process';

// Internal process primitive; command/arguments are fixed by index.mjs, never model input.
export function runJson(command, args, { signal, timeoutMs = 50000 } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('Version inspection cancelled.'));
    const child = spawn(command, args, { detached: true, cwd: '/tmp',
      env: { PATH: '/usr/bin:/bin', HOME: '/nonexistent', LANG: 'C.UTF-8', PYTHONDONTWRITEBYTECODE: '1' },
      stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '', failure, hardKill;
    const killGroup = sig => {
      if (!child.pid) return;
      try { process.kill(-child.pid, sig); } catch (error) { if (error.code !== 'ESRCH') failure ??= error; }
    };
    const stop = message => {
      if (failure) return;
      failure = new Error(message);
      killGroup('SIGTERM');
      hardKill = setTimeout(() => killGroup('SIGKILL'), 1000);
    };
    const abort = () => stop('Version inspection cancelled.');
    signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(() => stop('Version inspection timed out. Check VM GitHub connectivity and retry.'), timeoutMs);
    const cleanup = () => { clearTimeout(timer); clearTimeout(hardKill); signal?.removeEventListener('abort', abort); };
    child.stdout.on('data', data => {
      if (failure) return;
      output += data.toString('utf8');
      if (Buffer.byteLength(output) > 131072) stop('Version inspection response exceeded its limit.');
    });
    child.on('error', error => { failure ??= new Error('Version checker could not start: ' + error.code); });
    child.on('close', code => {
      cleanup();
      // Always reap any helper still in the process group before settling.
      killGroup('SIGKILL');
      if (failure) return reject(failure);
      if (code !== 0) return reject(new Error('Version checker failed. Inspect the fixed installation metadata and retry.'));
      try { resolve(JSON.parse(output)); }
      catch { reject(new Error('Version checker returned invalid JSON. Inspect its installation.')); }
    });
  });
}
