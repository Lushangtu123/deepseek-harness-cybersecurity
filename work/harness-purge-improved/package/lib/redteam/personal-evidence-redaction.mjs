export const SECRET_KEY = /^(?:secret(?:_value)?|pass_key|password|passwd|access_token|refresh_token|api_key|apikey|authorization|proxy-authorization|cookie|set-cookie)$/i
export function redactKnownText(value, secrets = []) {
  let text = String(value)
  for (const secret of [...new Set(secrets.filter(s => typeof s === 'string' && s))].sort((a, b) => b.length - a.length)) {
    for (const encoded of new Set([secret, encodeURIComponent(secret)])) text = text.split(encoded).join('[REDACTED]')
  }
  return text
}
export function redactText(value, secrets = []) {
  return redactKnownText(value,secrets)
    .replace(/\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n"']*/gi, '$1: [REDACTED]')
    .replace(/([?&](?:token|access_token|refresh_token|api_key|apikey|key|password|secret|signature|sig)=)[^&#\s"'`<>]*/gi, '$1[REDACTED]')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[REDACTED]@')
    // Consume a whole quoted value before considering a bare value. This also
    // covers raw JSON/HTTP bodies before a credential has been registered.
    .replace(/((?:["']?(?:password|passwd|secret|access_token|refresh_token|api_key|apikey)["']?)\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}"'&]+)/gi, '$1[REDACTED]')
    .replace(/((?:--user|-u)\s+)(?:'[^']*'|"[^"]*"|[^\s]+)/g, '$1[REDACTED]')
}
export function redactDisplay(value, secrets = []) {
  if (typeof value === 'string') return redactText(value, secrets)
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(x => redactDisplay(x, secrets))
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    out[key] = SECRET_KEY.test(key) && item ? '[REDACTED]' : redactDisplay(item, secrets)
  }
  return out
}
