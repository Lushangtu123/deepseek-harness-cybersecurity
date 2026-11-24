// Shared with the fixed Python AST parser. Match credential names, not metadata
// such as token_count, password_length, public_key or tokenizer.
export const SENSITIVE_KEY_PATTERN = '^(?:(?:[a-z0-9]+_)*(?:password|passwd|secret|secret_key|secret_value|token|api_key|apikey|private_key|pass_key)|authorization|proxy_authorization|cookie|set_cookie)$'
export function normalizeSensitiveKey(key) {
  return String(key).replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/-/g, '_').toLowerCase()
}
const sensitiveKey = new RegExp(SENSITIVE_KEY_PATTERN, 'i')
export const isSensitiveKey = key => sensitiveKey.test(normalizeSensitiveKey(key))
// Preserve the original RegExp export for consumers; new internal paths use
// normalization explicitly rather than changing this public object's type.
export const SECRET_KEY = /^(?:secret(?:_value)?|pass_key|password|passwd|access_token|refresh_token|api_key|apikey|authorization|proxy-authorization|cookie|set-cookie)$/i
const ASSIGNMENT_START = /(?<![\w$-])(["']?)([A-Za-z_][A-Za-z0-9_-]*)\1\s*(?::|=(?![=>]))\s*/g
const ASSIGNMENT_VALUE = /^(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}"'&]+)/
function redactAssignments(text, javascript) {
  let result = '', end = 0
  // Do not consume a non-sensitive outer string: it can contain a credential
  // assignment of its own (for example a logged request body).
  for (const match of text.matchAll(ASSIGNMENT_START)) {
    if (match.index < end || !isSensitiveKey(match[2])) continue
    const start = match.index + match[0].length
    const value = ASSIGNMENT_VALUE.exec(text.slice(start))
    if (!value) continue
    let replacement = '[REDACTED]'
    if (javascript) {
      const tail = headerSpaceEnd(text, start + value[0].length)
      const quoted = /^["']/.test(value[0])
      const embedded = !quoted && /^["']/.test(text.slice(tail))
      // This is deliberately bounded, not a JavaScript expression parser. A
      // fallback, concatenation, call, type annotation or computed value needs
      // structural support before it can be copied without retaining a tail.
      if ((!quoted && !/^(?:[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*|\d+|\[REDACTED\])$/.test(value[0]))
          || tail < text.length && !/[,;})\]]/.test(text[tail]) && !embedded) {
        throw Error('JavaScript复杂敏感值不能安全脱敏')
      }
      if (!embedded) replacement = '"[REDACTED]"'
    }
    result += text.slice(end, start) + replacement
    end = start + value[0].length
  }
  return result + text.slice(end)
}
const HEADER_START = /(?<![\w$-])(["']?)(?:authorization|proxy-authorization|cookie|set-cookie)\1\s*:\s*/gi
const HEADER_LITERAL = /^(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\$]|\$(?!\{)|\$\{\s*[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*\})*`)/
const HEADER_IDENTIFIER = /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*/
function headerSpaceEnd(text, start) {
  let at = start
  while (at < text.length) {
    if (/\s/.test(text[at])) { at++; continue }
    if (text.startsWith('//',at)) { const next=text.slice(at+2).search(/[\r\n\u2028\u2029]/); at=next<0?text.length:at+2+next+1; continue }
    if (text.startsWith('/*',at)) { const end=text.indexOf('*/',at+2); if(end<0)throw Error('JavaScript认证值边界不明确');at=end+2;continue }
    break
  }
  return at
}
function headerValueLength(text,start) {
  const literal=HEADER_LITERAL.exec(text.slice(start))
  if(!literal)throw Error('JavaScript复杂认证模板不能安全脱敏')
  let end=start+literal[0].length
  while(true){
    const at=headerSpaceEnd(text,end)
    if(text[at]==='+'){
      const operandStart=headerSpaceEnd(text,at+1),operand=HEADER_IDENTIFIER.exec(text.slice(operandStart))
      if(!operand)throw Error('JavaScript复杂认证值不能安全脱敏')
      end=operandStart+operand[0].length;continue
    }
    if(at<text.length&&!/[,};]/.test(text[at]))throw Error('JavaScript复杂认证值不能安全脱敏')
    return end-start
  }
}
function redactHeaders(text, javascript) {
  let result = '', end = 0
  for (const match of text.matchAll(HEADER_START)) {
    if (match.index < end) continue
    const start = match.index + match[0].length, rest = text.slice(start)
    const length=javascript?headerValueLength(text,start):(rest.search(/[\r\n]/)<0?rest.length:rest.search(/[\r\n]/))
    result += text.slice(end, start) + (javascript ? '"[REDACTED]"' : '[REDACTED]')
    end = start + length
  }
  return result + text.slice(end)
}
export function redactKnownText(value, secrets = []) {
  let text = String(value)
  for (const secret of [...new Set(secrets.filter(s => typeof s === 'string' && s))].sort((a, b) => b.length - a.length)) {
    for (const encoded of new Set([secret, encodeURIComponent(secret)])) text = text.split(encoded).join('[REDACTED]')
  }
  return text
}
export function redactText(value, secrets = [], {javascript=false}={}) {
  return redactAssignments(redactHeaders(redactKnownText(value,secrets),javascript)
    .replace(/([?&](?:token|access_token|refresh_token|api_key|apikey|key|password|secret|signature|sig)=)[^&#\s"'`<>]*/gi, '$1[REDACTED]')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[REDACTED]@')
    .replace(/((?:--user|-u)\s+)(?:'[^']*'|"[^"]*"|[^\s]+)/g, '$1[REDACTED]'),javascript)
}
export function redactDisplay(value, secrets = [], options={}) {
  if (typeof value === 'string') return redactText(value, secrets, options)
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(x => redactDisplay(x, secrets, options))
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    out[key] = isSensitiveKey(key) && item && typeof item !== 'boolean' ? '[REDACTED]' : redactDisplay(item, secrets, options)
  }
  return out
}
