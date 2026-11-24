const source = name => readFileSync(new URL(`./${name}`, import.meta.url), 'utf8');
function loadI18n({languages = ['en-US'], storage = memoryStorage(), document, console: con = console, zh = true} = {}) {
}
test('all visible homepage text is translatable except language-neutral names', () => {
  const html = source('index.html').replace(/<!--[\s\S]*?-->|<!DOCTYPE[^>]*>/g, '')
  for (const [, close, tag, attrs, textNode] of html.matchAll(/<(\/?)([a-z0-9]+)\b([^>]*)>|([^<]+)/g)) {
    if (textNode !== undefined) {
    }
  }
  assert.doesNotMatch(html, /data-i18n-html=/, 'the workspace writes no dictionary HTML');
});
