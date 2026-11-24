// Synthetic scanner input only; never execute this file.
import * as child_process from 'node:child_process';
import { exec as execute } from 'child_process';
import https from 'https';
import tls from 'tls';
function examples(value: string, element: HTMLElement, db: any) {
  // ruleid: harness.javascript.eval
  eval(value);
  // ok: harness.javascript.eval
  JSON.parse(value);
  // ok: harness.javascript.eval
  eval('1 + 2');
  // ruleid: harness.javascript.child-process-exec
  child_process.exec(value);
  // ruleid: harness.javascript.child-process-exec
  execute(value);
  // ok: harness.javascript.child-process-exec
  child_process.execFile('printf', [value]);
  // ok: harness.javascript.child-process-exec
  child_process.exec('printf hello');
  // ruleid: harness.javascript.dom-innerhtml
  element.innerHTML = value;
  // ok: harness.javascript.dom-innerhtml
  element.textContent = value;
  // ok: harness.javascript.dom-innerhtml
  element.innerHTML = '<p>hello</p>';
  // ruleid: harness.javascript.document-write
  document.write(value);
  // ok: harness.javascript.document-write
  document.write('<p>hello</p>');
  // ruleid: harness.javascript.tls-reject-disabled
  https.request({hostname: value, rejectUnauthorized: false});
  // ruleid: harness.javascript.tls-reject-disabled
  tls.connect({host: value, rejectUnauthorized: false});
  // ruleid: harness.javascript.tls-reject-disabled
  new https.Agent({rejectUnauthorized: false});
  // ok: harness.javascript.tls-reject-disabled
  new https.Agent({rejectUnauthorized: true});
  // ok: harness.javascript.tls-reject-disabled
  https.request({hostname: value, rejectUnauthorized: true});
  // ok: harness.javascript.tls-reject-disabled
  unrelated({rejectUnauthorized: false});
  // ruleid: harness.javascript.sql-concat
  db.query('SELECT * FROM items WHERE name=' + value);
  // ruleid: harness.javascript.sql-concat
  db.query(`SELECT * FROM items WHERE name=${value}`);
  // ok: harness.javascript.sql-concat
  db.query('SELECT * FROM items WHERE name=?', [value]);
  // ok: harness.javascript.sql-concat
  db.query(`SELECT 1`);
}
