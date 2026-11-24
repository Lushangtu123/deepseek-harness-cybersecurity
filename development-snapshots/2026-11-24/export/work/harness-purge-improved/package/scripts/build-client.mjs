/**
 * 把 lib/redteam/client.js 抽成可嵌入的工厂片段，
 * 写进 client.js 里的 DSH_PURGE_DRILL 标记之间。
 *
 * 用法：node scripts/build-client.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { Script } from "node:vm";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const drillSrc = join(root, "lib", "redteam", "client.js");
const clientPath = join(root, "client.js");

const BEGIN = "/* __DSH_PURGE_DRILL_BEGIN__ */";
const END = "/* __DSH_PURGE_DRILL_END__ */";

let raw = readFileSync(drillSrc, "utf8").replace(/\r\n/g, "\n");
const startMark = "factory: (require) => {";
const start = raw.indexOf(startMark);
if (start < 0) throw new Error("cannot find ModuleLoader factory in drill client");
const endMark = "\n    return module.exports\n  },\n})";
const end = raw.lastIndexOf(endMark);
if (end < 0) throw new Error("cannot find factory end in drill client");
let body = raw.slice(start + startMark.length, end);
const helperSource = name => readFileSync(join(root, "lib", "redteam", name), "utf8").replace(/\r\n/g, "\n");
const bindingHelpers = helperSource("personal-binding-client.mjs").replace(/^export /gm, "");
const observationHelpers = helperSource("personal-security-observation.mjs").replace(/^export /gm, "");
const profileHelpers = helperSource("personal-semgrep-profile.mjs").replace(/^export /gm, "");
const securitySource = helperSource("personal-security-client.mjs");
const requiredImport = "import {ruleObservation,validRuleObservation,validObservationSummary} from './personal-security-observation.mjs';\n";
if (securitySource.split(requiredImport).length !== 2) throw new Error("required observation import missing or duplicated");
const profileImport = "import {validDeepSemgrepProfile} from './personal-semgrep-profile.mjs';\n";
if (securitySource.split(profileImport).length !== 2) throw new Error("required rule profile import missing or duplicated");
const securityHelpers = securitySource.replace(requiredImport, "").replace(profileImport, "").replace(/^export /gm, "");
body = "\n" + bindingHelpers + "\n" + observationHelpers + "\n" + profileHelpers + "\n" + securityHelpers + "\n" + body;

// 去掉末尾 exports（return 已在 endMark 外）
body = body
	.replace(/\n\s*exports\.apply\s*=\s*apply\s*\n/, "\n")
	.replace(/\n\s*exports\.inject\s*=\s*inject\s*\n/, "\n");

// 替换 apply(ctx)：不再自己注册槽位，只导出 Panel / CSS / 状态
const applyAt = body.lastIndexOf("function apply(ctx) {");
if (applyAt < 0) throw new Error("apply(ctx) not found in drill client");
// apply() 本体没有嵌套函数花括号冲突到 CSS（CSS 在前面），用括号深度即可
let d = 0;
let j = body.indexOf("{", applyAt);
for (; j < body.length; j += 1) {
	const ch = body[j];
	if (ch === "{") d += 1;
	else if (ch === "}") {
		d -= 1;
		if (d === 0) {
			j += 1;
			break;
		}
	}
}
const applyParts = `function applyDrillParts() {
      return { CSS: CSS, Panel: Panel, setUI: setUI, useUI: useUI, isFullWindow: isFullWindow, setDockWidth: setDockWidth };
    }
`;
body = body.slice(0, applyAt) + applyParts + body.slice(j);

const fragment = `${BEGIN}
		// 内嵌演练台（源码在 lib/redteam，已并进本插件）
		const __dshPurgeDrill = (() => {
			var module = { exports: {} };
			var exports = module.exports;
${body}
			return applyDrillParts();
		})();
${END}`;

let client = readFileSync(clientPath, "utf8");
if (!client.includes(BEGIN) || !client.includes(END)) {
	throw new Error("client.js missing drill markers; run patch-client-dock.mjs first");
}
const beginAt = client.indexOf(BEGIN);
const endAt = client.indexOf(END);
if (beginAt < 0 || endAt < 0 || endAt < beginAt) throw new Error("drill markers out of order");
client = client.slice(0, beginAt) + fragment + client.slice(endAt + END.length);
new Script(client, { filename: clientPath });
writeFileSync(clientPath, client);
console.log("embedded drill client into client.js (" + Buffer.byteLength(fragment) + " bytes fragment)");
