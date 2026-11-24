import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { RedteamStore, dispatch } from '../package/lib/redteam/store-core.js'

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'purge-evidence-'))
  const store = new RedteamStore(root)
  t.after(() => { store.close(); rmSync(root, { recursive: true, force: true }) })
  const { id } = store.openEngagement('synthetic fixture', ['127.0.0.0/8'])
  return { store, id, db: store.db(id) }
}
const SECRET = 'SYNTHETIC_SECRET_9e44'

test('credential listings omit raw secrets even with caller includeSecrets flag', (t) => {
  const { store, id } = fixture(t)
  store.addCredential(id, { host: '127.0.0.1', username: 'fixture', secret_value: SECRET,
    note: 'Authorization: Bearer ' + SECRET })
  for (const result of [store.listCredentials(id, { includeSecrets: true }), dispatch(store, { op: 'credentials', engagement: id })]) {
    assert.equal(JSON.stringify(result).includes(SECRET), false)
  }
  const row = store.listCredentials(id)[0]
  assert.equal(row.has_secret, true)
  assert.equal(row.secret_masked, '••••••••')
  assert.equal(Object.hasOwn(row, 'secret_value'), false)
})

test('explicit single credential reveal is engagement bound and read-only', (t) => {
  const { store, id } = fixture(t)
  const credential = store.addCredential(id, { host: '127.0.0.1', secret_value: SECRET })
  const result = dispatch(store, { op: 'credentialReveal', engagement: id, id: credential.id })
  assert.equal(result.ok, true)
  assert.equal(result.item.secret_value, SECRET)
  assert.equal(dispatch(store, { op: 'credentialReveal', engagement: id, id: -1 }).ok, false)
  assert.equal(dispatch(store, { op: 'credentialReveal', engagement: id, id: 'all' }).ok, false)
  assert.equal(dispatch(store, { op: 'credentialReveal', engagement: 'missing', id: credential.id }).ok, false)
})

test('reports redact registered secrets, request headers and secret URL parameters', (t) => {
  const { store, id, db } = fixture(t)
  db.prepare('INSERT INTO asset(id,ip,segment_cidr) VALUES(1,?,?)').run('127.0.0.1', '127.0.0.0/8')
  store.addCredential(id, { asset_id: 1, host: '127.0.0.1', secret_value: SECRET })
  const vuln = store.addVuln(id, { asset_id: 1, title: 'synthetic fixture', severity: 'high', status: 'confirmed', target: 'http://127.0.0.1/?token=QUERY_SECRET', evidence: 'Password ' + SECRET })
  store.addHttpEvidence(id, { asset_id: 1, vuln_id: vuln.id, url: 'http://127.0.0.1/?token=QUERY_SECRET',
    method: 'GET', request: 'GET /?token=QUERY_SECRET HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer HEADER_SECRET\r\nCookie: sid=COOKIE_SECRET\r\n\r\n', response: 'Set-Cookie: sid=RESPONSE_SECRET\r\n' + SECRET })
  const point = db.prepare('SELECT id FROM score_point WHERE code = ?').get('web-app')
  store.addScoreHit(id, { point_id: point.id, asset_id: 1, vuln_id: vuln.id, target: 'http://127.0.0.1/?token=QUERY_SECRET', evidence: SECRET })
  const result = store.scoreReport(id)
  const text = JSON.stringify(result)
  for (const value of [SECRET, 'QUERY_SECRET', 'HEADER_SECRET', 'COOKIE_SECRET', 'RESPONSE_SECRET']) {
    assert.equal(text.includes(value), false, value)
  }
  assert.ok(result.items.length > 0)
  assert.ok(result.markdown.includes('[REDACTED]'))
})

test('vulnerability pagination is complete and stable for 201 records', (t) => {
  const { store, id, db } = fixture(t)
  const insert = db.prepare('INSERT INTO vuln(title,severity,status) VALUES(?,?,?)')
  for (let i = 0; i < 201; i++) insert.run('fixture-' + i, 'high', 'candidate')
  const first = store.listVulns(id, { limit: 200, offset: 0 })
  const second = store.listVulns(id, { limit: 200, offset: first.next_offset })
  assert.equal(first.total, 201)
  assert.equal(first.next_offset, 200)
  assert.equal(second.next_offset, null)
  assert.equal(new Set([...first.items, ...second.items].map(x => x.id)).size, 201)
  assert.equal(store.listVulns(id, { offset: -1 }).items[0].id, first.items[0].id)
})
