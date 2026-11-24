// This package profile is fixed, not fetched or chosen by project content.
// Runtime readiness describes managed S1 execution, not R3 detection quality.
const SEMGREP_DEEP_PROFILE={version:1,id:'deep-namespace17',mode:'deep',baseRulesSha256:'44ab404c318fd5cf6145b8aa1fed7a31b8eb22b67a0d2412fbab728276e803ed',rulesSha256:'e70603d05be7dc49ca3973b5d67ea02f25fb979ca3271bfc6bbeb19307ce9773',ruleCount:17,qualification:'managed-candidate-not-r3'};
export function deepSemgrepProfile(){return {...SEMGREP_DEEP_PROFILE}}
export function validDeepSemgrepProfile(value){return !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===Object.keys(SEMGREP_DEEP_PROFILE).length&&Object.entries(SEMGREP_DEEP_PROFILE).every(([key,expected])=>Object.hasOwn(value,key)&&value[key]===expected)}
