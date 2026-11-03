export const SECRET_KEY = /^(?:secret(?:_value)?|pass_key|password|passwd|access_token|refresh_token|api_key|apikey|authorization|proxy-authorization|cookie|set-cookie)$/i
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
  return redactHeaders(redactKnownText(value,secrets),javascript)
    .replace(/([?&](?:token|access_token|refresh_token|api_key|apikey|key|password|secret|signature|sig)=)[^&#\s"'`<>]*/gi, '$1[REDACTED]')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[REDACTED]@')
    // Consume a whole quoted value before considering a bare value. This also
    // covers raw JSON/HTTP bodies before a credential has been registered.
    .replace(/((?:["']?(?:password|passwd|secret|access_token|refresh_token|api_key|apikey)["']?)\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}"'&]+)/gi, '$1[REDACTED]')
    .replace(/((?:--user|-u)\s+)(?:'[^']*'|"[^"]*"|[^\s]+)/g, '$1[REDACTED]')
}
export function redactDisplay(value, secrets = [], options={}) {
  if (typeof value === 'string') return redactText(value, secrets, options)
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(x => redactDisplay(x, secrets, options))
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    out[key] = SECRET_KEY.test(key) && item ? '[REDACTED]' : redactDisplay(item, secrets, options)
  }
  return out
}
