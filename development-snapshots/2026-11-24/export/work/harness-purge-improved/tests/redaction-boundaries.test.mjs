import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { redactDisplay, redactText, SECRET_KEY } from '../package/lib/redteam/personal-evidence-redaction.mjs'
import { sanitizeReviewText } from '../package/lib/redteam/personal-review-snapshot.mjs'
import { readReviewSource } from '../package/lib/redteam/personal-security-review.mjs'
import { RedteamStore } from '../package/lib/redteam/store-core.js'
import { SecurityWorkbench } from '../package/lib/redteam/personal-security-workbench.mjs'

const names = ['SECRET_KEY', 'DJANGO_SECRET_KEY', 'GITHUB_TOKEN', 'DB_PASSWORD', 'clientSecret', 'private_key', 'privateKey', 'APIKey', 'proxy-authorization']
const ordinary = { monkey: 'unchanged', tokenizer: 'unchanged', public_key: 'unchanged', token_count: 17, password_length: 12, has_secret: true }

test('unregistered sensitive names are masked consistently in structured display and JSON copies', () => {
  const data = { ...ordinary, ...Object.fromEntries(names.map(key => [key, 'SYNTHETIC_VALUE'])) }
  for (const safe of [redactDisplay(data), JSON.parse(sanitizeReviewText(JSON.stringify(data), 'config.json'))]) {
    for (const name of names) assert.equal(safe[name], '[REDACTED]', name)
    for (const [key, value] of Object.entries(ordinary)) assert.equal(safe[key], value, key)
  }
})

test('text masks prefixed credentials and nested assignments without matching ordinary words', () => {
  const input = names.map(key => key + '="SYNTHETIC_' + key.replace(/[^a-z]/gi, '') + '"').join('\n')
  assert.ok(!redactText(input).includes('SYNTHETIC_'))
  assert.ok(!redactText('message="password=INNER_SYNTHETIC"').includes('INNER_SYNTHETIC'))
  assert.equal(redactText('monkey=unchanged tokenizer=unchanged public_key=unchanged token_count=17 password_length=12'),
    'monkey=unchanged tokenizer=unchanged public_key=unchanged token_count=17 password_length=12')
})

test('boolean credential status stays readable while registered values are removed from source paths', () => {
  assert.ok(SECRET_KEY instanceof RegExp)
  assert.equal(SECRET_KEY.test('proxy-authorization'), true)
  assert.equal(redactDisplay({has_secret: true}).has_secret, true)
  assert.ok(!redactText('ordinary="SYNTHETIC_REGISTERED"', ['SYNTHETIC_REGISTERED']).includes('SYNTHETIC_REGISTERED'))
})

test('JavaScript comparisons and embedded request text preserve syntax', () => {
  const comparison = 'export function same(token, expectedToken) { return token === expectedToken; }\n'
  assert.equal(sanitizeReviewText(comparison, 'auth.js'), comparison)
  const safe = sanitizeReviewText('const message = "password=SYNTHETIC_EMBEDDED";\n', 'auth.js')
  assert.ok(!safe.includes('SYNTHETIC_EMBEDDED'))
  assert.doesNotThrow(() => new Function(safe))
})

test('complex sensitive JavaScript expressions and typed assignments fail closed', () => {
  for (const source of [
    "const password = process.env.PASSWORD || 'SYNTHETIC_FALLBACK';\n",
    "const password = 'SYNTHETIC_FIRST' + 'SYNTHETIC_SECOND';\n",
    "const password = process.env['PASSWORD'] || 'SYNTHETIC_FALLBACK';\n",
    "const password = 'SYNTHETIC_FIRST'\n + 'SYNTHETIC_SECOND';\n",
  ]) assert.throws(() => sanitizeReviewText(source, 'auth.js'), /JavaScript/)
  assert.throws(() => sanitizeReviewText("const GITHUB_TOKEN: string = 'SYNTHETIC_TYPED';\n", 'auth.ts'), /JavaScript/)
})

test('Python environment subscript identifiers remain intact after source sanitization', () => {
  const source = "GITHUB_TOKEN = os.environ['GITHUB_TOKEN']\ncfg['password'] = os.environ['DB_PASSWORD']\n"
  assert.equal(sanitizeReviewText(source, 'config.py'), source)
})

const python = [
  "SECRET_KEY = 'SYNTHETIC_NAME'",
  "GITHUB_TOKEN: str = 'SYNTHETIC_ANNOTATION'",
  "settings.privateKey = b'SYNTHETIC_ATTRIBUTE'",
  "cfg['password'] = 'SYNTHETIC_SUBSCRIPT'",
  "user, password = 'ordinary-user', 'SYNTHETIC_TUPLE'",
  "[normal, [clientSecret]] = ['unchanged', ['SYNTHETIC_NESTED']]",
  "if (apiKey := 'SYNTHETIC_NAMED'): pass",
  "def connect(db_password='SYNTHETIC_DEFAULT', *, githubToken='SYNTHETIC_KEYWORD'): pass",
  "config = {'SECRET_KEY': 'SYNTHETIC_DICT'}",
  "tokenizer = 'unchanged'",
  "secret = os.getenv('SECRET_KEY')",
  '',
].join('\n')

test('Python source masks assignments structurally while preserving field names and ordinary values', () => {
  const safe = sanitizeReviewText(python, 'config.py')
  assert.ok(!safe.includes('SYNTHETIC_'))
  for (const text of ["cfg['password']", "'ordinary-user'", "'unchanged'", "'SECRET_KEY'", "os.getenv('SECRET_KEY')"]) assert.ok(safe.includes(text), text)
})

test('ambiguous Python unpacking into sensitive targets refuses copying rather than leaking', () => {
  for (const source of ["user, password = load('SYNTHETIC_SOURCE')\n", "user, *password = ['ok', 'SYNTHETIC_STAR']\n"]) {
    assert.throws(() => sanitizeReviewText(source, 'app.py'), /Python/)
  }
})

test('source read and actual workbench source redact before pagination, without changing project bytes', async t => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'source-redaction-')))
  const workspace = path.join(root, 'workspace'), repo = path.join(workspace, 'repo')
  fs.mkdirSync(repo, { recursive: true })
  const store = new RedteamStore(path.join(root, 'facts'))
  const bench = new SecurityWorkbench(store, { workspaceRoot: workspace, toolStatus: () => ({}) })
  t.after(async () => { await bench.dispose(); store.close(); fs.rmSync(root, { recursive: true, force: true }) })
  store.openEngagement('A')
  const file = path.join(repo, 'settings.py')
  fs.writeFileSync(file, python)
  const profile = bench.saveScope('a', { requestId: 'scope-redaction-1', revision: 0,
    repoRoot: repo, tools: ['semgrep'], expiresAt: new Date(Date.now() + 3600000).toISOString(), confirm: true })
  for (const read of [input => readReviewSource(profile, input), input => bench.source('a', input)]) {
    let offset = 0, combined = ''
    for (let n = 0; n < 20; n++) {
      const page = read({ path: 'settings.py', offset, maxBytes: 256 })
      assert.ok(!page.text.includes('SYNTHETIC_'))
      combined += page.text
      offset = page.nextOffset
      if (page.complete) break
    }
    assert.ok(combined.includes('[REDACTED]'))
    assert.ok(combined.includes('tokenizer'))
  }
  assert.equal(fs.readFileSync(file, 'utf8'), python)
})
