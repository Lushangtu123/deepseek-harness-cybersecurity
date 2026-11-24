// Server-owned interpretation of this one broad research rule. Scanner metadata
// never establishes callee identity, input control, risk or disposition.
const RULE='policy.harness.python.dynamic-code-namespace';
const FACTS={version:1,kind:'execution-point',confidence:'low',risk:'not-assessed',calleeIdentity:'unverified',inputControl:'unverified'};
export function ruleObservation(tool,rule){return tool==='semgrep'&&rule===RULE?{...FACTS}:undefined}
export function validRuleObservation(tool,rule,value){return tool==='semgrep'&&rule===RULE&&!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===Object.keys(FACTS).length&&Object.entries(FACTS).every(([key,expected])=>Object.hasOwn(value,key)&&value[key]===expected)}
export function validObservationSummary(value){return !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===4&&value.version===1&&['total','executionPoints','other'].every(k=>Number.isSafeInteger(value[k])&&value[k]>=0&&value[k]<=2000)&&value.total===value.executionPoints+value.other}
