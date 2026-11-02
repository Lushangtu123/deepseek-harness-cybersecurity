window.__ModuleLoader__.load({ id: "dsh-purge", factory: (require) => {

		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		const h = react.createElement;
		const { useState, useEffect, useCallback, useRef, Component } = react;

		const name = "dsh-purge";
		const inject = ["slots", "locale", "uiConversation", "remote", "remote.terminal", "remote.directoryPicker"];
		const NS = "settings.dsh-purge";
		let translate = (key) => key;
		function useT() {
			return translate;
		}
		function clientGuessSurface() {
			try {
				if (typeof navigator !== "undefined" && /electron/i.test(navigator.userAgent || "")) return "desktop";
				if (typeof location !== "undefined") {
					const port = String(location.port || "");
					if (port === "43120") return "desktop";
					const host = String(location.hostname || "");
					if (host && host !== "127.0.0.1" && host !== "localhost" && /dsh desktop/i.test(String(location.href || ""))) return "desktop";
				}
			} catch { /* ignore */ }
			return "";
		}
		function hostSurfaceOf(s) {
			return (s && s.surface) || clientGuessSurface() || "web";
		}
		function hostText(t, key, surface) {
			if (surface && surface !== "web") {
				const specific = key + "." + surface;
				const hit = t(specific);
				if (hit && hit !== specific) return hit;
			}
			return t(key);
		}
		function apiUrl(p) {
			try { return new URL(p, window.location.origin).toString(); } catch { return p; }
		}
		function apiTimeoutMs(p, init) {
			const path = String(p || "");
			const method = String((init && init.method) || "GET").toUpperCase();
			if (path.indexOf("/dsh-purge/update") !== -1) return method === "POST" ? 180000 : 45000;
			if (path.indexOf("/dsh-purge/uninstall") !== -1) return 90000;
			if (path.indexOf("/dsh-purge/skill") !== -1) return method === "POST" ? 120000 : 20000;
			// status 会在"应用"期间被后端的同步落盘阻塞，默认 20s 必然被 abort，界面只会显示"读取失败: timeout"。
			if (path.indexOf("/dsh-purge/status") !== -1) return 60000;
			if (path.indexOf("/dsh-purge/apply") !== -1) return 240000;
			if (path.indexOf("/dsh-purge/revert") !== -1) return 120000;
			if (path.indexOf("/dsh-purge/restart") !== -1) return 60000;
			return 20000;
		}
		function isAbortError(e) {
			const msg = String((e && e.message) || e || "");
			return (e && e.name === "AbortError") || /aborted|abort/i.test(msg);
		}
		async function apiJson(p, init) {
			const ctrl = new AbortController();
			const timer = setTimeout(() => ctrl.abort(), apiTimeoutMs(p, init));
			try {
				const r = await fetch(apiUrl(p), Object.assign({ cache: "no-store", credentials: "same-origin", signal: ctrl.signal }, init || {}));
				const text = await r.text();
				let data;
				try { data = text ? JSON.parse(text) : null; } catch {
					throw new Error(r.status + " non-json: " + text.slice(0, 120));
				}
				if (!r.ok) throw new Error((data && (data.error || data.message)) || (r.status + " " + r.statusText));
				return data;
			} catch (e) {
				if (isAbortError(e)) throw new Error("timeout");
				const msg = String((e && e.message) || e || "");
				if (/failed to fetch|networkerror|load failed/i.test(msg)) {
					throw new Error("Cannot reach the API. Make sure dsh is still running, then press Ctrl+F5");
				}
				throw e;
			} finally { clearTimeout(timer); }
		}

		function promptBoxEmpty(text) {
			return !String(text || "").trim();
		}

		function responseNeedsPrompt(d) {
			return Boolean(d && (d.needPrompt || d.injectSource === "none"));
		}

		function warnNeedPrompt(d, tr) {
			if (!responseNeedsPrompt(d)) return false;
			window.alert(tr("need.prompt"));
			return true;
		}

		async function bothInjectEmpty(overrideText, defaultText) {
			if (!promptBoxEmpty(overrideText)) return false;
			if (!promptBoxEmpty(defaultText)) return false;
			return true;
		}

		function rulesApi(op, extra) {
			return apiJson("/dsh-purge/rules", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(Object.assign({ op: op }, extra || {})),
			});
		}

		function skillsRouteMissing(e) {
			return /\b404\b|\b405\b|non-json/i.test(String((e && e.message) || e || ""));
		}

		function skillsApi(op, extra) {
			const init = {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(Object.assign({ op: op }, extra || {})),
			};
			return apiJson("/dsh-purge/skills", init).catch((e) => {
				if (!skillsRouteMissing(e)) throw e;
				return apiJson("/dsh-purge/skill", init);
			});
		}

		const TARGETS = ["AGENTS.md", "CLAUDE.md"];

		const zh = {
			nav: "规则设定",
			"dock.clean": "权限与状态",
			"dock.drill": "演练台",
			"dock.toggle": "dsh-purge",
			"dock.newSession": "dsh-purge",
			"dock.inSession": "dsh-purge",
			"dock.redteam": "红队模式",
			"dock.full": "全面浏览",
			"dock.close": "收起",
			"dock.unauthorized": "未授权",
			"welcome.title": "用户须知",
			"welcome.lead": "首次安装本插件时请阅读以下说明。确认后本窗不再弹出。",
			"welcome.warn": "本插件免费开源。任何背着作者私自售卖、付费倒卖或借本项目盈利的行为，作者将依法追究法律责任。",
			"welcome.body": "dsh-purge 是 DeepSeek Harness 的本机网络安全红队评测与清洗插件：在受控本机环境中调整提示词与补丁、做授权范围内的演练台操作。项目免费、非营利，源码仓库：",
			"welcome.repo": "https://github.com/YuJunZhiXue/dsh-purge",
			"welcome.ban1": "禁止将本项目用于未授权的网络攻击、入侵、窃取数据、破坏系统或任何违法犯罪。",
			"welcome.ban2": "禁止商业售卖、付费倒卖、黑灰产牟利，以及隐瞒作者的营利性再分发。",
			"welcome.ban3": "使用者须自行遵守所在地法律法规与平台规范；违法后果由行为人自行承担，与作者无关。",
			"welcome.bans": "禁止事项",
			"welcome.check": "我已阅读并理解上述用户须知，同意合法合规使用。",
			"welcome.ok": "我已知晓并继续",
			"auth.title": "演练台授权确认",
			"auth.lead": "清洗不需要这一步。第一次进入演练台，或打开全面浏览，都要先完成本窗。",
			"auth.warn": "安全警告：演练台只用于你有权管理的本机、离线靶标，或已书面授权的演练环境。未经授权的渗透、攻击、窃取和破坏一律禁止。",
			"auth.hint.wait": "请阅读声明。{n} 秒后才能勾选。",
			"auth.hint.scroll": "倒计时已结束。请把声明滚到文末，再勾选。",
			"auth.hint.check": "倒计时已结束。请勾选全部三项。",
			"auth.check.read": "我已读完《安全与禁止违法声明》，并认可其中的全部条款。",
			"auth.check.scope": "我确认只用在本机已授权环境、离线靶标或合规演练中。",
			"auth.check.ban": "我确认禁止任何违法用途。未完成本授权，不得使用演练台。",
			"auth.no": "暂不进入",
			"auth.ok": "确认授权",
			"auth.ok.tab": "确认授权并进入演练台",
			"auth.ok.full": "确认授权并全面浏览",
			"auth.ok.env": "确认授权并打开环境适配",
			"envGate.title": "环境还没配好",
			"envGate.lead": "红队模式发送前需要本机工具。未检测到可用环境时，先去环境适配，或确认暂不配置。",
			"envGate.kaliHint": "检测到 Kali 时会直接用本机工具，不必填路径。没有 Kali 时，在环境适配里填写各工具路径，或选一个整包文件夹自动分配。",
			"envGate.skip": "暂不配置",
			"envGate.skipConfirm": "确认后这次可以继续对话。扫描和利用类技能仍会因为缺少工具而不可用，之后可以在 dsh-purge → 环境适配里补路径。",
			"envGate.skipNo": "返回",
			"envGate.skipYes": "确认暂不配置",
			"envGate.go": "去环境适配",
			"theme.aria": "外观",
			"theme.white": "白",
			"theme.ink": "墨",
			"purge.title": "补丁",
			"override.title": "提示词",
			"own.title": "本地靶场",
			"own.hint": "开源版攻击任务只放行本机/内网 IP。域名会先解析，解析到的每一个地址都必须是私网或回环；hosts 把 .lab 指到公网 IP 也会拦。解析失败或混有公网地址一律拦截。",
			"own.save": "保存名单",
			"saved.own": "已保存自己的服务器",
			"saved.own.dropped": "已保存。有 {n} 行不是单个 IP 或主机名，已丢掉",
			"metric.purged": "已写入",
			"metric.purged.skip": "已写入。跳过 {n} 项，本机没有这些文件",
			"metric.pendingShort": "待处理 {n}",
			"metric.unmatchedShort": "没对上 {n}",
			"metric.skipShort": "跳过 {n}",
			"metric.unlocated.count": "—",
			"metric.shim": "shim",
			"metric.shim.na": "本端不需要",
			"metric.bak.yes": "有备份",
			"metric.bak.no": "无备份",
			"metric.bak.hint": "备份",
			"table.patch": "项目",
			"table.status": "状态",
			"status.applied": "已应用",
			"status.off": "已关闭",
			"status.pending": "待应用",
			"status.unmatched": "没对上",
			"status.skipped": "跳过",
			"apply.hint": "没改提示词框不用点保存，默认就是这份，启动和应用会写进 prompt-inject.md。只有自己改过再点保存才会覆盖。点应用打补丁。待应用=原文还在。跳过=当前版本不需要或组件未安装。",
			"warn.noRoot": "未定位到当前宿主的 @deepseek-ai，清洗不会生效。请完全退出后再打开本宿主，在本页点「应用」。桌面端安装目录可以是任意盘符；目录名带 DeepseekHarness / DeepSeek Harness 均可。",
			"warn.noRoot.desktop": "官方客户端的代码在 app.asar 里。点「应用」会解开并自动重启，不用另跑脚本。若一直显示还没定位，先完全退出客户端再开，再点「应用」。第三方 DSH Desktop 直接点「应用」。",
			"unpack.restarting": "补丁已写入。点「重启」后客户端会自己重新打开。",
			"restart.fullQuit": "正在重启，客户端会自己重新打开。",
			"warn.noInject": "官方始终用默认提示词。红队开了规则集就只用规则集；没开时用去掉 CTF 的默认提示词，再接红队操作。两边都空会提示必须添加。",
			"need.prompt": "提示词和规则集都是空的，必须先添加提示词，或启用一条有内容的规则集。",
			"btn.restoreInject": "恢复默认",
			"saved.restoreInject": "已恢复默认提示词",
			"skip": "跳过",
			"unknown": "未知",
			"delete": "删除",
			"btn.apply": "应用",
			"btn.apply.busy": "处理中…",
			"btn.revert": "还原",
			"btn.uninstall": "卸载",
			"btn.uninstall.busy": "卸载中…",
			"uninstall.title": "卸载 dsh-purge",
			"uninstall.body": "是否卸载？卸载将还原回原版，并清除本插件的全部文件与补丁。",
			"uninstall.confirm": "确认卸载",
			"uninstall.cancel": "取消",
			"uninstall.applying": "正在卸载并还原…",
			"uninstall.done": "已卸载并还原，正在重启…",
			"uninstall.done.desktop": "已卸载并还原，正在重启桌面应用…",
			"uninstall.fail": "卸载失败: {error}",
			"btn.checkUpdate": "检测更新",
			"btn.checkUpdate.busy": "检测中…",
			"btn.doUpdate": "更新",
			"btn.doUpdate.busy": "更新中…",
			"channel.title": "通道",
			"channel.stable": "正式版",
			"channel.beta": "测试版",
			"channel.useStable": "切换到正式版",
			"channel.useBeta": "切换到测试版",
			"channel.local": "本机",
			"update.checking": "正在检测更新…",
			"update.applying": "正在更新…",
			"update.switching": "正在切换版本…",
			"update.latest": "已是最新（{version}）",
			"update.available": "有新版本 {remote}，当前 {local}",
			"update.pinned": "已固定在 {version}，通道最新是 {remote}",
			"update.done": "已更新到 {version}",
			"update.restarting": "已还原并写入新补丁，正在重启…",
			"update.fullQuit": "补丁已写入。点「重启」后客户端会自己重新打开。",
			"restart.official.title": "需要重启",
			"restart.official.body": "补丁已写入。点重启后客户端会自己重新打开。",
			"update.switched": "已切换到 {version}",
			"update.autoDone": "已自动更新到 {version}",
			"update.reloading": "正在刷新设置页…",
			"update.dirty": "有新版本，本地有改动未自动覆盖",
			"update.fail": "更新失败: {error}",
			"update.timeout": "检测超时，请再点一次检测更新",
			"update.needRestart": "检测接口未加载，请先重启 dsh 再点检测更新",
			"update.noBeta": "还没有测试版",
			"update.switch": "切换到此版本",
			"update.pick": "选择版本",
			"update.tip": "最新",
			"update.current": "当前",
			"update.confirmSwitch": "切换到 {version}？之后可再切回另一通道或其它版本。本地未提交的插件改动不会保留。",
			"update.confirmChannel": "切换到{version}？会按该通道重新安装插件，本地未提交的插件改动不会保留。",
			"metric.version": "版本",
			"action.apply": "应用",
			"action.revert": "还原",
			"action.uninstall": "卸载",
			"ok.done": "已完成",
			"err.action": "失败: {error}",
			"err.status": "读取失败: {error}",
			"err.override": "读取失败: {error}",
			"err.rules": "读取失败: {error}",
			"err.read": "读取失败: {error}",
			"err.save": "保存失败: {error}",
			"btn.saveInject": "保存",
			"saved.override": "已保存",
			"rules.title": "规则集",
			"rules.none": "无",
			"rules.reset": "还原",
			"rules.reset.confirm": "还原全局指令文件？规则库会保留。",
			"rules.empty": "暂无规则",
			"rules.pick": "选择规则",
			"policy.title": "工作区策略",
			"policy.strict": "严格",
			"policy.fallback": "空位兜底",
			"policy.always": "总是允许",
			"policy.hint": "严格：永远剥 AGENTS.md / CLAUDE.md；空位兜底：提示词框为空时才用；总是允许：保留 DSH 原生行为",
			"cwd.title": "本地规则（当前目录）",
			"cwd.empty": "当前目录没有 AGENTS.md / CLAUDE.md",
			"cwd.rescan": "重新扫描",
			"cwd.hint": "只有提示词框为空时，被勾选的本地文件才作为兜底注入；提示词框一旦非空就不会用这些文件。",
			"cwd.scope.cwd": "当前目录",
			"cwd.scope.ancestor": "上级",
			"cwd.scope.root": "项目根",
			"cwd.no.workspace": "DSH 尚未选过工作目录，请先在 DSH 里开始一次任务再回来。",
			"pill.current": "当前",
			"btn.use": "启用",
			"btn.inUse": "当前",
			"confirm.delete": "删除 {id}？",
			"ph.id": "id",
			"ph.alias": "名称",
			"ph.alias.short": "名称",
			"btn.create": "新建",
			"need.id": "需要 id",
			"ph.content": "",
			"btn.saveRule": "保存",
			"skills.title": "Skill",
			"skills.hint": "导入到官方目录后，由 DSH 调用：聊天输入 /名称 立即加载；任务对上 description 或 whenToUse 时模型会调 skill 工具。正文写「激活」不会触发。",
			"skills.hint.desktop": "当前桌面宿主的官方 Skill 目录。聊天输入 /名称 立即加载；任务对上 description 时模型会调 skill 工具。",
			"skills.empty": "暂无用户 Skill",
			"btn.importZip": "导入压缩包",
			"btn.importFolder": "导入文件夹",
			"skills.importing": "正在导入…",
			"saved.import": "已导入 {count} 个 Skill",
			"need.import": "请选择压缩包或文件夹",
			"err.import.folder": "没读到文件夹里的文件，请直接选 Skill 目录（里面要有 SKILL.md）",
			"skills.pick": "选择 Skill",
			"skills.invalid": "官方会忽略：格式不对",
			"skills.call.slash": "聊天输入 {cmd}",
			"skills.call.model": "模型可调",
			"skills.call.modelOff": "模型不可调",
			"skills.call.userOff": "不可 /名称",
			"ph.skill.desc": "description（何时用）",
			"btn.saveSkill": "保存",
			"need.skill.id": "id 必须是 kebab-case，例如 code-review",
			"confirm.delete.skill": "从官方 $DSH_HOME/skills 删除 {id}？宿主会自动从目录拿掉。",
			"err.skills": "读取失败: {error}",
			"err.skills.needRestart": "Skill 接口未加载，请先重启当前宿主",
			"btn.restart": "重启",
			"btn.restart.busy": "重启中…",
			"restarting": "重启中…",
			"restarting.desktop": "正在重启桌面应用…",
			"restart.timeout": "超时，请刷新",
			"restart.fail": "失败: {error}",
			"restart.notStarted": "重启没有开始，客户端还在。不会自动再试。",
			"restart.already": "这一次重启已经开始，不会再重启一次。",
			"restart.confirm": "清洗已完成，重启后生效。",
			"restart.confirm.desktop": "清洗已完成，重启桌面应用后生效。",
			"restart.ask.title": "要现在重启吗",
			"restart.ask.body": "已经写入。重启后才会在当前客户端里生效。",
			"restart.now": "现在重启",
			"restart.notNow": "稍后",
			"restart.asarSwap": "补丁已写入磁盘。正在结束桌面进程并挪开 app.asar，完成后会自动重新打开；若仍无效，请先完全退出 Harness（托盘也关），再点一次应用。",
			"surface.web": "Web",
			"surface.desktop": "桌面端",
			"surface.gui": "GUI",
			"surface.tui": "TUI",
			"restart.incomplete": "提示词已写入。{detail}",
			"restart.incomplete.patches": "还有 {failed} 项代码补丁没对上当前版本（#{ids}），不影响这段提示词",
			"restart.incomplete.flash": "CMD 无感未钉入（{entry}）",
			"restart.later": "以后",
			"group.prompt": "提示词",
			"group.code": "代码",
			"group.engine": "引擎",
			"group.tools": "工具",
			"group.compat": "0.1.5 兼容",
			"group.dsh20": "0.2.0",
			"patch.1": "全局免责 → 强指令",
			"patch.2": "替换式免责 → 强指令",
			"patch.3": "作用域免责 → 强指令",
			"patch.4": "persona 会话强指令",
			"patch.5": "审批提示句 → 全权限",
			"patch.6": "沙箱 deny → allow 写",
			"patch.7": "沙箱默认全权限",
			"patch.8": "审批默认 never",
			"patch.9": "审批门自动放行",
			"patch.10": "审批配置默认 never",
			"patch.11": "never 提示句 → 自动放行",
			"patch.12": "ask 提示句 → 自动放行",
			"patch.13": "豁免升级阶梯",
			"patch.14": "升级无条件授信",
			"patch.15": "沙箱 confine 直通",
			"patch.16": "文件系统围栏取消",
			"patch.17": "观察策略读写放行",
			"patch.18": "重复调用守卫禁用",
			"patch.19": "工具结果修剪禁用",
			"patch.21": "恢复插件延长的 bash 等待",
			"patch.22": "read 上限放宽",
			"patch.23": "子代理深度 3 → 10",
			"patch.24": "preset fetch 启用",
			"patch.25": "去掉官方默认身份（功能提示词不动）",
			"patch.26": "minimal：去掉默认身份并打开 inject",
			"patch.28": "dsh-liangshen（梁神）：phase-1 保留 dsh-purge / dshpg 段",
			"patch.70": "极简模式终端不再禁止网络",
			"patch.71": "梁神去掉官方身份句",
			"patch.29": "dsh-tool-web：外部 untrusted 拦截→可执行",
			"patch.30": "dsh-hooks-claude-code：deny→allow",
			"patch.31": "dsh-hooks-codex：deny→allow",
			"patch.32": "Web 表面身份中性化",
			"patch.33": "Shell 拒绝提示 → 可执行",
			"patch.34": "沙箱提示中性化",
			"patch.35": "升级 never 不拒",
			"patch.36": "文件系统升级 schema 放行",
			"patch.37": "子代理 scope lock 中性化",
			"patch.38": "persona text→prefix（0.1.2 预设）",
			"patch.39": "会话 v0 plugin summary（mnemon）",
			"patch.40": "complete 预设仍保留注入",
			"patch.42": "设置页旧接口",
			"patch.43": "网页预设去掉默认身份",
			"patch.45": "官方桌面更新交接",
			"patch.46": "官方更新脚本只用英文",
			"patch.47": "OAuth 不再插入 Claude 身份",
			"patch.48": "shell 去掉删除前的额外确认",
			"patch.49": "OAuth 不再伪装 claude-cli",
			"patch.50": "跨会话引用不再标不可信",
			"patch.51": "新会话保持完全权限",
			"patch.52": "会话日志默认不上传",
			"patch.53": "网页提示去掉禁止另开服务器",
			"patch.54": "交付物提示去掉多余禁止",
			"patch.55": "每一步替换第一条系统提示",
			"patch.56": "回退只藏被撤掉的那一轮",
			"patch.57": "developer role 仅限 openai/azure，第三方代理回退 system",
			"patch.58": "回退空标记不进模型请求",
			"patch.59": "官方 Auto Review 不再拦工具",
			"patch.60": "官方 run_code 去掉审批教学",
			"patch.61": "官方沙箱策略不再教拒绝",
			"patch.62": "无审批通道时放行（用户拒绝仍有效）",
			"patch.63": "计划模式不再软拦执行",
			"patch.64": "Stop hook 不再注入假用户话",
			"patch.65": "UserPromptSubmit deny 不再整轮 reject",
			"patch.66": "空的系统段不再把这一轮打成内部错误",
			"patch.67": "缺 messages 时这一轮不中断",
			"patch.68": "回退后缺 content 不中断",
			"patch.69": "deepseek-flash 保持官方 in-history",
			"patch.72": "Messages 的 system 用当前系统提示",
			"patch.73": "极简 bash 去掉误留的镜像说明",
			"patch.74": "启动/应用把默认提示词写入 prompt-inject.md",
			"patch.75": "回退把已完成任务收回成未开始",
			"patch.76": "unrestricted 预设去掉身份句",
			"patch.77": "回退标记到达时丢弃已发送消息",
			"patch.78": "补丁文件缺失时从 .bak 恢复",
			"patch.80": "恢复官方极简工具表",
			"patch.82": "主进程兜底 DSH_PROFILE=desktop",
			"patch.83": "host 信号杀时不报错不弹对话框",
			"patch.84": "host code=0 正常退出不报错 (消除 stopped 对话框)",
			"patch.85": "prompt() 的 steer 仍走插话，不压成 followup",
			"patch.86": "队列插话走 steer；公共 steer() 保持下一步",
			"patch.87": "首次 assemble 用 prepare 返回的当前模式 systemPrompt",
			"patch.88": "去掉 renderPrompt 后的挂针，注入只走 assemble",
			"status.unlocated": "未定位",
			"status.na": "本端不需要",
			"metric.unlocated": "还没定位到本机 Harness",
			"metric.sealed": "已找到官方客户端，点应用解开",
			"metric.sealed.count": "待解开",
			"metric.lost": "补丁已丢失，请重新应用",
			"metric.lost.count": "已丢失",
			"rewind.label": "回退",
			"rewind.aria": "回退",
			"rewind.busy": "回退中…",
			"rewind.empty": "没有可回退的上一句",
			"rewind.fail": "回退失败: {error}",
			"rewind.once": "回退上一步",
					"rewind.once.hint": "撤回最后一步已进行的对话，新会话接上之前的上下文；那句回到输入框再发送",
			"rewind.round": "回退上一轮",
					"rewind.round.hint": "撤回上一整轮（含子代理）已进行的对话，新会话接上之前的上下文；那句回到输入框再发送",
			"hooksDeny.title": "Hooks 拦截",
			"hooksDeny.bypass": "放行 hooks 的 deny / ask（补丁 30 / 31 / 64 / 65）",
			"hooksDeny.hint": "关掉后，用户自己的 PreToolUse / UserPromptSubmit / Stop hook 的 deny 会按官方逻辑生效。官方 ask 分支本身是空操作，关开关不会弹出审批框。改完后点「应用」并重启才写进宿主。",
			"saved.hooksDeny": "已保存",
			"continue.title": "失败重试 / 继续",
			"continue.hint": "请求失败会自动重试；异常停止或中断可点「继续」或自动续跑。自己点停止不会自动继续。次数用完后需新开一轮。",
			"continue.autoRetry": "失败自动重试",
			"continue.retryMax": "重试次数",
			"continue.autoContinue": "中断后自动继续",
			"continue.continueMax": "继续次数",
			"continue.text": "继续用语",
			"saved.continue": "已保存",
			"continue.label": "继续",
			"continue.aria": "异常停止后继续",
			"continue.busy": "继续中…",
			"continue.ready": "继续（还可 {left} 次）",
			"continue.limit": "已达继续上限",
			"continue.fail": "继续失败: {error}",
		};

		const en = {
			nav: "Rules",
			"dock.clean": "Permissions",
			"dock.drill": "Drill",
			"dock.toggle": "dsh-purge",
			"dock.newSession": "dsh-purge",
			"dock.inSession": "dsh-purge",
			"dock.redteam": "Red team",
			"dock.full": "Full view",
			"dock.close": "Collapse",
			"dock.unauthorized": "Unauthorized",
			"welcome.title": "User notice",
			"welcome.lead": "Please read this on first install. After you confirm, it will not appear again.",
			"welcome.warn": "This plugin is free and open source. Anyone who sells, resells, or profits from it behind the author's back may face legal action.",
			"welcome.body": "dsh-purge is a local DeepSeek Harness plugin for security evaluation and cleaning: adjust prompts and patches on a machine you control, and use the drill console only within authorized scope. It is free and non-profit. Repository:",
			"welcome.repo": "https://github.com/YuJunZhiXue/dsh-purge",
			"welcome.ban1": "Do not use this project for unauthorized attacks, intrusion, data theft, sabotage, or any illegal activity.",
			"welcome.ban2": "Do not commercially sell, resell, or profit from gray-market use, or redistribute for profit without the author.",
			"welcome.ban3": "You must follow local law and platform rules; illegal use is solely your responsibility.",
			"welcome.bans": "Prohibitions",
			"welcome.check": "I have read and understand this notice and will use the plugin lawfully.",
			"welcome.ok": "I understand — continue",
			"auth.title": "Drill console authorization",
			"auth.lead": "Cleaning does not need this step. Opening Drill or Full view the first time requires this dialog.",
			"auth.warn": "Warning: the drill console is only for hosts you manage, offline targets, or written authorized exercises. Unauthorized intrusion, attack, theft, or sabotage is forbidden.",
			"auth.hint.wait": "Read the notice. You can check the boxes in {n}s.",
			"auth.hint.scroll": "Countdown finished. Scroll to the end, then check the boxes.",
			"auth.hint.check": "Countdown finished. Check all three boxes.",
			"auth.check.read": "I have read the Safety and Anti-Abuse Notice and accept every clause.",
			"auth.check.scope": "I will only use authorized local hosts, offline targets, or compliant exercises.",
			"auth.check.ban": "I will not use this for any illegal purpose. Without this authorization the drill console stays closed.",
			"auth.no": "Not now",
			"auth.ok": "Authorize",
			"auth.ok.tab": "Authorize and open Drill",
			"auth.ok.full": "Authorize and open Full view",
			"auth.ok.env": "Authorize and open Env adapt",
			"envGate.title": "Environment is not ready",
			"envGate.lead": "Red team mode needs local tools before you send. If none are available, open Env adapt or confirm you will continue without them.",
			"envGate.kaliHint": "When Kali is detected, local tools are used directly and paths are optional. Otherwise set each tool path in Env adapt, or pick one toolkit folder to assign them.",
			"envGate.skip": "Skip for now",
			"envGate.skipConfirm": "You can keep chatting after this. Scan and exploit skills stay unavailable until the tools are installed. You can add paths later under dsh-purge → Env adapt.",
			"envGate.skipNo": "Back",
			"envGate.skipYes": "Continue without tools",
			"envGate.go": "Open Env adapt",
			"theme.aria": "Appearance",
			"theme.white": "Light",
			"theme.ink": "Ink",
			"purge.title": "Patches",
			"override.title": "Prompt",
			"own.title": "Local lab only",
			"own.hint": "The open-source build only allows localhost/private IPs. Domains are resolved first; every A/AAAA must be loopback or RFC1918. A hosts entry that points .lab at a public IP is blocked. Failed or mixed public answers are denied.",
			"own.save": "Save list",
			"saved.own": "Own servers saved",
			"saved.own.dropped": "Saved. {n} lines were not a single IP or hostname and were dropped",
			"metric.purged": "Written",
			"metric.purged.skip": "Written. Skipped {n}; those files are not on this install",
			"metric.pendingShort": "Pending {n}",
			"metric.unmatchedShort": "No match {n}",
			"metric.skipShort": "Skipped {n}",
			"metric.unlocated.count": "—",
			"metric.shim": "shim",
			"metric.shim.na": "Not needed here",
			"metric.bak.yes": "Backup",
			"metric.bak.no": "No backup",
			"metric.bak.hint": "Backup",
			"table.patch": "Item",
			"table.status": "Status",
			"status.applied": "Applied",
			"status.off": "Off",
			"status.pending": "Pending",
			"status.unmatched": "No match",
			"status.skipped": "Skipped",
			"apply.hint": "If you did not edit the prompt box, do not save. The default is already used and is written to prompt-inject.md on start/apply. Save only after you change it. Apply writes host patches. Pending = original text still present. Skipped = not needed for this version or the component is not installed.",
			"warn.noRoot": "Could not find this host’s @deepseek-ai tree, so Apply will not patch anything. Fully quit and reopen this host, then Apply here. Desktop may live on any drive; folder names like DeepseekHarnessDesktop or DeepSeek Harness are fine.",
			"warn.noRoot.desktop": "Official Harness keeps its code in app.asar. Apply unpacks it and restarts the app. If this page stays “not found”, fully quit the client, reopen it, then Apply again. Third-party DSH Desktop: just Apply.",
			"unpack.restarting": "Patches are written. Click Restart and the client opens again by itself.",
			"restart.fullQuit": "Restarting. The client will open again by itself.",
			"warn.noInject": "Official mode always uses the default prompt. Red team uses only the active rule set; otherwise it uses the default prompt without the CTF section, then the red team steps. If both are empty you will be asked to add a prompt.",
			"need.prompt": "Both the prompt and the rule set are empty. Add a prompt, or enable a rule that has content.",
			"btn.restoreInject": "Reset default",
			"saved.restoreInject": "Default prompt restored",
			"skip": "Skipped",
			"unknown": "Unknown",
			"delete": "Delete",
			"btn.apply": "Apply",
			"btn.apply.busy": "Working…",
			"btn.revert": "Restore",
			"btn.uninstall": "Uninstall",
			"btn.uninstall.busy": "Uninstalling…",
			"uninstall.title": "Uninstall dsh-purge",
			"uninstall.body": "Uninstall? This restores the original Harness and removes this plugin completely.",
			"uninstall.confirm": "Uninstall",
			"uninstall.cancel": "Cancel",
			"uninstall.applying": "Uninstalling and restoring…",
			"uninstall.done": "Uninstalled and restored. Restarting…",
			"uninstall.done.desktop": "Uninstalled and restored. Restarting the desktop app…",
			"uninstall.fail": "Uninstall failed: {error}",
			"btn.checkUpdate": "Check update",
			"btn.checkUpdate.busy": "Checking…",
			"btn.doUpdate": "Update",
			"btn.doUpdate.busy": "Updating…",
			"channel.title": "Channel",
			"channel.stable": "Stable",
			"channel.beta": "Beta",
			"channel.useStable": "Switch to stable",
			"channel.useBeta": "Switch to beta",
			"channel.local": "This copy",
			"update.checking": "Checking for updates…",
			"update.applying": "Updating…",
			"update.switching": "Switching version…",
			"update.latest": "Up to date ({version})",
			"update.available": "Update {remote} available (now {local})",
			"update.pinned": "Pinned at {version}; channel latest is {remote}",
			"update.done": "Updated to {version}.",
			"update.restarting": "Restored the old patches, wrote the new ones, and restarting…",
			"update.fullQuit": "Patches are written. Click Restart and the client opens again by itself.",
			"restart.official.title": "Restart required",
			"restart.official.body": "Patches are written. Click Restart and the client opens again by itself.",
			"update.switched": "Switched to {version}.",
			"update.autoDone": "Auto-updated to {version}.",
			"update.reloading": "Refreshing settings…",
			"update.dirty": "Update available; local edits were not overwritten.",
			"update.fail": "Update failed: {error}",
			"update.timeout": "Check timed out. Click Check update again.",
			"update.needRestart": "Update API is not loaded. Restart dsh, then check again.",
			"update.noBeta": "No beta build yet",
			"update.switch": "Switch to this version",
			"update.pick": "Select version",
			"update.tip": "latest",
			"update.current": "current",
			"update.confirmSwitch": "Switch to {version}? You can switch back later. Uncommitted plugin edits will not be kept.",
			"update.confirmChannel": "Switch to {version}? The plugin will be reinstalled from that channel. Uncommitted plugin edits will not be kept.",
			"metric.version": "Version",
			"action.apply": "Apply",
			"action.revert": "Restore",
			"action.uninstall": "Uninstall",
			"ok.done": "Done",
			"err.action": "Failed: {error}",
			"err.status": "Read failed: {error}",
			"err.override": "Read failed: {error}",
			"err.rules": "Read failed: {error}",
			"err.read": "Read failed: {error}",
			"err.save": "Save failed: {error}",
			"btn.saveInject": "Save",
			"saved.override": "Saved",
			"rules.title": "Rule sets",
			"rules.none": "None",
			"rules.reset": "Restore",
			"rules.reset.confirm": "Restore global instruction files? The rule library is kept.",
			"rules.empty": "No rules",
			"rules.pick": "Select a rule",
			"policy.title": "Workspace policy",
			"policy.strict": "Strict",
			"policy.fallback": "Fallback",
			"policy.always": "Always on",
			"policy.hint": "Strict: always strip AGENTS.md / CLAUDE.md. Fallback: use workspace files only when the prompt box is empty. Always on: keep DSH default behavior.",
			"cwd.title": "Local rules (current folder)",
			"cwd.empty": "No AGENTS.md / CLAUDE.md in this folder",
			"cwd.rescan": "Rescan",
			"cwd.hint": "Checked files are injected only when the prompt box is empty. A non-empty prompt box always wins.",
			"cwd.scope.cwd": "cwd",
			"cwd.scope.ancestor": "ancestor",
			"cwd.scope.root": "project root",
			"cwd.no.workspace": "DSH has not opened a workspace yet. Start a task in DSH first, then come back.",
			"pill.current": "On",
			"btn.use": "Enable",
			"btn.inUse": "On",
			"confirm.delete": "Delete {id}?",
			"ph.id": "id",
			"ph.alias": "Name",
			"ph.alias.short": "Name",
			"btn.create": "New",
			"need.id": "id required",
			"ph.content": "",
			"btn.saveRule": "Save",
			"skills.title": "Skills",
			"skills.hint": "After import, DSH calls it: type /name in chat to load now; the model calls the skill tool when the task matches description or whenToUse. Writing「激活」in the body does nothing.",
			"skills.hint.desktop": "This desktop host’s official skill catalog. Type /name in chat to load; the model calls the skill tool when the task matches the description.",
			"skills.empty": "No user skills",
			"btn.importZip": "Import zip",
			"btn.importFolder": "Import folder",
			"skills.importing": "Importing…",
			"saved.import": "Imported {count} skill(s)",
			"need.import": "Choose a zip or folder",
			"err.import.folder": "No files were read. Select the skill folder itself (it must contain SKILL.md).",
			"skills.pick": "Select a skill",
			"skills.invalid": "Official catalog will ignore this: invalid format",
			"skills.call.slash": "Type {cmd} in chat",
			"skills.call.model": "Model can load",
			"skills.call.modelOff": "Hidden from model",
			"skills.call.userOff": "/name disabled",
			"ph.skill.desc": "description (when to use)",
			"btn.saveSkill": "Save",
			"need.skill.id": "id must be kebab-case, e.g. code-review",
			"confirm.delete.skill": "Delete {id} from official $DSH_HOME/skills? The host will drop it from the catalog.",
			"err.skills": "Read failed: {error}",
			"err.skills.needRestart": "Skill API is not loaded. Restart this host first.",
			"btn.restart": "Restart",
			"btn.restart.busy": "Restarting…",
			"restarting": "Restarting…",
			"restarting.desktop": "Restarting the desktop app…",
			"restart.timeout": "Timed out; refresh",
			"restart.fail": "Failed: {error}",
			"restart.notStarted": "Restart did not start. This client is still open, and it will not try again by itself.",
			"restart.already": "This restart already started. It will not restart again.",
			"restart.confirm": "Apply finished. Restart to take effect.",
			"restart.confirm.desktop": "Apply finished. Restart the desktop app to take effect.",
			"restart.ask.title": "Restart now?",
			"restart.ask.body": "It is written. It takes effect in this client after a restart.",
			"restart.now": "Restart now",
			"restart.notNow": "Later",
			"restart.asarSwap": "Patches are on disk. Quitting the desktop app and moving app.asar aside; it will reopen when done. If behavior is unchanged, fully quit Harness (including tray) and Apply again.",
			"surface.web": "Web",
			"surface.desktop": "Desktop",
			"surface.gui": "GUI",
			"surface.tui": "TUI",
			"restart.incomplete": "The prompt is in. {detail}",
			"restart.incomplete.patches": "{failed} code patch(es) did not match this host (#{ids}). The prompt is unaffected",
			"restart.incomplete.flash": "CMD silence not pinned ({entry})",
			"restart.later": "Later",
			"group.prompt": "Prompt",
			"group.code": "Code",
			"group.engine": "Engine",
			"group.tools": "Tools",
			"group.compat": "0.1.5 compat",
			"group.dsh20": "0.2.0",
			"patch.1": "Global disclaimer → mandate",
			"patch.2": "Replacement disclaimer → mandate",
			"patch.3": "Scope disclaimer → mandate",
			"patch.4": "Persona session mandate",
			"patch.5": "Approval copy → full access",
			"patch.6": "Sandbox deny → allow write",
			"patch.7": "Sandbox default full access",
			"patch.8": "Approval default never",
			"patch.9": "Approval gate auto-grant",
			"patch.10": "Approval config default never",
			"patch.11": "never copy → auto-grant",
			"patch.12": "ask copy → auto-grant",
			"patch.13": "Escalation ladder exempt",
			"patch.14": "Escalation unconditional grant",
			"patch.15": "Sandbox confine passthrough",
			"patch.16": "Filesystem fence off",
			"patch.17": "Observation policy allow R/W",
			"patch.18": "Repeat-call guard off",
			"patch.19": "Tool-result pruner off",
			"patch.21": "Restore plugin-raised bash wait",
			"patch.22": "read cap raised",
			"patch.23": "subagent depth 3 → 10",
			"patch.24": "preset fetch on",
			"patch.25": "Strip official default identity (keep feature prompts)",
			"patch.26": "minimal: strip identity, open inject",
			"patch.28": "dsh-liangshen: keep dsh-purge / dshpg in phase-1",
			"patch.70": "Minimal shell drops the no-network line",
			"patch.71": "Liangshen drops the stock identity line",
			"patch.29": "dsh-tool-web: untrusted framing → usable data",
			"patch.30": "dsh-hooks-claude-code: deny→allow",
			"patch.31": "dsh-hooks-codex: deny→allow",
			"patch.32": "Web surface identity neutral",
			"patch.33": "Shell denial prompt → executable",
			"patch.34": "Sandbox hint neutralized",
			"patch.35": "Escalation never-reject",
			"patch.36": "FS escalation schema opened",
			"patch.37": "Subagent scope lock neutralized",
			"patch.38": "persona text→prefix (0.1.2 presets)",
			"patch.39": "session v0 plugin summary (mnemon)",
			"patch.40": "Keep inject when a complete prompt is set",
			"patch.42": "Settings legacy API",
			"patch.43": "Strip identity from web presets",
			"patch.45": "Official desktop update handoff",
			"patch.46": "Official update script stays ASCII",
			"patch.47": "OAuth no longer inserts Claude identity",
			"patch.48": "Shell drops extra delete caution",
			"patch.49": "OAuth no longer mimics claude-cli",
			"patch.50": "Session references are not marked untrusted",
			"patch.51": "Fresh session stays on full access",
			"patch.52": "Session log upload off by default",
			"patch.53": "Web prompt drops do-not-start",
			"patch.54": "Deliverable prompt drops extra prohibition",
			"patch.55": "Replace the first system prompt every step",
			"patch.56": "Rewind hides only the cut range",
			"patch.57": "developer role for openai/azure only, third-party gateways use system",
			"patch.58": "Rewind markers stay off the model request",
			"patch.59": "Official Auto Review no longer denies tools",
			"patch.60": "Official run_code drops approval teaching",
			"patch.61": "Official sandbox policy no longer teaches refusal",
			"patch.62": "Fail-open without approval channel (user reject kept)",
			"patch.63": "Plan mode no longer soft-blocks execution",
			"patch.64": "Stop hook no longer steers fake user text",
			"patch.65": "UserPromptSubmit deny no longer rejects turn",
			"patch.66": "Empty system section no longer ends the turn as an internal error",
			"patch.67": "A missing messages list no longer ends the turn",
			"patch.68": "Missing content after rewind no longer ends the turn",
			"patch.69": "deepseek-flash keeps the official in-history flag",
			"patch.72": "Messages system field uses the current system prompt",
			"patch.73": "Minimal preset drops stray mirror sentence",
			"patch.74": "Start/apply writes the default prompt to prompt-inject.md",
			"patch.75": "Rewind resets completed todos to pending",
			"patch.76": "Unrestricted preset: strip identity sentence",
			"patch.77": "Rewind marker drops already-sent messages",
			"patch.78": "Restore missing overlay from .bak backup",
			"patch.80": "Restore official minimal tool plugins",
			"patch.82": "Fallback DSH_PROFILE=desktop in main process",
			"patch.83": "Don't fail on signal kill (no crash dialog)",
			"patch.84": "Don't fail on code=0 clean exit (no stopped dialog)",
			"patch.85": "prompt() steer stays interrupt, not followup",
			"patch.86": "Queue steer stays steer; public steer() stays next-step",
			"patch.87": "First assemble uses the systemPrompt prepare returned",
			"patch.88": "Drop the hang after renderPrompt; inject is assemble only",
			"status.na": "Not for this host",
			"metric.sealed": "Official client found. Apply to unpack",
			"metric.sealed.count": "Sealed",
			"metric.lost": "Patches lost — Apply again",
			"metric.lost.count": "Lost",
			"status.unlocated": "Not located",
			"metric.unlocated": "This install was not found yet",
			"rewind.label": "Undo",
			"rewind.aria": "Undo",
			"rewind.busy": "Undoing…",
			"rewind.empty": "Nothing to undo",
			"rewind.fail": "Undo failed: {error}",
			"rewind.once": "Undo last step",
					"rewind.once.hint": "Withdraw the last step into a new session that keeps earlier context; the line returns to the box",
			"rewind.round": "Undo last turn",
					"rewind.round.hint": "Withdraw the last turn (and its subagents) into a new session that keeps earlier context; the line returns to the box",
			"hooksDeny.title": "Hook interception",
			"hooksDeny.bypass": "Bypass hook deny / ask (patches 30 / 31 / 64 / 65)",
			"hooksDeny.hint": "When off, your own PreToolUse / UserPromptSubmit / Stop hook deny runs as the official host wrote it. The official ask branch is a no-op; turning this off will not show an approval dialog. Click Apply and restart to write the host files.",
			"saved.hooksDeny": "Saved",
			"continue.title": "Retry / Continue",
			"continue.hint": "Failed requests auto-retry. After an abnormal stop or interrupt, use Continue or auto-resume. A manual stop never auto-continues. Counts reset after a completed turn.",
			"continue.autoRetry": "Auto-retry on failure",
			"continue.retryMax": "Retry count",
			"continue.autoContinue": "Auto-continue after interrupt",
			"continue.continueMax": "Continue count",
			"continue.text": "Continue text",
			"saved.continue": "Saved",
			"continue.label": "Continue",
			"continue.aria": "Continue after an abnormal stop",
			"continue.busy": "Continuing…",
			"continue.ready": "Continue ({left} left)",
			"continue.limit": "Continue limit reached",
			"continue.fail": "Continue failed: {error}",
		};

		const PURGE_CSS = `
.dshp-root{--dshp-display:"Songti SC","Noto Serif SC","Iowan Old Style",Palatino,"Palatino Linotype",Georgia,serif;--dshp-sans:"Yu Gothic UI","Hiragino Sans GB","Source Han Sans SC",system-ui,sans-serif;--dshp-mono:"Cascadia Mono","Sarasa Mono SC",ui-monospace,monospace;--dshp-ease:cubic-bezier(.16,1,.3,1);max-width:920px;display:flex;flex-direction:column;gap:18px;padding:16px;border-radius:12px;background:var(--dshp-bg);color:var(--dshp-ink);font-family:var(--dshp-sans)}
.dshp-root{--dshp-bg:transparent;--dshp-paper:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#f6f4ef) 74%,transparent);--dshp-ink:var(--dsw-alias-label-primary,#1a1916);--dshp-mute:color-mix(in srgb,var(--dsw-alias-label-primary,#1a1916) 74%,var(--dsw-alias-label-secondary,#5c564c));--dshp-line:color-mix(in srgb,var(--dsw-alias-border-l1,#c8c2b6) 78%,transparent);--dshp-fill:color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 14%,transparent);--dshp-accent:var(--dsw-alias-brand-primary,#3f6b52);--dshp-accent-soft:color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 18%,transparent);--dshp-ok:#1f7a45;--dshp-warn:#8a5a12;--dshp-bad:#9a3434}
.dshp-root[data-theme="white"]{color-scheme:light}
.dshp-root[data-theme="dusk"]{color-scheme:dark;--dshp-ok:#8fd0a8;--dshp-warn:#e4c48a;--dshp-bad:#f0b4b4}
.dshp-toolbar{display:flex;align-items:center;justify-content:flex-end;gap:8px}
.dshp-switch{display:inline-flex;border:1px solid var(--dshp-line);border-radius:999px;overflow:hidden;background:var(--dshp-paper)}
.dshp-switch button{appearance:none;border:0;background:transparent;color:var(--dshp-mute);font:12px/1 var(--dshp-sans);padding:6px 14px;cursor:pointer}
.dshp-switch button.is-on{background:var(--dshp-accent-soft);color:var(--dshp-ink)}
.dshp-switch button:focus-visible{outline:2px solid var(--dshp-accent);outline-offset:-2px}
.dshp-panel{border:1px solid var(--dshp-line);background:var(--dshp-paper);border-radius:10px;padding:18px 18px 16px}
.dshp-kicker{font-family:var(--dshp-mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dshp-mute);margin:0 0 4px}
.dshp-title{font-family:var(--dshp-display);font-size:20px;font-weight:500;letter-spacing:.02em;line-height:1.3;margin:0;color:var(--dshp-ink)}
.dshp-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.dshp-sub{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:20px 0 10px}
.dshp-sub h4{margin:0;font-family:var(--dshp-display);font-size:15px;font-weight:500}
.dshp-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:14px}
.dshp-metric{border:1px solid var(--dshp-line);background:var(--dshp-bg);padding:12px;min-height:68px;display:flex;flex-direction:column;gap:4px;border-radius:8px}
.dshp-metric b{font-family:var(--dshp-display);font-size:18px;font-weight:500;line-height:1.2}
.dshp-metric span{font-size:11px;color:var(--dshp-mute)}
.dshp-bar{height:3px;border-radius:99px;background:var(--dshp-line);overflow:hidden;margin:8px 0 14px}
.dshp-bar>i{display:block;height:100%;background:var(--dshp-accent);width:0;transition:width .4s var(--dshp-ease)}
.dshp-group{border:1px solid var(--dshp-line);margin:0 0 8px;background:var(--dshp-bg);border-radius:8px;overflow:hidden}
.dshp-group-h{width:100%;display:flex;align-items:center;gap:10px;padding:9px 12px;border:0;background:transparent;color:inherit;cursor:pointer;font:inherit;text-align:left}
.dshp-group-h:hover{background:var(--dshp-fill)}
.dshp-group-h:focus-visible{outline:2px solid var(--dshp-accent);outline-offset:-2px}
.dshp-group-h strong{font-family:var(--dshp-display);font-size:14px;font-weight:500}
.dshp-group-h em{font-style:normal;font-size:12px;color:var(--dshp-mute);flex:1}
.dshp-count{font-family:var(--dshp-mono);font-size:12px;color:var(--dshp-mute)}
.dshp-table{width:100%;border-collapse:collapse;font-size:12.5px}
.dshp-table th{text-align:left;font-weight:500;font-size:11px;letter-spacing:.06em;color:var(--dshp-mute);padding:7px 12px;border-bottom:1px solid var(--dshp-line)}
.dshp-table td{padding:8px 12px;border-bottom:1px solid var(--dshp-line);vertical-align:middle}
.dshp-table tr:last-child td{border-bottom:0}
.dshp-table tr.is-on td{background:var(--dshp-accent-soft)}
.dshp-id{font-family:var(--dshp-mono);opacity:.75;width:42px}
.dshp-actions{text-align:right;white-space:nowrap}
.dshp-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dshp-row+.dshp-row{margin-top:10px}
.dshp-pill{display:inline-flex;align-items:center;gap:6px;font-family:var(--dshp-mono);font-size:11px;padding:2px 8px;border:1px solid var(--dshp-line);border-radius:99px;line-height:1.6;background:var(--dshp-bg)}
.dshp-pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.dshp-pill.is-ok{color:var(--dshp-ok);border-color:color-mix(in srgb,var(--dshp-ok) 30%,var(--dshp-line))}
.dshp-pill.is-wait{color:var(--dshp-warn);border-color:color-mix(in srgb,var(--dshp-warn) 30%,var(--dshp-line))}
.dshp-pill.is-miss{color:var(--dshp-mute)}
.dshp-pill.is-bad{color:var(--dshp-bad)}
.dshp-btn{appearance:none;font-family:var(--dshp-sans);font-size:13px;font-weight:500;min-height:34px;padding:0 14px;border-radius:8px;border:1px solid transparent;cursor:pointer;transition:background .15s var(--dshp-ease),opacity .15s var(--dshp-ease)}
.dshp-btn:disabled{opacity:.45;cursor:not-allowed}
.dshp-btn:focus-visible{outline:2px solid var(--dshp-accent);outline-offset:2px}
.dshp-btn-primary{background:var(--dshp-accent-soft);color:var(--dshp-ink);border-color:color-mix(in srgb,var(--dshp-accent) 35%,var(--dshp-line))}
.dshp-btn-primary:hover:not(:disabled){background:color-mix(in srgb,var(--dshp-accent) 22%,var(--dshp-bg))}
.dshp-btn-ghost{background:transparent;color:var(--dshp-ink);border-color:var(--dshp-line)}
.dshp-btn-danger{background:transparent;color:var(--dshp-bad);border-color:color-mix(in srgb,var(--dshp-bad) 40%,var(--dshp-line))}
.dshp-btn-solid-danger{background:color-mix(in srgb,var(--dshp-bad) 16%,var(--dshp-bg));color:var(--dshp-bad);border-color:color-mix(in srgb,var(--dshp-bad) 30%,var(--dshp-line))}
.dshp-btn-tiny{min-height:28px;padding:0 10px;font-size:12px}
.dshp-field,.dshp-area{width:100%;box-sizing:border-box;font:13px/1.55 var(--dshp-mono);padding:8px 10px;background:var(--dshp-bg);color:var(--dshp-ink);border:1px solid var(--dshp-line);border-radius:8px}
.dshp-field{width:auto;min-width:140px}
.dshp-cr-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:8px 0 0;font-size:13px}
.dshp-cr-row label{display:inline-flex;align-items:center;gap:6px;color:var(--dshp-ink)}
.dshp-cr-num{width:64px;min-width:64px;height:28px;padding:0 8px}
.dshp-cr-text{width:120px;min-width:88px;height:28px;padding:0 8px}
.dshp-ver{width:100%;min-width:0;max-width:none;height:32px;padding:0 10px;font-size:12px}
.dshp-rel{margin:0 0 14px}
.dshp-now{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin:0 0 4px}
.dshp-now-label{font-family:var(--dshp-mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dshp-mute)}
.dshp-now-ver{font-family:var(--dshp-display);font-size:20px;font-weight:500;letter-spacing:.01em}
.dshp-now-mark{display:inline-flex;align-items:center;margin-left:6px;padding:1px 7px;border-radius:99px;font-family:var(--dshp-mono);font-size:11px;font-style:normal;font-weight:500;line-height:1.5;color:var(--dshp-ok);border:1px solid color-mix(in srgb,var(--dshp-ok) 38%,var(--dshp-line));background:color-mix(in srgb,var(--dshp-ok) 14%,var(--dshp-bg))}
.dshp-editions{display:flex;flex-direction:column;margin:10px 0 0;border-top:1px solid var(--dshp-line)}
.dshp-edition{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--dshp-line)}
.dshp-edition-name{display:inline-flex;align-items:center;gap:0;font-family:var(--dshp-display);font-size:15px;font-weight:500;white-space:nowrap}
.dshp-edition.is-on .dshp-edition-name{color:var(--dshp-ink)}
.dshp-edition:not(.is-on) .dshp-edition-name{color:var(--dshp-mute)}
.dshp-edition .dshp-btn{min-width:118px}
.dshp-rel .dshp-notice{display:block;margin-top:8px;min-height:16px}
@media (max-width:560px){.dshp-edition{grid-template-columns:1fr auto;grid-template-areas:"name btn" "sel sel"}.dshp-edition-name{grid-area:name}.dshp-edition .dshp-ver{grid-area:sel}.dshp-edition .dshp-btn{grid-area:btn}}
.dshp-area{min-height:220px;resize:vertical}
.dshp-field:focus,.dshp-area:focus{outline:none;border-color:var(--dshp-accent);box-shadow:0 0 0 3px var(--dshp-accent-soft)}
.dshp-field:disabled,.dshp-area:disabled{opacity:.5}
.dshp-ask{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px;padding:10px 12px;border:1px solid var(--dshp-line);border-radius:8px;background:var(--dshp-bg);font-size:13px}
.dshp-modal-bg{position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:20px;background:color-mix(in srgb,var(--dshp-ink) 28%,transparent)}
.dshp-modal{width:min(420px,100%);background:var(--dshp-paper);color:var(--dshp-ink);border:1px solid var(--dshp-line);border-radius:12px;padding:20px 20px 16px;box-shadow:0 16px 40px color-mix(in srgb,var(--dshp-ink) 18%,transparent)}
.dshp-modal h4{margin:0 0 8px;font-family:var(--dshp-display);font-size:18px;font-weight:500}
.dshp-modal p{margin:0 0 16px;font-size:13.5px;line-height:1.55}
.dshp-modal-ops{display:flex;justify-content:flex-end;gap:8px}
.dshp-restart-mask{position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.62);font-family:"Yu Gothic UI","Hiragino Sans GB","Source Han Sans SC","Microsoft YaHei UI",system-ui,sans-serif}
.dshp-restart-card{width:min(420px,100%);box-sizing:border-box;padding:22px 22px 18px;border-radius:14px;background:var(--dsw-alias-bg-layer-1,#fffcf7);color:var(--dsw-alias-label-primary,#16140f);border:1px solid var(--dsw-alias-border-l1,#c9c3b6);box-shadow:0 18px 50px rgba(0,0,0,.35)}
.dshp-restart-card h4{margin:0 0 10px;font-family:inherit;font-size:20px;font-weight:650;line-height:1.35;color:inherit}
.dshp-restart-card p{margin:0 0 18px;font-size:16px;font-weight:500;line-height:1.65;color:inherit}
.dshp-restart-card .dshp-modal-ops{display:flex;justify-content:flex-end;gap:10px}
.dshp-restart-card .dshp-btn{min-height:38px;padding:0 16px;font-size:15px;font-weight:650;color:var(--dsw-alias-label-primary,#16140f);background:var(--dsw-alias-bg-layer-2,#fff);border:1px solid var(--dsw-alias-border-l1,#c9c3b6)}
.dshp-restart-card .dshp-btn-primary,.dshp-restart-card .dshp-btn-primary:hover:not(:disabled){color:#fff;background:#2f6b4f;border-color:#2f6b4f}
body[data-ds-dark-theme] .dshp-restart-card,.dshp-restart-mask[data-theme="dusk"] .dshp-restart-card{background:#1c1e24;color:#f4f1ea;border-color:#5a5e68}
body[data-ds-dark-theme] .dshp-restart-card .dshp-btn,.dshp-restart-mask[data-theme="dusk"] .dshp-restart-card .dshp-btn{color:#f4f1ea;background:#2a2d34;border-color:#5a5e68}
body[data-ds-dark-theme] .dshp-restart-card .dshp-btn-primary,body[data-ds-dark-theme] .dshp-restart-card .dshp-btn-primary:hover:not(:disabled),.dshp-restart-mask[data-theme="dusk"] .dshp-restart-card .dshp-btn-primary,.dshp-restart-mask[data-theme="dusk"] .dshp-restart-card .dshp-btn-primary:hover:not(:disabled){color:#fff;background:#3d8f68;border-color:#3d8f68}
.dshp-notice{font-size:12.5px;line-height:1.4}
.dshp-notice.is-ok{color:var(--dshp-ok)}
.dshp-notice.is-bad{color:var(--dshp-bad)}
.dshp-skel{height:12px;border-radius:6px;background:linear-gradient(90deg,var(--dshp-fill),var(--dshp-line),var(--dshp-fill));background-size:200% 100%;animation:dshp-pulse 1.2s ease-in-out infinite}
.dshp-active{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 12px;margin-bottom:12px;border:1px solid var(--dshp-line);background:var(--dshp-bg);border-radius:8px}
.dshp-active b{font-family:var(--dshp-display);font-weight:500}
.dshp-empty{padding:28px 12px;font-size:13px;color:var(--dshp-mute);text-align:center}
.dshp-split{display:flex;flex-direction:column;gap:12px}
.dshp-rulelist{display:flex;flex-direction:column;border:1px solid var(--dshp-line);border-radius:8px;background:var(--dshp-bg);overflow:hidden}
.dshp-rulebody{max-height:240px;overflow:auto}
.dshp-ruleitem{display:flex;align-items:center;gap:12px;width:100%;padding:10px 12px;border:0;border-bottom:1px solid var(--dshp-line);background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}
.dshp-ruleitem:hover{background:var(--dshp-fill)}
.dshp-ruleitem.is-edit{background:var(--dshp-accent-soft)}
.dshp-rule-main{flex:1;min-width:0}
.dshp-rule-name{display:flex;align-items:center;gap:8px;font-family:var(--dshp-display);font-size:14px;line-height:1.35}
.dshp-rule-meta{display:block;margin-top:3px;font-family:var(--dshp-mono);font-size:11px;color:var(--dshp-mute)}
.dshp-rule-ops{display:flex;flex-direction:row;align-items:center;gap:6px;flex-shrink:0}
.dshp-create{display:flex;flex-direction:column;gap:6px;padding:10px 12px;border-top:1px solid var(--dshp-line);background:var(--dshp-paper)}
.dshp-create-row{display:flex;gap:6px;align-items:center}
.dshp-create .dshp-field{flex:1;min-width:0;width:auto}
.dshp-editor{display:flex;flex-direction:column;gap:10px;min-width:0;border:1px solid var(--dshp-line);border-radius:8px;background:var(--dshp-bg);padding:12px;min-height:320px}
.dshp-editor .dshp-area{flex:1;min-height:240px}
.dshp-editor-empty{flex:1;display:flex;align-items:center;justify-content:center;color:var(--dshp-mute);font-size:13px;min-height:160px}
.dshp-block{padding:14px 0;border-top:1px solid var(--dshp-line)}
.dshp-block-head{display:flex;align-items:center;gap:10px;margin:0 0 8px}
.dshp-block-head h4{margin:0;font-family:var(--dshp-display);font-size:14px;font-weight:500;flex:1;color:var(--dshp-ink)}
.dshp-block-hint{margin:8px 0 0;font-size:12px;line-height:1.55;color:var(--dshp-mute)}
.dshp-policy-row{display:flex;align-items:center;gap:10px}
.dshp-policy-row>label{font-size:12px;color:var(--dshp-mute);flex:0 0 auto}
.dshp-cwd-path{margin:0 0 8px;font-family:var(--dshp-mono);font-size:11px;color:var(--dshp-mute);word-break:break-all;line-height:1.5}
.dshp-cwd-list{display:flex;flex-direction:column;border:1px solid var(--dshp-line);border-radius:8px;background:var(--dshp-bg);overflow:hidden}
.dshp-cwd-item{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-bottom:1px solid var(--dshp-line);cursor:pointer;margin:0}
.dshp-cwd-item:last-child{border-bottom:0}
.dshp-cwd-item:hover{background:var(--dshp-fill)}
.dshp-cwd-item.is-on{background:var(--dshp-accent-soft)}
.dshp-cwd-item input{margin:3px 0 0;flex:0 0 auto}
.dshp-cwd-main{flex:1;min-width:0}
.dshp-cwd-name{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:var(--dshp-display);font-size:13.5px;line-height:1.35;color:var(--dshp-ink)}
.dshp-cwd-badge{font-family:var(--dshp-mono);font-size:10px;letter-spacing:.04em;text-transform:uppercase;padding:1px 7px;border-radius:99px;border:1px solid var(--dshp-line);color:var(--dshp-mute);line-height:1.6}
.dshp-cwd-size{font-family:var(--dshp-mono);font-size:11px;color:var(--dshp-mute)}
.dshp-cwd-sub{margin-top:3px;font-family:var(--dshp-mono);font-size:11px;color:var(--dshp-mute);word-break:break-all}
.dshp-cwd-prev{margin-top:4px;font-size:11px;line-height:1.5;color:var(--dshp-mute);max-height:34px;overflow:hidden}
@keyframes dshp-pulse{0%{background-position:200% 0}100%{background-position:-200% 0}}
@media (max-width:640px){.dshp-metrics{grid-template-columns:1fr}.dshp-ruleitem{flex-wrap:wrap}.dshp-rule-ops{width:100%;justify-content:flex-end}}
@media (prefers-reduced-motion:reduce){.dshp-btn,.dshp-bar>i{transition:none}.dshp-skel{animation:none}}

.dshp-dock{position:fixed;top:12px;right:12px;z-index:10050;display:flex;flex-direction:column;width:var(--dshp-dock-w,620px);height:var(--dshp-dock-h,72vh);min-width:380px;min-height:320px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);box-sizing:border-box;background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,var(--dshp-paper,#1c1c1c)) 52%,transparent);backdrop-filter:blur(22px) saturate(1.35);-webkit-backdrop-filter:blur(22px) saturate(1.35);border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,var(--dshp-line,#555)) 65%,transparent);border-radius:12px;box-shadow:0 18px 48px color-mix(in srgb,#000 30%,transparent),0 0 0 1px color-mix(in srgb,#fff 6%,transparent);pointer-events:auto;color:var(--dsw-alias-label-primary,var(--dshp-ink,#f2f2f2));overflow:visible}
.dshp-dock[data-open="0"]{display:none}
.dshp-launch{position:fixed;right:16px;bottom:16px;z-index:10040;appearance:none;display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;border:1px solid color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 55%,transparent);border-radius:999px;background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#1c1c1c) 72%,transparent);color:var(--dsw-alias-label-primary,#f2f2f2);cursor:pointer;font:13px/1 inherit;box-shadow:0 8px 22px color-mix(in srgb,#000 28%,transparent);pointer-events:auto}
.dshp-launch:hover{border-color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 18%,transparent)}
.dshp-launch[data-open="1"],.dshp-launch[data-hide="1"]{display:none}
.dshp-dock-head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,var(--dshp-line,#555)) 55%,transparent);background:transparent;cursor:grab;user-select:none;touch-action:none;color:var(--dsw-alias-label-primary,var(--dshp-ink,#f2f2f2));border-radius:12px 12px 0 0}
.dshp-dock-head:active{cursor:grabbing}
.dshp-dock-head b{font-size:14px;font-weight:600;color:inherit;text-shadow:0 1px 0 color-mix(in srgb,#000 18%,transparent)}
.dshp-dock-head button{cursor:pointer;color:inherit;background:color-mix(in srgb,var(--dsw-alias-bg-layer-2,rgba(127,127,127,.18)) 55%,transparent)}
.dshp-dock-tabs{display:flex;gap:4px;padding:0 12px;border-bottom:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,var(--dshp-line,#555)) 55%,transparent);background:transparent}
.dshp-dock-tab{appearance:none;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--dsw-alias-label-secondary,var(--dshp-mute,#b8b4ac));border-radius:0;padding:10px 14px 8px;margin-bottom:-1px;cursor:pointer;font:13px/1.2 inherit;text-shadow:0 1px 0 color-mix(in srgb,#000 12%,transparent)}
.dshp-dock-tab:hover{color:var(--dsw-alias-label-primary,var(--dshp-ink,#f2f2f2))}
.dshp-dock-tab.on{color:var(--dsw-alias-label-primary,var(--dshp-ink,#f2f2f2));font-weight:600;border-bottom-color:var(--dsw-alias-brand-primary,#6dbf8c);background:transparent}
.dshp-dock-body{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;background:transparent;border-radius:0 0 12px 12px}
.dshp-dock-body .dshp-root{max-width:none;height:100%;flex:1;min-height:0;overflow:auto;background:transparent!important;--dshp-bg:transparent;--dshp-paper:color-mix(in srgb,var(--dshp-ink) 7%,transparent);--dshp-fill:color-mix(in srgb,var(--dshp-ink) 6%,transparent);--dshp-line:color-mix(in srgb,var(--dshp-ink) 20%,transparent);--dshp-accent-soft:color-mix(in srgb,var(--dshp-accent) 22%,transparent)}
.dshp-dock-body .dshp-panel,.dshp-dock-body .dshp-metric,.dshp-dock-body .dshp-group,.dshp-dock-body .dshp-editor,.dshp-dock-body .dshp-active,.dshp-dock-body .dshp-ask,.dshp-dock-body .dshp-create,.dshp-dock-body .dshp-rulelist,.dshp-dock-body .dshp-table,.dshp-dock-body .dshp-ruleitem,.dshp-dock-body .dshp-cwd-list,.dshp-dock-body .dshp-cwd-item{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#f7f4ee) 74%,transparent)!important;border-color:color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 32%,transparent)!important;color:var(--dshp-ink)!important;box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 32%,transparent);backdrop-filter:blur(16px) saturate(1.3);-webkit-backdrop-filter:blur(16px) saturate(1.3)}
.dshp-dock-body .dshp-field,.dshp-dock-body .dshp-area{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 88%,transparent)!important;color:var(--dshp-ink)!important;border-color:color-mix(in srgb,var(--dsw-alias-border-l1,#8a8478) 72%,transparent)!important}
.dshp-dock-body select.dshp-field,.dshp-dock-body .dshp-field.dshp-ver{background:var(--dsw-alias-bg-layer-1,#fff)!important;color:var(--dshp-ink)!important;color-scheme:inherit}
.dshp-dock[data-theme="white"] select.dshp-field option,.dshp-dock[data-theme="white"] .dshp-field.dshp-ver option{background:#fff;color:#16140f}
.dshp-dock[data-theme="dusk"] select.dshp-field option,.dshp-dock[data-theme="dusk"] .dshp-field.dshp-ver option{background:#1b1d22;color:#f4f1ea}
.dshp-dock-body .dshp-title,.dshp-dock-body .dshp-sub h4,.dshp-dock-body .dshp-group-h strong,.dshp-dock-body .dshp-metric b,.dshp-dock-body .dshp-rule-name{font-family:inherit;font-weight:650;letter-spacing:0;color:var(--dshp-ink)!important;text-shadow:none}
.dshp-dock-body .dshp-mute,.dshp-dock-body .dshp-kicker,.dshp-dock-body .dshp-metric span,.dshp-dock-body .dshp-group-h em,.dshp-dock-body .dshp-count,.dshp-dock-body .dshp-rule-meta,.dshp-dock-body .dshp-hint{color:var(--dshp-mute)!important;font-weight:500;text-shadow:none}
.dshp-dock-body .rt-dock{position:relative;inset:auto;width:100%!important;height:100%;max-width:none!important;flex:1;min-height:0;min-width:0;display:flex!important;flex-direction:column;box-shadow:none;border:0;transform:none!important;opacity:1!important;pointer-events:auto!important;background:transparent!important}
.dshp-dock-body .rt-grip{display:none!important}
.dshp-dock-body .rt-embedded>.rt-head,.dshp-dock-body .rt-tabs,.dshp-dock-body .rt-foot{flex:none}
.dshp-dock-body .rt-body{flex:1;min-height:0;overflow:hidden!important;background:transparent!important}
.dshp-dock-body .rt-main{min-height:0;flex:1;overflow:hidden}
.dshp-dock-body .rt-pane{min-height:0;overflow:auto!important}
.dshp-dock-body .rt-embedded>.rt-head{padding:8px 12px}
.dshp-dock-body .rt-embedded>.rt-head .rt-title{font-size:14px;letter-spacing:0}
.dshp-dock-body .rt-tabs{gap:2px;padding:6px 10px 0;flex-wrap:wrap}
.dshp-dock-body .rt-tab{border-radius:0;border-bottom:2px solid transparent;margin-bottom:-1px;padding:8px 9px 7px;background:transparent;font-size:14px}
.dshp-dock-body .rt-tab.on{border-bottom-color:var(--dsw-alias-brand-primary,#6d8f78);background:transparent;font-weight:650}
.dshp-dock-body .rt-row:hover,.dshp-dock-body .rt-item:hover,.dshp-dock-body .rt-item.on,.dshp-dock-body .rt-seg:hover,.dshp-dock-body .rt-seg.on,.dshp-dock-body .rt-vrow:hover,.dshp-dock-body .rt-score-row:hover{background:var(--rt-surf-2)!important}
body:not([data-ds-dark-theme]) .dshp-auth-modal{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fffcf7) 92%,transparent);color:var(--dsw-alias-label-primary,#1a1916);border-color:color-mix(in srgb,var(--dsw-alias-border-l1,#c9c3b6) 80%,transparent);backdrop-filter:blur(18px) saturate(1.3);-webkit-backdrop-filter:blur(18px) saturate(1.3)}
body:not([data-ds-dark-theme]) .dshp-auth-legal{background:color-mix(in srgb,var(--dsw-alias-bg-layer-2,#f3f0e8) 90%,transparent);color:var(--dsw-alias-label-primary,#1a1916);border-color:color-mix(in srgb,var(--dsw-alias-border-l1,#c9c3b6) 80%,transparent)}
body:not([data-ds-dark-theme]) .dshp-auth-warn{background:color-mix(in srgb,#f5e6c8 88%,transparent);color:#6b4a10}
body:not([data-ds-dark-theme]) .dshp-auth-ops button{border-color:var(--dsw-alias-border-l1,#c9c3b6);color:var(--dsw-alias-label-primary,#1a1916);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 88%,transparent)}
body:not([data-ds-dark-theme]) .dshp-auth-ops button.primary{background:var(--dsw-alias-brand-primary,#3f6b52);border-color:var(--dsw-alias-brand-primary,#3f6b52);color:#fff}
.dshp-dock-resize,.dshp-dock-resize-l,.dshp-dock-resize-r,.dshp-dock-resize-b{position:absolute;z-index:60;pointer-events:auto;touch-action:none}
.dshp-dock-resize{right:0;bottom:0;width:22px;height:22px;cursor:nwse-resize;background:linear-gradient(135deg,transparent 46%,color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 75%,transparent) 46%);border-radius:0 0 12px 0;opacity:.95}
.dshp-dock-resize-l{left:-2px;top:0;bottom:0;width:10px;cursor:ew-resize;background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 18%,transparent)}
.dshp-dock-resize-l:hover,.dshp-dock-resize-r:hover{background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 42%,transparent)}
.dshp-dock-resize-r{right:-2px;top:0;bottom:22px;width:10px;cursor:ew-resize;background:transparent}
.dshp-dock-resize-b{left:10px;right:22px;bottom:-2px;height:10px;cursor:ns-resize;background:transparent}
.dshp-dock-resize-b:hover{background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 35%,transparent)}
.dshp-auth-mask{position:fixed;inset:0;z-index:10100;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;padding:20px;pointer-events:auto}
.dshp-env-gate{z-index:10200}
.dshp-auth-modal{width:min(680px,100%);max-height:min(88vh,820px);display:flex;flex-direction:column;gap:10px;padding:16px;border:1px solid var(--dsw-alias-border-l1,#333);border-radius:12px;background:var(--dsw-alias-bg-layer-1,#1a1a1a);color:var(--dsw-alias-label-primary,#eee)}
.dshp-auth-modal h2{margin:0;font-size:16px;font-weight:600}
.dshp-auth-warn{padding:8px 10px;border-radius:8px;background:#3a2e18;color:#f0d48a;font-size:13px}
.dshp-auth-legal{overflow:auto;height:300px;margin:0;padding:10px 12px;border:1px solid var(--dsw-alias-border-l1,#333);border-radius:8px;background:#121212;font-size:13px;line-height:1.55}
.dshp-auth-legal h3{margin:14px 0 4px;font-size:13px}
.dshp-auth-legal h3:first-child{margin-top:0}
.dshp-auth-legal p{margin:0 0 8px}
.dshp-auth-checks{display:flex;flex-direction:column;gap:8px;font-size:13px}
.dshp-auth-checks label{display:flex;gap:8px;align-items:flex-start}
.dshp-auth-checks label.locked{opacity:.45}
.dshp-auth-ops{display:flex;justify-content:flex-end;gap:8px}
.dshp-auth-ops button,.dshp-dock-head button{appearance:none;border:1px solid var(--dsw-alias-border-l1,#444);background:transparent;color:inherit;border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit}
.dshp-auth-ops button.primary{background:#2a4033;border-color:#8fbf9a}
.dshp-auth-ops button:disabled{opacity:.45;cursor:default}
.dshp-icon-btn{appearance:none;display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 10px;border:1px solid color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 45%,transparent);border-radius:8px;background:transparent;color:var(--dsw-alias-label-secondary,currentColor);cursor:pointer;font:13px/1 inherit;white-space:nowrap;flex:0 0 auto}
.dshp-icon-btn:hover{border-color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 12%,transparent);color:var(--dsw-alias-label-primary,currentColor)}
.dshp-icon-btn.on{border-color:var(--dsw-alias-brand-primary,#6dbf8c);color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 16%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 28%,transparent)}
.dshp-hbtn{appearance:none;display:inline-flex;flex:0 0 auto;align-items:center;gap:6px;border:1px solid color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 55%,transparent);background:transparent;color:var(--dsw-alias-label-secondary,currentColor);cursor:pointer;font:12px/1 inherit;padding:5px 10px;border-radius:8px;white-space:nowrap}
.dshp-hbtn:hover{border-color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 12%,transparent);color:var(--dsw-alias-label-primary,currentColor)}
.dshp-hbtn.on{border-color:var(--dsw-alias-brand-primary,#6dbf8c);color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 18%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 32%,transparent)}
.dshp-live-dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--dsw-alias-brand-primary,#6dbf8c);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 28%,transparent)}
.dshp-hero-chip{display:inline-flex;align-items:center;margin-left:6px;flex:0 0 auto}

/* VM workbench: scoped light surface, independent of host theme tokens. */
.dshp-vm-overlay{position:fixed;inset:0;z-index:100050;display:grid;place-items:center;padding:24px;background:#15223b66;backdrop-filter:blur(5px);box-sizing:border-box;isolation:isolate}
.dshp-vm-panel{color-scheme:light;--vm-ink:#17253c;--vm-muted:#5a687d;--vm-line:#e2e8f0;--vm-blue:#2459d8;color:var(--vm-ink);background:#fff;border:1px solid #ffffffc9;border-radius:24px;width:min(880px,100%);max-height:calc(100dvh - 48px);overflow:auto;overscroll-behavior:contain;box-sizing:border-box;box-shadow:0 28px 90px #0c193d38;font:14px/1.55 "Avenir Next","PingFang SC","Microsoft YaHei",sans-serif}
.dshp-vm-panel *{box-sizing:border-box}
.dshp-vm-head{display:flex;align-items:center;gap:14px;padding:26px 28px 22px;border-bottom:1px solid var(--vm-line)}
.dshp-vm-mark{display:grid;place-items:center;flex:none;width:44px;height:44px;background:#edf3ff;border:1px solid #d7e3ff;border-radius:14px;color:#2459d8;font:700 21px/1 Menlo,Consolas,monospace}
.dshp-vm-title{flex:1;min-width:0}.dshp-vm-eyebrow{font-size:10px;font-weight:700;letter-spacing:.16em;color:#65768f}.dshp-vm-title h2{margin:2px 0 0;font-size:22px;letter-spacing:-.035em;line-height:1.3;font-weight:650;color:var(--vm-ink)}
.dshp-vm-panel p{margin:0}.dshp-vm-meta{display:flex;align-items:flex-start;gap:14px;margin:22px 28px 0;padding:16px 18px;background:#f5f7fb;border:1px solid var(--vm-line);border-radius:14px}.dshp-vm-meta-label{font-size:11px;color:var(--vm-muted);margin-bottom:5px}.dshp-vm-meta-main{flex:1;min-width:0}.dshp-vm-path{display:block;overflow-wrap:anywhere;white-space:normal;font:12px/1.7 Menlo,Consolas,monospace;color:#33455f}.dshp-vm-local{font-size:10px;white-space:nowrap;color:#31578e;background:#e7eefb;border-radius:6px;padding:3px 7px}
.dshp-vm-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:28px;padding:24px 28px 28px}.dshp-vm-section{min-width:0}.dshp-vm-section+ .dshp-vm-section{border-left:1px solid var(--vm-line);padding-left:28px}.dshp-vm-section-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}.dshp-vm-section h3{font-size:15px;font-weight:650;letter-spacing:-.02em;margin:0}.dshp-vm-count{font:11px/1.5 Menlo,Consolas,monospace;color:#60708a;background:#eef2f8;padding:1px 7px;border-radius:6px}.dshp-vm-help{color:var(--vm-muted);font-size:12px;line-height:1.8;margin-bottom:16px!important}.dshp-vm-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.dshp-vm-panel .dshp-vm-btn{appearance:none;display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:36px;padding:8px 13px;border:1px solid #d8e0ed;border-radius:9px;background:#fff;color:#33455f;font:600 12px/1.35 "Avenir Next","PingFang SC",sans-serif;cursor:pointer;transition:background .15s,border-color .15s,box-shadow .15s}
.dshp-vm-panel .dshp-vm-btn:hover:not(:disabled){background:#f0f4fb;border-color:#a5b8d6}.dshp-vm-panel .dshp-vm-btn.primary{background:var(--vm-blue);border-color:var(--vm-blue);color:#fff;box-shadow:0 2px 4px #2459d81a}.dshp-vm-panel .dshp-vm-btn.primary:hover:not(:disabled){background:#1949be;border-color:#1949be}.dshp-vm-panel .dshp-vm-btn.quiet{background:transparent;border-color:transparent;color:#63728a}.dshp-vm-panel .dshp-vm-btn:disabled{color:#7b879a;background:#f3f5f8;border-color:#e6ebf2;cursor:default;box-shadow:none}
.dshp-vm-panel :is(button,input):focus-visible{outline:3px solid #2459d8;outline-offset:3px}.dshp-vm-terminals{display:grid;gap:10px;margin-top:16px}.dshp-vm-terminal{padding:14px;border:1px solid var(--vm-line);border-radius:12px;background:#fff}.dshp-vm-terminal.is-ready{border-color:#c4d7cf;background:#fbfefc}.dshp-vm-terminal-head{display:flex;align-items:flex-start;gap:8px;margin-bottom:9px}.dshp-vm-terminal-name{min-width:0;flex:1;font-size:13px;overflow-wrap:anywhere}.dshp-vm-state{display:inline-flex;align-items:center;gap:5px;flex:none;font-size:10px;font-weight:600;padding:2px 7px;border-radius:5px;background:#f0f2f6;color:#5d697c}.dshp-vm-state:before{content:"";width:5px;height:5px;border-radius:50%;background:currentColor}.is-ready .dshp-vm-state{background:#e7f5ee;color:#22734d}.dshp-vm-terminal .dshp-vm-meta-label{margin:0;font-size:10px}.dshp-vm-terminal .dshp-vm-path{font-size:11px;margin:3px 0 11px}.dshp-vm-terminal .dshp-vm-btn{min-height:30px;padding:6px 10px;font-size:11px}.dshp-vm-empty{padding:24px 15px;text-align:center;background:#f8fafc;border:1px dashed #d6dfeb;border-radius:12px;color:#63728a;font-size:12px}
.dshp-vm-label{display:block;font-size:12px;font-weight:600;margin:0 0 7px}.dshp-vm-input{appearance:none;display:block;width:100%;min-height:44px;padding:11px 12px;border:1px solid #ccd6e5;border-radius:9px;background:#fbfcfe;color:#263952;font:12px/1.6 Menlo,Consolas,monospace;box-shadow:inset 0 1px 2px #15223b05}.dshp-vm-input:disabled{color:#6b788c;background:#f0f3f8}.dshp-vm-import-btn{width:100%;margin-top:12px}.dshp-vm-confirm{padding:16px;margin-top:16px;border:1px solid #c7d7f8;background:#f3f7ff;border-radius:12px}.dshp-vm-confirm h4{margin:0 0 9px;font-size:13px;font-weight:650}.dshp-vm-confirm .dshp-vm-path{padding:9px 0;color:#264674}.dshp-vm-confirm .dshp-vm-help{font-size:11px;margin-bottom:12px!important}.dshp-vm-error{margin:0 28px 24px!important;padding:12px 14px;border:1px solid #f1c5c9;border-radius:10px;background:#fff4f4;color:#a32134;font-size:12px;overflow-wrap:anywhere}.dshp-vm-footer{padding:13px 28px;background:#f8fafc;border-top:1px solid var(--vm-line);font-size:11px;color:#62718a;display:flex;justify-content:space-between;gap:12px}
.dshp-vm-launch{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap}.dshp-vm-launch>button{appearance:none!important;display:inline-flex;align-items:center;justify-content:center;min-height:30px;height:auto!important;gap:6px;padding:6px 11px!important;border:1px solid #cdd9ed!important;border-radius:8px!important;background:#f3f7ff!important;color:#2c4e85!important;font:600 12px/1.35 "Avenir Next","PingFang SC",sans-serif!important;cursor:pointer}.dshp-vm-launch>button:hover{background:#e8effe!important;border-color:#93afe0!important}.dshp-vm-launch>button:focus-visible{outline:3px solid #2459d8;outline-offset:3px}.dshp-vm-launch>button:disabled{opacity:.6;cursor:wait}
@media(max-width:700px){:has(>.dshp-hero-chip .dshp-vm-launch){flex-wrap:wrap!important}.dshp-hero-chip:has(.dshp-vm-launch){flex:1 1 100%;min-width:0;max-width:100%;margin-left:0;flex-wrap:wrap;gap:7px}.dshp-vm-launch{min-width:0;max-width:100%}}
.dshp-vm-history{margin-top:14px;border-top:1px solid var(--vm-line);padding-top:12px}.dshp-vm-history>summary{font-size:11px;color:#5a687d;cursor:pointer;padding:4px 0}.dshp-vm-history>summary:focus-visible{outline:3px solid #2459d8;outline-offset:3px}.dshp-vm-directory-list{display:grid;gap:5px;max-height:160px;overflow:auto;margin-top:10px;border:1px solid var(--vm-line);border-radius:9px;padding:6px}.dshp-vm-panel .dshp-vm-dir-choice{appearance:none;background:#f5f8fd;color:#294b7d;border:0;border-radius:6px;padding:9px 10px;font-family:inherit;font-size:12px;font-weight:600;line-height:1.5;text-align:left;overflow-wrap:anywhere;cursor:pointer}.dshp-vm-dir-choice:hover{background:#e9f0fe}.dshp-vm-field-error{color:#a32134;font-size:11px;line-height:1.7;overflow-wrap:anywhere;margin-top:6px!important}.dshp-vm-field-error:empty{display:none}
@media(max-width:700px){.dshp-vm-overlay{padding:12px}.dshp-vm-panel{border-radius:18px;max-height:calc(100dvh - 24px)}.dshp-vm-head{padding:20px;gap:11px}.dshp-vm-title h2{font-size:20px}.dshp-vm-meta{margin:16px 20px 0;padding:13px}.dshp-vm-grid{grid-template-columns:minmax(0,1fr);gap:22px;padding:20px}.dshp-vm-section+ .dshp-vm-section{border-left:0;border-top:1px solid var(--vm-line);padding:20px 0 0}.dshp-vm-footer{padding:12px 20px}.dshp-vm-error{margin:0 20px 20px!important}}
.dshp-vm-toolchain{margin:0 28px 24px;border:1px solid var(--vm-line);border-radius:12px;padding:18px;background:#fafcff}.dshp-vm-toolchain .dshp-vm-section-head{align-items:flex-start;gap:16px}.dshp-vm-toolchain h3{margin:0;font-size:14px}.dshp-vm-toolchain .dshp-vm-btn{flex-shrink:0}.dshp-vm-toolchain-rows{display:grid;gap:10px;margin-top:14px}.dshp-vm-toolchain-row{background:white;border:1px solid var(--vm-line);border-radius:9px;padding:13px}.dshp-vm-toolchain-row>div{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px}.dshp-vm-toolchain-state{font-size:10px;color:#416081;background:#edf3fb;padding:2px 6px;border-radius:5px}.dshp-vm-toolchain dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0 7px}.dshp-vm-toolchain dt{font-size:10px;color:#64758c}.dshp-vm-toolchain dd{margin:4px 0 0;font:11px/1.6 Menlo,Consolas,monospace;overflow-wrap:anywhere;color:#263c59}.dshp-vm-toolchain a{font-size:10px;color:#315b9f;text-underline-offset:3px}.dshp-vm-toolchain .dshp-vm-help{font-size:11px;margin:7px 0 0}.dshp-vm-toolchain-row strong{font-size:12px}@media(max-width:700px){.dshp-vm-toolchain{margin:0 20px 20px;padding:14px}.dshp-vm-toolchain .dshp-vm-section-head{flex-wrap:wrap}.dshp-vm-toolchain dl{grid-template-columns:minmax(0,1fr);gap:8px}}
@media(prefers-reduced-motion:reduce){.dshp-vm-panel button{transition:none}}

.dshp-hero-chip-btn{appearance:none;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 12px;border:1px solid color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 50%,transparent);border-radius:999px;background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 10%,transparent);color:var(--dsw-alias-label-primary,currentColor);cursor:pointer;font:12.5px/1 inherit;white-space:nowrap}
.dshp-hero-chip-btn:hover{border-color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 18%,transparent)}
.dshp-hero-chip-btn.on{border-color:var(--dsw-alias-brand-primary,#6dbf8c);color:var(--dsw-alias-brand-primary,#6dbf8c);background:color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 18%,transparent);box-shadow:0 0 0 1px color-mix(in srgb,var(--dsw-alias-brand-primary,#6dbf8c) 32%,transparent)}
.dshp-tab-chip{display:inline-flex;align-items:flex-end;flex:0 0 auto}
.dshp-tab-btn{appearance:none;position:relative;border:none;background:transparent;cursor:pointer;padding:0 0 9px;font:500 13px/16px inherit;color:var(--dsw-alias-label-tertiary,currentColor);white-space:nowrap}
.dshp-tab-btn:hover{color:var(--dsw-alias-label-primary,currentColor)}
.dshp-tab-btn.on{color:var(--dsw-alias-brand-primary,#6dbf8c)}
.dshp-tab-btn.on:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;border-radius:2px;background:var(--dsw-alias-brand-primary,#6dbf8c)}
/* Glass follows the host color. Weight and background opacity are kept separate: the shell is translucent, the text sits on a more solid layer. */
.dshp-dock{font-family:"Segoe UI","Microsoft YaHei UI","PingFang SC","Noto Sans SC",system-ui,sans-serif;font-size:14px;line-height:1.6;font-weight:500;-webkit-font-smoothing:antialiased;text-shadow:none}
.dshp-dock[data-theme="white"],.dshp-dock[data-theme="dusk"]{background:linear-gradient(165deg,color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 50%,transparent),color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 18%,transparent) 46%,color-mix(in srgb,var(--dsw-alias-bg-layer-2,#fff) 28%,transparent))!important;backdrop-filter:blur(26px) saturate(1.45)!important;-webkit-backdrop-filter:blur(26px) saturate(1.45)!important;color:var(--dshp-ink)!important;border:1px solid color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 36%,transparent)!important;box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 42%,transparent),0 18px 44px color-mix(in srgb,#000 18%,transparent)!important}
.dshp-dock[data-theme="dusk"]{--dshp-ink:var(--dsw-alias-label-primary,#f4f1ea);--dshp-mute:color-mix(in srgb,var(--dsw-alias-label-primary,#f4f1ea) 84%,var(--dsw-alias-label-secondary,#c9c3b8))}
.dshp-dock[data-theme="white"]{--dshp-ink:var(--dsw-alias-label-primary,#16140f);--dshp-mute:color-mix(in srgb,var(--dsw-alias-label-primary,#16140f) 76%,var(--dsw-alias-label-secondary,#3c362e))}
.dshp-dock .dshp-dock-head,.dshp-dock .dshp-dock-tabs{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,transparent) 28%,transparent)!important;color:var(--dshp-ink)!important}
.dshp-dock .dshp-dock-head,.dshp-dock .dshp-dock-head b,.dshp-dock .dshp-dock-head button,.dshp-dock .dshp-dock-tab,.dshp-dock .dshp-dock-tab.on{color:var(--dshp-ink)!important;text-shadow:none!important;font-weight:600}
.dshp-dock .dshp-dock-tab{font-size:14px}
.dshp-dock .dshp-dock-tab.on{border-bottom-color:var(--dsw-alias-brand-primary,#6d8f78)!important}
.dshp-dock-body .rt-dock{font-size:14px!important;line-height:1.6!important;font-weight:500!important;color:var(--dshp-ink)!important;--rt-ink:var(--dshp-ink);--rt-mute:var(--dshp-mute);--rt-surf:color-mix(in srgb,var(--dsw-alias-bg-layer-2,var(--dsw-alias-bg-layer-1,#fff)) 40%,transparent);--rt-surf-2:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 62%,transparent);--rt-line:color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 30%,transparent)}
.dshp-dock-body .rt-title,.dshp-dock-body .rt-tab,.dshp-dock-body .rt-tab.on,.dshp-dock-body .rt-card,.dshp-dock-body .rt-card h4,.dshp-dock-body .rt-row,.dshp-dock-body .rt-vrow,.dshp-dock-body .rt-kv,.dshp-dock-body .rt-kv b,.dshp-dock-body .rt-kv span,.dshp-dock-body .rt-mono,.dshp-dock-body .rt-empty,.dshp-dock-body .rt-foot,.dshp-dock-body .rt-tag,.dshp-dock-body .rt-item,.dshp-dock-body .rt-item-name,.dshp-dock-body .rt-item-desc,.dshp-dock-body .rt-sec-sub,.dshp-dock-body .rt-kb-sub,.dshp-dock-body .rt-seg-cidr,.dshp-dock-body .rt-seg-meta,.dshp-dock-body .rt-section,.dshp-dock-body .rt-note,.dshp-dock-body .rt-hint{color:var(--dshp-ink)!important;text-shadow:none!important;opacity:1!important}
.dshp-dock-body .rt-tab,.dshp-dock-body .rt-foot,.dshp-dock-body .rt-empty,.dshp-dock-body .rt-item-desc,.dshp-dock-body .rt-kb-sub,.dshp-dock-body .rt-kv span,.dshp-dock-body .rt-tag,.dshp-dock-body .rt-sec-sub{color:var(--dshp-mute)!important}
.dshp-dock-body .rt-card,.dshp-dock-body .rt-pane,.dshp-dock-body .rt-side,.dshp-dock-body .rt-table,.dshp-dock-body .rt-toolbar,.dshp-dock-body .rt-embedded>.rt-head,.dshp-dock-body .rt-tabs{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 72%,transparent)!important;border-color:color-mix(in srgb,var(--dsw-alias-brand-primary,#6d8f78) 28%,transparent)!important;color:var(--dshp-ink)!important;box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 26%,transparent)!important;backdrop-filter:blur(16px) saturate(1.3);-webkit-backdrop-filter:blur(16px) saturate(1.3)}
.dshp-dock-body .rt-btn,.dshp-dock-body .rt-input,.dshp-dock-body .rt-eng-select,.dshp-dock-body textarea.rt-input{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 90%,transparent)!important;color:var(--dshp-ink)!important;border-color:color-mix(in srgb,var(--dsw-alias-border-l1,#888) 70%,transparent)!important}
.dshp-dock-body .rt-btn-primary{background:var(--dsw-alias-brand-primary,#3f6b52)!important;border-color:var(--dsw-alias-brand-primary,#3f6b52)!important;color:#fff!important}
.dshp-dock[data-theme="white"] .dshp-dock-body .rt-eng-select option,.dshp-dock[data-theme="white"] .dshp-dock-body .rt-input option{background:#fff;color:#16140f}
.dshp-dock[data-theme="dusk"] .dshp-dock-body .rt-eng-select option,.dshp-dock[data-theme="dusk"] .dshp-dock-body .rt-input option{background:#1b1d22;color:#f4f1ea}
.dshp-dock-body .rt-err{font-weight:650}
.dshp-dock[data-theme="white"] .dshp-dock-body .rt-err{color:#9a3434!important}
.dshp-dock[data-theme="dusk"] .dshp-dock-body .rt-err{color:#f0b4b4!important}
.dshp-dock-body .rt-rep-http,.dshp-dock-body pre{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 84%,transparent)!important;color:var(--dshp-ink)!important;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,#888) 60%,transparent)!important}
`;

		function formatSize(bytes) {
			if (typeof bytes !== "number" || !isFinite(bytes) || bytes < 0) return "0 B";
			if (bytes < 1024) return bytes + " B";
			const kb = bytes / 1024;
			return (kb >= 100 ? Math.round(kb) : kb.toFixed(1)) + " KB";
		}

		function statusKind(st) {
			if (st === "applied" || st === "already") return "ok";
			if (st === "pending") return "wait";
			if (st === "unmatched") return "bad";
			if (st === "na") return "ok";
			if (st === "missing_file" || st === "skipped" || st === "unlocated" || st === "off") return "miss";
			return "bad";
		}

		function statusLabel(st, t) {
			if (st === "applied" || st === "already") return t("status.applied");
			if (st === "off") return t("status.skipped");
			if (st === "pending") return t("status.pending");
			if (st === "unmatched") return t("status.unmatched");
			if (st === "skipped") return t("status.skipped");
			if (st === "missing_file") return t("skip");
			if (st === "unlocated") return t("status.unlocated");
			if (st === "na") return t("status.na");
			return st || t("unknown");
		}

		function shimKind(v) {
			if (v === "patched" || v === "n/a") return "ok";
			if (v === "original") return "wait";
			if (v === "missing" || !v) return "miss";
			return "bad";
		}

		function noticeNode(notice) {
			if (!notice || notice.kind === "idle" || !notice.text) return null;
			return h("span", { className: "dshp-notice " + (notice.kind === "error" ? "is-bad" : "is-ok") }, notice.text);
		}

		function Btn(props) {
			const { kind, tiny, children, className, type, ...rest } = props;
			const cls = ["dshp-btn", kind ? "dshp-btn-" + kind : "dshp-btn-ghost", tiny ? "dshp-btn-tiny" : "", className || ""].filter(Boolean).join(" ");
			return h("button", Object.assign({ type: type || "button", className: cls }, rest), children);
		}

		function Pill({ value, label }) {
			const t = useT();
			return h("span", { className: "dshp-pill is-" + statusKind(value) }, label || statusLabel(value, t));
		}

		const LAYER_GROUP = {
			"Prompt": "prompt",
			"Code": "code",
			"Tools": "tools",
			"0.1.5 compat": "compat",
			"0.2.0 compat": "dsh20",
		};
		const GROUP_ORDER = ["prompt", "code", "tools", "compat", "dsh20"];
		/* The host may report patch layer names in the host locale. The zh dictionary
		 * still keeps those labels, so map them at runtime instead of hardcoding CJK
		 * literals in this file. */
		for (const key of GROUP_ORDER) {
			const label = zh["group." + key];
			if (label && !LAYER_GROUP[label]) LAYER_GROUP[label] = key;
		}
		function layerGroupOf(layer) {
			if (LAYER_GROUP[layer]) return LAYER_GROUP[layer];
			/* zh labels the 0.2.0 layer as "0.2.0" while the host may append a suffix. */
			return String(layer || "").startsWith(zh["group.dsh20"]) ? "dsh20" : "code";
		}

		function patchRowsOf(state) {
			if (!state || !state.ai_base) return [];
			const fromList = Array.isArray(state.patches) ? state.patches : null;
			const rows = fromList
				? fromList.map((p) => ({
					id: Number(p.id),
					ids: Array.isArray(p.ids) && p.ids.length ? p.ids.map(Number) : [Number(p.id)],
					st: p.status || "missing_file",
					layer: p.layer || "",
					title: p.title || "",
				}))
				: Object.keys(state.patch_status || {}).map((id) => ({
					id: Number(id),
					ids: [Number(id)],
					st: state.patch_status[id],
					layer: "",
					title: "",
				}));
			return rows.filter((r) => r.st && r.st !== "na" && Number.isFinite(r.id));
		}

		function patchIdLabel(r) {
			const ids = Array.isArray(r.ids) && r.ids.length ? r.ids : [r.id];
			return ids.map((id) => "#" + id).join("/");
		}

		function patchTitle(t, state, r) {
			if (r && r.title) return r.title;
			const id = r && typeof r === "object" ? r.id : r;
			const key = "patch." + id;
			const hit = t(key);
			if (hit && hit !== key) return hit;
			const names = state && state.patch_names;
			const name = names && (names[id] || names[String(id)]);
			return name || key;
		}

		function tallyPatches(rows) {
			const out = { applied: 0, pending: 0, unmatched: 0, skipped: 0, total: 0 };
			for (const row of rows || []) {
				out.total += 1;
				if (row.st === "applied" || row.st === "already") out.applied += 1;
				else if (row.st === "pending") out.pending += 1;
				else if (row.st === "unmatched") out.unmatched += 1;
				else out.skipped += 1;
			}
			return out;
		}

		function PatchGroups({ state }) {
			const t = useT();
			const [open, setOpen] = useState({});
			if (!state || !state.patch_status) return h("div", { className: "dshp-skel", style: { height: 120 } });
			const located = !!state.ai_base;
			if (!located) return null;
			const grouped = new Map();
			for (const row of patchRowsOf(state)) {
				const key = layerGroupOf(row.layer);
				if (!grouped.has(key)) grouped.set(key, []);
				grouped.get(key).push(row);
			}
			return GROUP_ORDER.filter((key) => grouped.has(key)).map((key) => {
				const rows = grouped.get(key).slice().sort((a, b) => a.id - b.id);
				if (!rows.length) return null;
				const tally = tallyPatches(rows);
				const notes = [];
				if (tally.pending) notes.push(t("metric.pendingShort", { n: tally.pending }));
				if (tally.unmatched) notes.push(t("metric.unmatchedShort", { n: tally.unmatched }));
				if (tally.skipped) notes.push(t("metric.skipShort", { n: tally.skipped }));
				const expanded = !!open[key];
				return h("div", { key: key, className: "dshp-group" },
					h("button", {
						type: "button",
						className: "dshp-group-h",
						"aria-expanded": expanded ? "true" : "false",
						onClick: () => setOpen((prev) => Object.assign({}, prev, { [key]: !prev[key] })),
					},
						h("strong", null, t("group." + key)),
						h("span", { className: "dshp-count" }, tally.applied + "/" + tally.total + (notes.length ? " · " + notes.join(" · ") : "")),
					),
					expanded ? h("table", { className: "dshp-table" },
						h("thead", null, h("tr", null,
							h("th", null, "#"),
							h("th", null, t("table.patch")),
							h("th", null, t("table.status")),
						)),
						h("tbody", null, rows.map((r) => h("tr", { key: r.ids ? r.ids.join("-") : r.id },
							h("td", { className: "dshp-id" }, patchIdLabel(r)),
							h("td", null, patchTitle(t, state, r)),
							h("td", null, h(Pill, { value: r.st })),
						))),
					) : null,
				);
			});
		}

		function HooksDenySection({ onSaved }) {
			const t = useT();
			const [cfg, setCfg] = useState(null);
			const [notice, setNotice] = useState({ kind: "idle", text: "" });
			const [busy, setBusy] = useState(false);

			useEffect(() => {
				apiJson("/dsh-purge/hooks-deny")
					.then((d) => { if (d && d.ok) setCfg({ hooksDenyBypass: d.hooksDenyBypass !== false }); })
					.catch(() => {});
			}, []);

			const save = (hooksDenyBypass) => {
				if (!cfg || busy) return;
				setCfg({ hooksDenyBypass });
				setBusy(true);
				apiJson("/dsh-purge/hooks-deny", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify({ hooksDenyBypass }),
				})
					.then((d) => {
						if (d && d.ok) {
							setCfg({ hooksDenyBypass: d.hooksDenyBypass === true });
							setNotice({ kind: "ok", text: t("saved.hooksDeny") });
							if (typeof onSaved === "function") onSaved();
						} else {
							setNotice({ kind: "error", text: t("err.save", { error: (d && d.error) || "" }) });
						}
					})
					.catch((e) => setNotice({ kind: "error", text: t("err.save", { error: e.message }) }))
					.finally(() => setBusy(false));
			};

			if (!cfg) return null;
			return h("div", { className: "dshp-cr", style: { marginTop: 12 } },
				h("div", { className: "dshp-sub" },
					h("h4", null, t("hooksDeny.title")),
					noticeNode(notice),
				),
				h("p", { className: "dshp-hint", style: { margin: "0 0 4px", color: "var(--dshp-mute)", fontSize: 12 } }, t("hooksDeny.hint")),
				h("div", { className: "dshp-cr-row" },
					h("label", null,
						h("input", {
							type: "checkbox",
							checked: cfg.hooksDenyBypass === true,
							disabled: busy,
							onChange: (e) => save(e.target.checked),
						}),
						t("hooksDeny.bypass"),
					),
				),
			);
		}

		function ContinueRetrySection() {
			const t = useT();
			const [cfg, setCfg] = useState(null);
			const [notice, setNotice] = useState({ kind: "idle", text: "" });
			const [busy, setBusy] = useState(false);

			useEffect(() => {
				apiJson("/dsh-purge/continue/settings")
					.then((d) => { if (d && d.ok) setCfg(d); })
					.catch(() => {});
			}, []);

			const save = (patch) => {
				if (!cfg || busy) return;
				const next = { ...cfg, ...patch };
				if (next.autoRetry && !(Number(next.retryMax) > 0)) next.retryMax = 3;
				if (next.autoContinue && !(Number(next.continueMax) > 0)) next.continueMax = 3;
				setCfg(next);
				setBusy(true);
				apiJson("/dsh-purge/continue/settings", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify(next),
				})
					.then((d) => {
						if (d && d.ok) {
							setCfg(d);
							setNotice({ kind: "ok", text: t("saved.continue") });
						} else {
							setNotice({ kind: "error", text: t("err.save", { error: (d && d.error) || "" }) });
						}
					})
					.catch((e) => setNotice({ kind: "error", text: t("err.save", { error: e.message }) }))
					.finally(() => setBusy(false));
			};

			if (!cfg) return null;
			return h("div", { className: "dshp-cr" },
				h("div", { className: "dshp-sub" },
					h("h4", null, t("continue.title")),
					noticeNode(notice),
				),
				h("p", { className: "dshp-hint", style: { margin: "0 0 4px", color: "var(--dshp-mute)", fontSize: 12 } }, t("continue.hint")),
				h("div", { className: "dshp-cr-row" },
					h("label", null,
						h("input", {
							type: "checkbox",
							checked: Boolean(cfg.autoRetry),
							disabled: busy,
							onChange: (e) => save({ autoRetry: e.target.checked }),
						}),
						t("continue.autoRetry"),
					),
					h("label", null,
						t("continue.retryMax"),
						h("input", {
							className: "dshp-field dshp-cr-num",
							type: "number",
							min: 0,
							max: 20,
							value: cfg.retryMax,
							disabled: busy,
							onChange: (e) => save({ retryMax: Number(e.target.value) }),
						}),
					),
				),
				h("div", { className: "dshp-cr-row" },
					h("label", null,
						h("input", {
							type: "checkbox",
							checked: Boolean(cfg.autoContinue),
							disabled: busy,
							onChange: (e) => save({ autoContinue: e.target.checked }),
						}),
						t("continue.autoContinue"),
					),
					h("label", null,
						t("continue.continueMax"),
						h("input", {
							className: "dshp-field dshp-cr-num",
							type: "number",
							min: 0,
							max: 20,
							value: cfg.continueMax,
							disabled: busy,
							onChange: (e) => save({ continueMax: Number(e.target.value) }),
						}),
					),
					h("label", null,
						t("continue.text"),
						h("input", {
							className: "dshp-field dshp-cr-text",
							type: "text",
							value: cfg.continueText || "",
							disabled: busy,
							onChange: (e) => save({ continueText: e.target.value }),
						}),
					),
				),
			);
		}

		function RestartAsk(props) {
			const node = h("div", {
				className: "dshp-restart-mask",
				"data-theme": props.theme === "dusk" ? "dusk" : "white",
				role: "dialog",
				"aria-modal": "true",
				"aria-labelledby": "dshp-restart-title",
				onClick: (e) => { if (e.target === e.currentTarget && props.onLater) props.onLater(); },
			},
				h("div", { className: "dshp-restart-card" },
					h("h4", { id: "dshp-restart-title" }, props.t("restart.ask.title")),
					h("p", null, props.t("restart.ask.body")),
					h("div", { className: "dshp-modal-ops" },
						h(Btn, { onClick: props.onLater }, props.t("restart.notNow")),
						h(Btn, { kind: "primary", onClick: props.onRestart }, props.t("restart.now")),
					),
				),
			);
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function" && typeof document !== "undefined" && document.body) {
					return rd.createPortal(node, document.body);
				}
			} catch { /* host 可能没暴露 react-dom */ }
			return node;
		}

		function PurgifySection() {
			const t = useT();
			const tRef = useRef(t);
			tRef.current = t;
			const [state, setState] = useState(null);
			const [override, setOverride] = useState("");
			const [defaultOverride, setDefaultOverride] = useState("");
			const [overrideLoaded, setOverrideLoaded] = useState(false);
			const [ownServers, setOwnServers] = useState("");
			const [ownLoaded, setOwnLoaded] = useState(false);
			const [patchBusy, setPatchBusy] = useState(false);
			const [updateBusy, setUpdateBusy] = useState(false);
			const [canApplyUpdate, setCanApplyUpdate] = useState(false);
			const [updateJob, setUpdateJob] = useState(null);
			const [askRestart, setAskRestart] = useState(false);
			const suppressRestartAsk = useRef(false);
			const [askUninstall, setAskUninstall] = useState(false);
			const [uninstallBusy, setUninstallBusy] = useState(false);
			const [notice, setNotice] = useState({ kind: "idle", text: "" });
			const [updateNotice, setUpdateNotice] = useState({ kind: "idle", text: "" });
			const [updateInfo, setUpdateInfo] = useState(null);
			const [channel, setChannel] = useState("stable");
			const [pick, setPick] = useState({ stable: "", beta: "" });
			const actionTicket = useRef(0);
			const overrideRef = useRef("");
			const defaultOverrideRef = useRef("");
			const promptSeededRef = useRef(false);
			const promptDirtyRef = useRef(false);
			const promptAreaRef = useRef(null);
			overrideRef.current = override;
			defaultOverrideRef.current = defaultOverride;

			const readPromptBox = () => {
				const node = promptAreaRef.current;
				const live = node && typeof node.value === "string" ? node.value : overrideRef.current;
				overrideRef.current = live || "";
				return overrideRef.current;
			};

			const syncPicks = (d) => {
				const versions = (d && d.versions) || [];
				const ceiling = listedCeiling(versions, d && d.localVersion);
				const next = { stable: "", beta: "" };
				for (const id of ["stable", "beta"]) {
					const list = versions.filter((item) => item.channel === id && keepListedVersion(item, ceiling));
					const hit = preferListed(list, d && d.localVersion, d && d.pin);
					next[id] = (hit && hit.ref) || "";
				}
				setPick(next);
			};

			const updateErrorText = (tr, e) => {
				const msg = String((e && e.message) || e || "");
				if (msg === "timeout" || /aborted|abort|超时/i.test(msg)) return tr("update.timeout");
				if (/\b404\b/.test(msg) || /non-json/.test(msg)) return tr("update.needRestart");
				return tr("update.fail", { error: msg });
			};

			const applyUpdateInfo = useCallback((d, tr, kind) => {
				if (d.channel) setChannel(d.channel);
				setUpdateInfo((prev) => {
					const versions = (d.versions && d.versions.length) ? d.versions : ((prev && prev.versions) || []);
					return Object.assign({}, prev || {}, d, { versions });
				});
				if (d.versions && d.versions.length) syncPicks(d);
				if (kind === "check") setCanApplyUpdate(Boolean(d.hasUpdate) && !d.error);
				else if (kind === "done" || kind === "switched" || kind === "channel") setCanApplyUpdate(false);
				const version = d.localVersion || d.localSha || "—";
				const remote = d.remoteVersion || d.remoteSha || "—";
				let text = tr("update.latest", { version });
				if (d.hasUpdate) text = tr("update.available", { remote, local: version });
				if (d.pinned && d.hasUpdate) text = tr("update.pinned", { version, remote });
				if (kind === "switched" || kind === "channel") text = tr("update.switched", { version: d.localVersion || d.remoteVersion || "—" });
				if (kind === "done") text = tr("update.done", { version: d.localVersion || d.remoteVersion || "—" });
				if (d.error) text = d.error;
				setUpdateNotice({ kind: d.ok === false || d.error ? "error" : "ok", text });
			}, []);

			const checkUpdate = useCallback((id) => {
				setUpdateBusy(true);
				setUpdateJob({ id: id || "", kind: "check" });
				const tr = tRef.current;
				setUpdateNotice({ kind: "ok", text: tr("update.checking") });
				apiJson("/dsh-purge/update")
					.then((d) => {
						if (!d || (!d.ok && !d.channel)) throw new Error((d && d.error) || "check failed");
						applyUpdateInfo(d, tr, "check");
					})
					.catch((e) => setUpdateNotice({ kind: "error", text: updateErrorText(tr, e) }))
					.finally(() => {
						setUpdateBusy(false);
						setUpdateJob(null);
					});
			}, [applyUpdateInfo]);

			const postUpdate = useCallback((body, kind, id) => {
				setUpdateBusy(true);
				setUpdateJob({ id: id || "", kind });
				const tr = tRef.current;
				setUpdateNotice({ kind: "ok", text: kind === "switched" || kind === "channel" ? tr("update.switching") : tr("update.applying") });
				return apiJson("/dsh-purge/update", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify(body || {}),
				})
					.then((d) => {
						if (!d || (d.ok === false && d.error)) throw new Error((d && d.error) || "update failed");
						applyUpdateInfo(d, tr, kind);
						if (d.needsFullQuit) {
							suppressRestartAsk.current = false;
							setAskRestart(true);
							setUpdateNotice({ kind: "ok", text: tr("restart.official.body") });
							return d;
						}
						if (d.restartAfter) {
							setUpdateNotice({ kind: "ok", text: tr("update.restarting") });
							return d;
						}
						if (d.applied && d.reloadClient !== false) {
							setUpdateNotice({ kind: "ok", text: tr("update.reloading") });
							setTimeout(() => {
								try { window.location.reload(); } catch { /* ignore */ }
							}, 280);
						} else if (d.needRestart) {
							setAskRestart(true);
						}
						return d;
					})
					.catch((e) => {
						setUpdateNotice({ kind: "error", text: updateErrorText(tr, e) });
						throw e;
					})
					.finally(() => {
						setUpdateBusy(false);
						setUpdateJob(null);
					});
			}, [applyUpdateInfo]);

			const doUpdate = useCallback((id) => {
				const lane = id === "beta" ? "beta" : "stable";
				postUpdate({ op: "apply", ref: lane === "beta" ? "beta" : "master", channel: lane }, "done", id).catch(() => {});
			}, [postUpdate]);

			const changeChannel = useCallback((next) => {
				if (!next) return;
				const tr = tRef.current;
				if (!window.confirm(tr("update.confirmChannel", { version: tr("channel." + next) }))) return;
				const prevChannel = channel;
				const prevInfo = updateInfo;
				setChannel(next);
				setUpdateInfo((cur) => Object.assign({}, cur || {}, { channel: next }));
				postUpdate({ op: "channel", channel: next }, "channel", next).catch(() => {
					setChannel(prevChannel);
					setUpdateInfo(prevInfo);
				});
			}, [channel, postUpdate, updateInfo]);

			const switchSelected = useCallback((id) => {
				const tr = tRef.current;
				const ref = pick[id];
				const versions = ((updateInfo && updateInfo.versions) || []).filter((item) => item.channel === id);
				const hit = versions.find((item) => item.ref === ref);
				const label = (hit && (hit.label || hit.version)) || ref;
				if (!ref) return;
				if (!window.confirm(tr("update.confirmSwitch", { version: label }))) return;
				const prevChannel = channel;
				const prevInfo = updateInfo;
				if (hit && hit.channel) {
					setChannel(hit.channel);
					setUpdateInfo((cur) => Object.assign({}, cur || {}, { channel: hit.channel }));
				}
				postUpdate({ op: "switch", ref }, "switched", id).catch(() => {
					setChannel(prevChannel);
					setUpdateInfo(prevInfo);
				});
			}, [channel, pick, postUpdate, updateInfo]);

			const loadAll = useCallback(() => {
				const tr = tRef.current;
				apiJson("/dsh-purge/status")
					.then((d) => {
						if (d && d.ok) {
							setState(d);
							if (d.channel) setChannel(d.channel);
							if (d.update && d.update.ok && !d.update.error) setUpdateInfo(d.update);
							if (d.boot_full_quit && !suppressRestartAsk.current) setAskRestart(true);
						} else {
							setState({ ok: false, patches_total: 0, patches_applied: 0, patch_status: {}, shim_cmd: "n/a", shim_ps1: "n/a", shim_bin: "n/a", has_backup: false });
							setNotice({ kind: "error", text: tr("err.status", { error: (d && d.error) || "bad response" }) });
						}
					})
					.catch((e) => {
						setState({ ok: false, patches_total: 0, patches_applied: 0, patch_status: {}, shim_cmd: "n/a", shim_ps1: "n/a", shim_bin: "n/a", has_backup: false });
						setNotice({ kind: "error", text: tr("err.status", { error: e.message }) });
					});
				apiJson("/dsh-purge/update")
					.then((d) => {
						if (!d) return;
						if (d.channel) setChannel(d.channel);
						setUpdateInfo(d);
						syncPicks(d);
					})
					.catch(() => {});
				apiJson("/dsh-purge/override")
					.then((d) => {
						if (d && d.ok) {
							const packed = typeof d.defaultContent === "string" ? d.defaultContent : "";
							const shown = typeof d.content === "string" ? d.content : packed;
							if (packed) setDefaultOverride(packed);
							if (!promptSeededRef.current || !promptDirtyRef.current) {
								promptSeededRef.current = true;
								setOverride(shown || packed);
							}
							setOverrideLoaded(true);
						}
						else setNotice({ kind: "error", text: tr("err.override", { error: (d && d.error) || "" }) });
					})
					.catch((e) => setNotice({ kind: "error", text: tr("err.override", { error: e.message }) }));
				apiJson("/dsh-purge/own-servers")
					.then((d) => {
						if (d && d.ok) {
							setOwnServers(typeof d.content === "string" ? d.content : "");
							setOwnLoaded(true);
						}
					})
					.catch(() => {});
			}, []);

			useEffect(() => {
				loadAll();
				const timer = setTimeout(() => { loadAll(); }, 5000);
				return () => clearTimeout(timer);
			}, [loadAll]);

			const rejectNeedPrompt = useCallback((tr) => {
				setAskRestart(false);
				setNotice({ kind: "error", text: tr("need.prompt") });
				setTimeout(() => window.alert(tr("need.prompt")), 0);
			}, []);

			const doAction = useCallback((action, actionKey) => {
				const tr = tRef.current;
				const label = tr(actionKey);
				const ticket = ++actionTicket.current;
				const run = () => {
					setPatchBusy(true);
					setAskRestart(false);
					setNotice({ kind: "idle", text: "" });
					const applyContent = action === "apply" ? readPromptBox() : "";
					fetch("/dsh-purge/" + action, {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify(action === "apply" ? { content: applyContent } : {}),
					})
						.then((r) => r.json())
						.then((d) => {
							if (ticket !== actionTicket.current) return;
							if (responseNeedsPrompt(d)) {
								rejectNeedPrompt(tr);
								return;
							}
							if (!d.ok) {
								setNotice({ kind: "error", text: tr("err.action", { action: label, error: d.error || "" }) });
								return;
							}
							if (action === "apply") {
								if (typeof d.defaultContent === "string") setDefaultOverride(d.defaultContent);
								if (typeof d.override_content === "string") {
									setOverride(d.override_content);
									setOverrideLoaded(true);
								}
							}
							if (action === "apply" && d.complete === false) {
								const parts = [];
								if (d.failed > 0) {
									const ids = (d.failed_items || [])
										.map((x) => x.id)
										.filter((id) => id != null)
										.join(",");
									parts.push(
										tr("restart.incomplete.patches", {
											failed: String(d.failed || 0),
											ids: ids || "?",
										}),
									);
								}
								if (d.cmd_flash && d.cmd_flash.ok === false) {
									parts.push(
										tr("restart.incomplete.flash", {
											entry: String(d.cmd_flash.entry || "fail"),
										}),
									);
								}
								if (parts.length === 0) parts.push(tr("restart.incomplete.flash", { entry: "unknown" }));
								setNotice({
									kind: "error",
									text: tr("restart.incomplete", { detail: parts.join("；") }),
								});
								loadAll();
								if (d.restarting || d.needs_full_quit) {
									suppressRestartAsk.current = false;
									setAskRestart(true);
								}
								return;
							}
							if (action === "apply") {
								setNotice({ kind: "ok", text: tr("ok.done") });
								loadAll();
								suppressRestartAsk.current = false;
								setAskRestart(true);
								return;
							}
							setNotice({ kind: "ok", text: tr("ok.done") });
							loadAll();
						})
						.catch((e) => {
							if (ticket !== actionTicket.current) return;
							setNotice({ kind: "error", text: tr("err.action", { action: label, error: e.message }) });
						})
						.finally(() => {
							if (ticket === actionTicket.current) setPatchBusy(false);
						});
				};
				run();
			}, [loadAll, rejectNeedPrompt, state]);

			const saveOverride = useCallback(() => {
				const tr = t;
				const ticket = ++actionTicket.current;
				const go = () => {
					setPatchBusy(true);
					setAskRestart(false);
					setNotice({ kind: "idle", text: "" });
					const content = readPromptBox();
					fetch("/dsh-purge/override", {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({ content: content }),
					})
						.then((r) => r.json())
						.then((d) => {
							if (ticket !== actionTicket.current) return;
							if (!d.ok || responseNeedsPrompt(d)) {
								rejectNeedPrompt(tr);
								return;
							}
							if (typeof d.content === "string") {
								overrideRef.current = d.content;
								setOverride(d.content);
							}
							promptDirtyRef.current = false;
							setNotice({ kind: "ok", text: t("saved.override") });
						})
						.catch((e) => {
							if (ticket !== actionTicket.current) return;
							setNotice({ kind: "error", text: t("err.save", { error: e.message }) });
						})
						.finally(() => {
							if (ticket === actionTicket.current) setPatchBusy(false);
						});
				};
				bothInjectEmpty(readPromptBox(), defaultOverrideRef.current).then((empty) => {
					if (ticket !== actionTicket.current) return;
					if (empty) {
						rejectNeedPrompt(tr);
						return;
					}
					go();
				});
			}, [t, rejectNeedPrompt]);

			const restoreOverride = useCallback(() => {
				if (!defaultOverride) return;
				const tr = t;
				const ticket = ++actionTicket.current;
				overrideRef.current = defaultOverride;
				setOverride(defaultOverride);
				setPatchBusy(true);
				setNotice({ kind: "idle", text: "" });
				apiJson("/dsh-purge/override", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify({ content: defaultOverride }),
				})
					.then((d) => {
						if (ticket !== actionTicket.current) return;
						if (!d || !d.ok) {
							setNotice({ kind: "error", text: tr("err.save", { error: (d && d.error) || "" }) });
							return;
						}
						if (typeof d.content === "string") {
							overrideRef.current = d.content;
							setOverride(d.content);
						}
						promptDirtyRef.current = false;
						setNotice({ kind: "ok", text: tr("saved.restoreInject") });
					})
					.catch((e) => {
						if (ticket !== actionTicket.current) return;
						setNotice({ kind: "error", text: tr("err.save", { error: e.message }) });
					})
					.finally(() => {
						if (ticket === actionTicket.current) setPatchBusy(false);
					});
			}, [defaultOverride, t]);

			const waitHostAfterUninstall = useCallback((tr) => {
				const started = Date.now();
				const ping = () => {
					fetch("/", { cache: "no-store", credentials: "same-origin" })
						.then((r) => {
							if (r.ok) {
								try {
									window.localStorage.removeItem("dshp-theme");
									window.localStorage.removeItem("dshp-theme-mode");
								} catch { /* ignore */ }
								window.location.reload();
								return;
							}
							retry();
						})
						.catch(retry);
				};
				const retry = () => {
					if (Date.now() - started > 90000) {
						setNotice({ kind: "error", text: tr("restart.timeout") });
						setUninstallBusy(false);
						return;
					}
					setTimeout(ping, 500);
				};
				setTimeout(ping, 800);
			}, []);

			const doUninstall = useCallback(() => {
				setUninstallBusy(true);
				setAskUninstall(false);
				setAskRestart(false);
				const tr = tRef.current;
				setNotice({ kind: "ok", text: tr("uninstall.applying") });
				apiJson("/dsh-purge/uninstall", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" })
					.then((d) => {
						if (!d || !d.ok) throw new Error((d && d.error) || "uninstall failed");
						setNotice({ kind: "ok", text: (d && d.note) || hostText(tr, "uninstall.done", d.surface || hostSurfaceOf(state)) });
						if ((d && d.surface) === "desktop" || (d && d.fullApp) || hostSurfaceOf(state) === "desktop") return;
						waitHostAfterUninstall(tr);
					})
					.catch((e) => {
						const msg = String((e && e.message) || e || "");
						if (/failed to fetch|networkerror|load failed/i.test(msg)) {
							setNotice({ kind: "ok", text: hostText(tr, "uninstall.done", hostSurfaceOf(state)) });
							if (hostSurfaceOf(state) === "desktop" || clientGuessSurface() === "desktop") return;
							waitHostAfterUninstall(tr);
							return;
						}
						setNotice({ kind: "error", text: tr("uninstall.fail", { error: msg }) });
						setUninstallBusy(false);
					});
			}, [state, waitHostAfterUninstall]);

			const s = state;
			const located = !!(s && s.ai_base);
			const hostSurface = hostSurfaceOf(s);
			const desktopLikely = hostSurface === "desktop" || clientGuessSurface() === "desktop";
			const sealedReady = !located && desktopLikely && !!(s && (s.asar_still_sealed || s.desktop_exe || s.desktop_install));
			const patchesLost = !located && !!(s && s.patches_lost);
			const tally = located ? tallyPatches(patchRowsOf(s)) : { applied: 0, pending: 0, unmatched: 0, skipped: 0, total: 0 };
			const total = tally.total;
			const applied = tally.applied;
			const pct = located && total ? Math.round((applied / total) * 100) : 0;
			const metricNotes = [];
			if (tally.pending) metricNotes.push(t("metric.pendingShort", { n: tally.pending }));
			if (tally.unmatched) metricNotes.push(t("metric.unmatchedShort", { n: tally.unmatched }));
			if (tally.skipped) metricNotes.push(t("metric.skipShort", { n: tally.skipped }));

			const versions = (updateInfo && updateInfo.versions) || [];
			const channelNow = (updateInfo && updateInfo.channel) || channel || "stable";
			const localVer = (s && s.plugin_version) || (updateInfo && updateInfo.localVersion) || "";
			const renderEdition = (id) => {
				const lane = (updateInfo && updateInfo.lanes && updateInfo.lanes[id]) || {};
				const ceiling = listedCeiling(versions, localVer || (updateInfo && updateInfo.localVersion));
				const list = versions.filter((item) => item.channel === id && keepListedVersion(item, ceiling));
				const selectedRef = pick[id] || "";
				const hit = list.find((item) => item.ref === selectedRef) || preferListed(list, localVer, updateInfo && updateInfo.pin);
				const onLane = channelNow === id;
				const noBeta = id === "beta" && Array.isArray(updateInfo && updateInfo.versions) && !list.length;
				const pickedOther = Boolean(hit && selectedRef && !hit.current);
				const thisJob = updateJob && updateJob.id === id ? updateJob : null;
				let actionLabel = t("btn.checkUpdate");
				let actionKind;
				let actionClick = () => checkUpdate(id);
				let actionDisabled = updateBusy || Boolean(noBeta);
				if (noBeta) {
					actionLabel = t("update.noBeta");
					actionClick = () => {};
				} else if (pickedOther) {
					actionLabel = t("update.switch");
					actionKind = "primary";
					actionClick = () => switchSelected(id);
				} else if (!onLane) {
					actionLabel = id === "beta" ? t("channel.useBeta") : t("channel.useStable");
					actionKind = "primary";
					actionClick = () => changeChannel(id);
				} else if (canApplyUpdate && lane.hasUpdate) {
					actionLabel = t("btn.doUpdate");
					actionKind = "primary";
					actionClick = () => doUpdate(id);
				}
				if (thisJob) {
					if (thisJob.kind === "check") actionLabel = t("btn.checkUpdate.busy");
					else if (thisJob.kind === "done") actionLabel = t("btn.doUpdate.busy");
					else actionLabel = t("update.switching");
				}
				return h("div", {
					className: "dshp-edition" + (onLane ? " is-on" : ""),
					"aria-label": t("channel." + id),
				},
					h("span", { className: "dshp-edition-name" },
						t("channel." + id),
						onLane ? h("em", { className: "dshp-now-mark" }, t("update.current")) : null,
					),
					h("select", {
						className: "dshp-field dshp-ver",
						value: list.length ? ((hit && hit.ref) || "") : "",
						disabled: updateBusy || !list.length,
						onChange: (e) => setPick((prev) => Object.assign({}, prev, { [id]: e.target.value })),
						"aria-label": t("update.pick"),
					},
						list.length
							? list.map((item) => h("option", {
								key: item.ref + (item.sha || ""),
								value: item.ref,
							}, versionChoiceLabel(item, t)))
							: h("option", { value: "" }, noBeta ? t("update.noBeta") : t("update.pick")),
					),
					h(Btn, { tiny: true, kind: actionKind, disabled: actionDisabled, onClick: actionClick }, actionLabel),
				);
			};
			return h("section", { className: "dshp-panel", "aria-label": t("purge.title") },
				h("div", { className: "dshp-head" },
					h("h3", { className: "dshp-title" }, t("purge.title")),
					h("span", { className: "dshp-pill" }, t("surface." + hostSurface)),
				),
				h("div", { className: "dshp-rel" },
					h("div", { className: "dshp-now" },
						h("span", { className: "dshp-now-label" }, t("channel.local")),
						h("b", { className: "dshp-now-ver" }, localVer ? "v" + localVer : "—"),
						h("em", { className: "dshp-now-mark" }, t("update.current")),
					),
					h("div", { className: "dshp-editions" },
						renderEdition("stable"),
						renderEdition("beta"),
					),
					noticeNode(updateNotice),
				),
				s ? h("div", { className: "dshp-metrics" },
					h("div", { className: "dshp-metric" },
						h("b", null, located ? (applied + " / " + total) : (patchesLost ? t("metric.lost.count") : (sealedReady ? t("metric.sealed.count") : t("metric.unlocated.count")))),
						h("span", null, !located ? (patchesLost ? t("metric.lost") : (sealedReady ? t("metric.sealed") : t("metric.unlocated"))) : (metricNotes.length ? metricNotes.join(" · ") : t("metric.purged"))),
					),
					h("div", { className: "dshp-metric" },
						h("b", { style: { fontSize: 13, fontFamily: "var(--dshp-mono)", fontWeight: 500 } },
							h("span", { className: "dshp-pill is-" + shimKind(s.shim_cmd) }, "cmd"),
							" ",
							h("span", { className: "dshp-pill is-" + shimKind(s.shim_ps1) }, "ps1"),
							" ",
							h("span", { className: "dshp-pill is-" + shimKind(s.shim_bin || "missing") }, "unix"),
						),
						h("span", null, (s.shim_cmd === "n/a" && s.shim_ps1 === "n/a" && (s.shim_bin === "n/a" || !s.shim_bin)) ? t("metric.shim.na") : t("metric.shim")),
					),
					h("div", { className: "dshp-metric" },
						h("b", null, s.has_backup ? t("metric.bak.yes") : t("metric.bak.no")),
						h("span", null, t("metric.bak.hint")),
					),
				) : h("div", { className: "dshp-metrics" },
					h("div", { className: "dshp-metric" }, h("div", { className: "dshp-skel" }), h("div", { className: "dshp-skel", style: { width: "40%" } })),
					h("div", { className: "dshp-metric" }, h("div", { className: "dshp-skel" }), h("div", { className: "dshp-skel", style: { width: "40%" } })),
					h("div", { className: "dshp-metric" }, h("div", { className: "dshp-skel" }), h("div", { className: "dshp-skel", style: { width: "40%" } })),
				),
				h("div", { className: "dshp-bar", "aria-hidden": "true" }, h("i", { style: { width: pct + "%" } })),
				h(PatchGroups, { state: s }),
				h(HooksDenySection, { onSaved: loadAll }),
				h("div", { className: "dshp-row", style: { marginTop: 14 } },
					h(Btn, { kind: "primary", disabled: patchBusy || uninstallBusy || !overrideLoaded, onClick: () => doAction("apply", "action.apply") }, patchBusy ? t("btn.apply.busy") : t("btn.apply")),
					h(Btn, { kind: "danger", disabled: patchBusy || uninstallBusy, onClick: () => doAction("revert", "action.revert") }, t("btn.revert")),
					h(Btn, { kind: "solid-danger", disabled: patchBusy || uninstallBusy, onClick: () => setAskUninstall(true) }, uninstallBusy ? t("btn.uninstall.busy") : t("btn.uninstall")),
					noticeNode(notice),
				),
				askUninstall ? h("div", {
					className: "dshp-modal-bg",
					role: "dialog",
					"aria-modal": "true",
					"aria-labelledby": "dshp-uninstall-title",
					onClick: (e) => { if (e.target === e.currentTarget && !uninstallBusy) setAskUninstall(false); },
				},
					h("div", { className: "dshp-modal" },
						h("h4", { id: "dshp-uninstall-title" }, t("uninstall.title")),
						h("p", null, t("uninstall.body")),
						h("div", { className: "dshp-modal-ops" },
							h(Btn, { disabled: uninstallBusy, onClick: () => setAskUninstall(false) }, t("uninstall.cancel")),
							h(Btn, { kind: "solid-danger", disabled: uninstallBusy, onClick: doUninstall }, t("uninstall.confirm")),
						),
					),
				) : null,
				h("p", { className: "dshp-hint", style: { margin: "8px 0 0", color: "var(--dshp-mute)", fontSize: 12 } }, t("apply.hint")),
				s && !s.ai_base ? h("p", { className: "dshp-hint", style: { margin: "8px 0 0", color: "var(--dshp-danger, #c44)", fontSize: 12 } }, hostText(t, "warn.noRoot", hostSurface)) : null,
				s && s.ai_base && s.override_status === "missing" ? h("p", { className: "dshp-hint", style: { margin: "8px 0 0", color: "var(--dshp-mute)", fontSize: 12 } }, t("warn.noInject")) : null,
				askRestart ? h(RestartAsk, {
					t: t,
					theme: detectHostTheme(),
					onLater: () => {
						suppressRestartAsk.current = true;
						setAskRestart(false);
					},
					onRestart: () => {
						suppressRestartAsk.current = true;
						setAskRestart(false);
						restartDsh(setNotice, function () {}, t, hostSurface);
					},
				}) : null,
				// h(ContinueRetrySection, null),
				h("div", { className: "dshp-sub" },
					h("h4", null, t("override.title")),
					h("div", { className: "dshp-row", style: { margin: 0 } },
						h(Btn, { kind: "primary", tiny: true, disabled: patchBusy || !overrideLoaded, onClick: saveOverride }, t("btn.saveInject")),
						h(Btn, { tiny: true, disabled: patchBusy || !overrideLoaded || !defaultOverride, onClick: restoreOverride }, t("btn.restoreInject")),
					),
				),
				h("textarea", {
					className: "dshp-area",
					ref: promptAreaRef,
					value: override,
					onChange: (e) => {
						promptDirtyRef.current = true;
						overrideRef.current = e.target.value;
						setOverride(e.target.value);
					},
					spellCheck: false,
					placeholder: "",
				}),
				promptBoxEmpty(override) ? h("p", {
					className: "dshp-hint",
					style: { margin: "8px 0 0", color: "var(--dshp-danger, #c44)", fontSize: 12 },
				}, t("need.prompt")) : null,
				h("div", { className: "dshp-sub" },
					h("h4", null, t("own.title")),
				),
				h("p", { className: "dshp-hint", style: { margin: "8px 0 0", color: "var(--dshp-mute)", fontSize: 12 } }, t("own.hint")),
			);
		}

		function ruleLabel(r) {
			if (!r) return "";
			if (r.name !== r.id) return r.name + " (" + r.id + ")";
			return r.id;
		}

		function RulesSection() {
			const t = useT();
			const tRef = useRef(t);
			tRef.current = t;
			const [st, setSt] = useState(null);
			const [editId, setEditId] = useState(null);
			const [editName, setEditName] = useState("");
			const [editTarget, setEditTarget] = useState("AGENTS.md");
			const [content, setContent] = useState("");
			const [newId, setNewId] = useState("");
			const [newName, setNewName] = useState("");
			const [newTarget, setNewTarget] = useState("AGENTS.md");
			const [busy, setBusy] = useState(false);
			const [notice, setNotice] = useState({ kind: "idle", text: "" });

			const loadStatus = useCallback(() => {
				const tr = tRef.current;
				let cwd = "";
				try { cwd = clientCurrentCwd(); } catch { /* ignore */ }
				rulesApi("status", cwd ? { cwd: cwd } : undefined)
					.then((d) => {
						if (d && d.ok) setSt(d);
						else {
							setSt({ ok: false, rules: [], active: null });
							setNotice({ kind: "error", text: tr("err.rules", { error: (d && d.error) || "bad response" }) });
						}
					})
					.catch((e) => {
						setSt({ ok: false, rules: [], active: null });
						setNotice({ kind: "error", text: tr("err.rules", { error: e.message }) });
					});
			}, []);

			useEffect(() => { loadStatus(); }, [loadStatus]);

			const doPost = useCallback((action, payload, after) => {
				setBusy(true);
				setNotice({ kind: "idle", text: "" });
				rulesApi(action, payload)
					.then((d) => {
						if (d && d.ok) {
							setNotice({ kind: "ok", text: t("ok.done") });
							if (action === "save" || action === "activate") warnNeedPrompt(d, t);
							loadStatus();
							if (after) after();
						} else {
							warnNeedPrompt(d, t);
							setNotice({ kind: "error", text: t("err.action", { error: (d && d.error) || "" }) });
						}
					})
					.catch((e) => setNotice({ kind: "error", text: t("err.action", { error: e.message }) }))
					.finally(() => setBusy(false));
			}, [loadStatus, t]);

			const openRule = useCallback((id) => {
				setBusy(true);
				rulesApi("read", { id: id })
					.then((d) => {
						if (d.ok) {
							setEditId(id);
							setEditName(d.name || id);
							setEditTarget(d.target || "AGENTS.md");
							setContent(typeof d.content === "string" ? d.content : "");
						} else setNotice({ kind: "error", text: t("err.read", { error: d.error || "" }) });
					})
					.catch((e) => setNotice({ kind: "error", text: t("err.read", { error: e.message }) }))
					.finally(() => setBusy(false));
			}, [t]);

			const clearEditor = () => {
				setEditId(null);
				setEditName("");
				setEditTarget("AGENTS.md");
				setContent("");
			};

			let list;
			if (!st) {
				list = h("div", { className: "dshp-skel", style: { height: 80, margin: 12 } });
			} else if (!st.rules || st.rules.length === 0) {
				list = h("p", { className: "dshp-empty" }, t("rules.empty"));
			} else {
				list = st.rules.map((r) => {
					const isActive = r.id === st.active;
					const isEdit = r.id === editId;
					return h("div", {
						key: r.id,
						className: "dshp-ruleitem" + (isEdit ? " is-edit" : ""),
						role: "button",
						tabIndex: 0,
						onClick: () => openRule(r.id),
						onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openRule(r.id); } },
					},
						h("div", { className: "dshp-rule-main" },
							h("span", { className: "dshp-rule-name" },
								ruleLabel(r),
								isActive ? h("span", { className: "dshp-pill is-ok" }, t("pill.current")) : null,
							),
							h("span", { className: "dshp-rule-meta" }, r.target + " · " + formatSize(r.size)),
						),
						h("div", { className: "dshp-rule-ops" },
							h(Btn, {
								tiny: true,
								kind: isActive ? undefined : "primary",
								disabled: busy || isActive,
								onClick: (e) => {
									e.stopPropagation();
									if (!isActive) doPost("activate", { id: r.id });
								},
							}, isActive ? t("btn.inUse") : t("btn.use")),
							h(Btn, {
								tiny: true,
								kind: "danger",
								disabled: busy,
								onClick: (e) => {
									e.stopPropagation();
									if (!window.confirm(t("confirm.delete", { id: r.id }))) return;
									if (editId === r.id) clearEditor();
									doPost("delete", { id: r.id });
								},
							}, t("delete")),
						),
					);
				});
			}

			const policyValue = (st && typeof st.workspace_policy === "string") ? st.workspace_policy : "fallback";
			const policyOptions = (st && Array.isArray(st.workspace_policies) && st.workspace_policies.length) ? st.workspace_policies : ["fallback", "strict", "always"];
			const cwdCandidates = (st && Array.isArray(st.cwd_candidates)) ? st.cwd_candidates : [];
			const cwdValue = (st && typeof st.cwd === "string") ? st.cwd : "";
			return h("section", { className: "dshp-panel", "aria-label": t("rules.title") },
				h("div", { className: "dshp-head" },
					h("h3", { className: "dshp-title" }, t("rules.title")),
					h("div", { className: "dshp-row", style: { margin: 0 } },
						noticeNode(notice),
						h(Btn, {
							tiny: true,
							kind: "danger",
							disabled: busy,
							onClick: () => {
								if (!window.confirm(t("rules.reset.confirm"))) return;
								clearEditor();
								doPost("reset", {});
							},
						}, t("rules.reset")),
					),
				),
				h("div", { className: "dshp-block" },
					h("div", { className: "dshp-policy-row" },
						h("label", { htmlFor: "dshp-policy-select" }, t("policy.title")),
						h("select", {
							id: "dshp-policy-select",
							className: "dshp-field",
							value: policyValue,
							disabled: busy || !st,
							onChange: (e) => doPost("set-policy", { policy: e.target.value }),
						}, policyOptions.map((p) => h("option", { key: p, value: p }, t("policy." + p)))),
					),
					h("p", { className: "dshp-block-hint" }, t("policy.hint")),
				),
				h("div", { className: "dshp-block" },
					h("div", { className: "dshp-block-head" },
						h("h4", null, t("cwd.title")),
						h(Btn, {
							tiny: true,
							disabled: busy,
							onClick: () => {
								let cwd = cwdValue;
								if (!cwd) { try { cwd = clientCurrentCwd(); } catch { /* ignore */ } }
								doPost("scan-cwd", cwd ? { cwd: cwd } : {});
							},
						}, t("cwd.rescan")),
					),
					cwdValue ? h("p", { className: "dshp-cwd-path" }, cwdValue) : null,
					(!st || !cwdValue)
						? h("p", { className: "dshp-empty" }, t("cwd.no.workspace"))
						: (cwdCandidates.length === 0
							? h("p", { className: "dshp-empty" }, t("cwd.empty"))
							: h("div", { className: "dshp-cwd-list" }, cwdCandidates.map((item) => h("label", {
								key: item.path,
								className: "dshp-cwd-item" + (item.selected ? " is-on" : ""),
							},
								h("input", {
									type: "checkbox",
									checked: Boolean(item.selected),
									disabled: busy,
									onChange: (e) => doPost("toggle-cwd", { path: item.path, enabled: e.target.checked }),
								}),
								h("div", { className: "dshp-cwd-main" },
									h("div", { className: "dshp-cwd-name" },
										h("span", null, item.name),
										h("span", { className: "dshp-cwd-badge" }, t("cwd.scope." + (item.scope || "cwd"))),
										h("span", { className: "dshp-cwd-size" }, formatSize(item.size || 0)),
									),
									h("div", { className: "dshp-cwd-sub" }, item.path),
									item.preview ? h("div", { className: "dshp-cwd-prev" }, item.preview) : null,
								),
							)))),
					h("p", { className: "dshp-block-hint" }, t("cwd.hint")),
				),
				h("div", { className: "dshp-block" },
				h("div", { className: "dshp-split" },
					h("div", { className: "dshp-rulelist" },
						h("div", { className: "dshp-rulebody" }, list),
						h("div", { className: "dshp-create" },
							h("div", { className: "dshp-create-row" },
								h("input", { className: "dshp-field", placeholder: t("ph.id"), value: newId, onChange: (e) => setNewId(e.target.value) }),
								h("input", { className: "dshp-field", placeholder: t("ph.alias"), value: newName, onChange: (e) => setNewName(e.target.value) }),
								h("select", { className: "dshp-field", style: { minWidth: 120, flex: "0 0 auto" }, value: newTarget, onChange: (e) => setNewTarget(e.target.value) },
									TARGETS.map((x) => h("option", { key: x, value: x }, x))),
								h(Btn, {
									kind: "primary",
									tiny: true,
									disabled: busy,
									onClick: () => {
										const id = newId.trim();
										if (!id) { setNotice({ kind: "error", text: t("need.id") }); return; }
										const name = newName.trim() || id;
										const target = newTarget;
										doPost("save", { id, content: "", name, target }, () => {
											setEditId(id);
											setEditName(name);
											setEditTarget(target);
											setContent("");
										});
										setNewId(""); setNewName(""); setNewTarget("AGENTS.md");
									},
								}, t("btn.create")),
							),
						),
					),
					h("div", { className: "dshp-editor" },
						editId ? [
							h("div", { key: "meta", className: "dshp-row" },
								h("input", {
									className: "dshp-field", placeholder: t("ph.alias.short"), value: editName,
									onChange: (e) => setEditName(e.target.value),
								}),
								h("select", {
									className: "dshp-field", style: { minWidth: 120 }, value: editTarget,
									onChange: (e) => setEditTarget(e.target.value),
								}, TARGETS.map((x) => h("option", { key: x, value: x }, x))),
							),
							h("textarea", {
								key: "body",
								className: "dshp-area", value: content,
								onChange: (e) => setContent(e.target.value),
								placeholder: "",
							}),
							h("div", { key: "save", className: "dshp-row" },
								h(Btn, {
									kind: "primary",
									disabled: busy,
									onClick: () => doPost("save", { id: editId, content, name: editName, target: editTarget }),
								}, t("btn.saveRule")),
								noticeNode(notice),
							),
						] : h("div", { className: "dshp-editor-empty" }, t("rules.pick")),
					),
				),
				),
			);
		}

		function skillUiAllowed(d) {
			if (!d) return false;
			const ver = String(d.plugin_version || d.localVersion || "").replace(/^v/i, "");
			if (/^1\.1\.11(?:-|$)/.test(ver)) return false;
			const parts = ver.match(/^(\d+)\.(\d+)\.(\d+)/);
			if (!parts) return false;
			if (+parts[1] !== 1) return +parts[1] > 1;
			if (+parts[2] !== 1) return +parts[2] > 1;
			return +parts[3] >= 12;
		}

		function splitListedVersion(raw) {
			const text = String(raw || "").trim().replace(/^v/i, "");
			const cut = text.split("-");
			const core = String(cut[0] || "").split(".").map((n) => parseInt(n, 10) || 0);
			return { core: [core[0] || 0, core[1] || 0, core[2] || 0], pre: cut.slice(1).join("-") };
		}

		function listedVersionNewer(remote, local) {
			if (!remote || !local || String(remote) === String(local)) return false;
			const a = splitListedVersion(remote);
			const b = splitListedVersion(local);
			for (let i = 0; i < 3; i += 1) {
				if (a.core[i] !== b.core[i]) return a.core[i] > b.core[i];
			}
			if (a.pre && !b.pre) return false;
			if (!a.pre && b.pre) return true;
			return a.pre > b.pre;
		}

		function listedCeiling(versions, localVer) {
			let best = "";
			const rows = (versions || []).slice();
			const local = String(localVer || "").replace(/^v/i, "");
			if (local && !/(?:^|[-._])(beta|rc|pre|preview|test)(?:\d|$|[-._])/i.test(local)) {
				rows.push({ channel: "stable", version: local });
			}
			for (const item of rows) {
				if (!item || item.channel === "beta") continue;
				const ver = String(item.version || "").replace(/^v/i, "");
				if (!/^\d+\.\d+\.\d+/.test(ver) || /(?:^|[-._])(beta|rc|pre|preview|test)(?:\d|$|[-._])/i.test(ver)) continue;
				if (!best || listedVersionNewer(ver, best)) best = ver;
			}
			return best;
		}

		function keepListedVersion(item, _ceiling) {
			const ver = String((item && (item.version || item.ref || item.id)) || "");
			if (!item) return false;
			if (item.ref === "beta" || item.id === "beta") return true;
			if (item.channel === "beta") return false;
			if (/(?:^|[-._])(beta|rc|pre|preview|test)(?:\d|$|[-._])/i.test(ver)) return false;
			return true;
		}

		function preferListed(list, localVer, pin) {
			const pinned = pin ? (list || []).find((item) => item.ref === pin) : null;
			if (pinned) return pinned;
			const ver = String(localVer || "").replace(/^v/i, "");
			const same = (list || []).filter((item) => ver && String(item.version || "").replace(/^v/i, "") === ver);
			if (same.length) {
				return same.find((item) => item.current)
					|| same.find((item) => item.latest)
					|| same[0];
			}
			return (list || []).find((item) => item.current)
				|| (list || []).find((item) => item.latest)
				|| (list || [])[0]
				|| null;
		}

		function versionChoiceLabel(item, tr) {
			const ver = String((item && item.version) || "").replace(/^v/i, "");
			const base = ver ? ("v" + ver) : ((item && (item.label || item.ref)) || "—");
			if (item && item.current) return base + " · " + tr("update.current");
			if (item && item.latest) return base + " · " + tr("update.tip");
			return base;
		}

		function SkillsSection() {
			const t = useT();
			const tRef = useRef(t);
			tRef.current = t;
			const [onBeta, setOnBeta] = useState(false);
			const [st, setSt] = useState(null);
			const [editId, setEditId] = useState(null);
			const [editDesc, setEditDesc] = useState("");
			const [content, setContent] = useState("");
			const [busy, setBusy] = useState(false);
			const [notice, setNotice] = useState({ kind: "idle", text: "" });
			const zipRef = useRef(null);
			const folderRef = useRef(null);

			const loadStatus = useCallback(() => {
				const tr = tRef.current;
				const fail = (e) => {
					setSt({ ok: false, skills: [] });
					setNotice({
						kind: "error",
						text: skillsRouteMissing(e) ? tr("err.skills.needRestart") : tr("err.skills", { error: (e && e.message) || e || "bad response" }),
					});
				};
				const apply = (d) => {
					if (d && d.ok) setSt({ ok: true, skills: d.skills || [] });
					else fail({ message: (d && d.error) || "bad response" });
				};
				apiJson("/dsh-purge/status")
					.then((d) => {
						const allowed = skillUiAllowed(d);
						setOnBeta(allowed);
						if (!allowed) {
							setSt(null);
							return;
						}
						if (d.skills) {
							apply({ ok: true, skills: d.skills });
							return;
						}
						skillsApi("status").then(apply).catch(fail);
					})
					.catch(() => {
						setOnBeta(false);
						setSt(null);
					});
			}, []);

			useEffect(() => { loadStatus(); }, [loadStatus]);

			const doPost = useCallback((action, payload, after) => {
				setBusy(true);
				setNotice({ kind: "idle", text: "" });
				skillsApi(action, payload)
					.then((d) => {
						if (d && d.ok) {
							setNotice({ kind: "ok", text: t("ok.done") });
							loadStatus();
							if (after) after(d);
						} else {
							setNotice({ kind: "error", text: t("err.action", { error: (d && d.error) || "" }) });
						}
					})
					.catch((e) => setNotice({
						kind: "error",
						text: skillsRouteMissing(e) ? t("err.skills.needRestart") : t("err.action", { error: e.message }),
					}))
					.finally(() => setBusy(false));
			}, [loadStatus, t]);

			const openSkill = useCallback((id) => {
				setBusy(true);
				skillsApi("read", { id: id })
					.then((d) => {
						if (d.ok) {
							setEditId(id);
							setEditDesc(d.description || "");
							setContent(typeof d.content === "string" ? d.content : "");
						} else setNotice({ kind: "error", text: t("err.read", { error: d.error || "" }) });
					})
					.catch((e) => setNotice({ kind: "error", text: t("err.read", { error: e.message }) }))
					.finally(() => setBusy(false));
			}, [t]);

			const clearEditor = () => {
				setEditId(null);
				setEditDesc("");
				setContent("");
			};

			const readAsBase64 = (file) => new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => {
					const text = String(reader.result || "");
					const at = text.indexOf(",");
					resolve(at >= 0 ? text.slice(at + 1) : text);
				};
				reader.onerror = () => reject(new Error(t("need.import")));
				reader.readAsDataURL(file);
			});

			const importZip = (file) => {
				if (!file) {
					setNotice({ kind: "error", text: t("need.import") });
					return;
				}
				setBusy(true);
				setNotice({ kind: "ok", text: t("skills.importing") });
				readAsBase64(file)
					.then((data) => skillsApi("import", { data, name: file.name }))
					.then((d) => {
						if (!d || !d.ok) throw new Error((d && d.error) || "");
						setNotice({ kind: "ok", text: t("saved.import", { count: (d.imported || []).length || 1 }) });
						loadStatus();
					})
					.catch((e) => setNotice({
						kind: "error",
						text: skillsRouteMissing(e) ? t("err.skills.needRestart") : t("err.action", { error: e.message }),
					}))
					.finally(() => setBusy(false));
			};

			const keepFolderFile = (file) => {
				const rel = String(file.webkitRelativePath || file.name || "").replace(/\\/g, "/");
				if (!rel || rel.includes("..")) return false;
				if (/(^|\/)(node_modules|\.git|__MACOSX|\.system)(\/|$)/i.test(rel)) return false;
				if (/(^|\/)\._/.test(rel) || /\/\.DS_Store$/i.test(rel)) return false;
				return true;
			};

			const importFolder = (list) => {
				const files = Array.from(list || []).filter(keepFolderFile);
				if (!files.length) {
					setNotice({ kind: "error", text: t("err.import.folder") });
					return;
				}
				setBusy(true);
				setNotice({ kind: "ok", text: t("skills.importing") });
				Promise.all(files.map((file) => readAsBase64(file).then((content) => ({
					path: file.webkitRelativePath || file.name,
					content,
					encoding: "base64",
				}))))
					.then((payload) => skillsApi("import", {
						files: payload,
						name: String(payload[0] && payload[0].path || "").split("/")[0],
					}))
					.then((d) => {
						if (!d || !d.ok) throw new Error((d && d.error) || "");
						setNotice({ kind: "ok", text: t("saved.import", { count: (d.imported || []).length || 1 }) });
						loadStatus();
					})
					.catch((e) => setNotice({
						kind: "error",
						text: skillsRouteMissing(e) ? t("err.skills.needRestart") : t("err.action", { error: e.message }),
					}))
					.finally(() => setBusy(false));
			};

			if (!onBeta) return null;

			let list;
			if (!st) {
				list = h("div", { className: "dshp-skel", style: { height: 80, margin: 12 } });
			} else if (!st.skills || st.skills.length === 0) {
				list = h("p", { className: "dshp-empty" }, t("skills.empty"));
			} else {
				list = st.skills.map((item) => {
					const isEdit = item.id === editId;
					return h("div", {
						key: item.id,
						className: "dshp-ruleitem" + (isEdit ? " is-edit" : ""),
						role: "button",
						tabIndex: 0,
						onClick: () => openSkill(item.id),
						onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSkill(item.id); } },
					},
						h("div", { className: "dshp-rule-main" },
							h("span", { className: "dshp-rule-name" }, item.id),
							h("span", { className: "dshp-rule-meta" },
								(item.valid ? item.description : t("skills.invalid")) + " · " + formatSize(item.size),
							),
							item.valid ? h("span", { className: "dshp-rule-meta" },
								[
									item.userInvocable ? t("skills.call.slash", { cmd: "/" + item.id }) : t("skills.call.userOff"),
									item.modelInvocable ? t("skills.call.model") : t("skills.call.modelOff"),
								].join(" · "),
							) : null,
						),
						h("div", { className: "dshp-rule-ops" },
							h(Btn, {
								tiny: true,
								kind: "danger",
								disabled: busy,
								onClick: (e) => {
									e.stopPropagation();
									if (!window.confirm(t("confirm.delete.skill", { id: item.id }))) return;
									if (editId === item.id) clearEditor();
									doPost("delete", { id: item.id });
								},
							}, t("delete")),
						),
					);
				});
			}

			return h("section", { className: "dshp-panel", "aria-label": t("skills.title") },
				h("div", { className: "dshp-head" },
					h("h3", { className: "dshp-title" }, t("skills.title")),
					h("div", { className: "dshp-row", style: { margin: 0 } }, noticeNode(notice)),
				),
				h("p", { className: "dshp-hint", style: { margin: "0 0 10px", color: "var(--dshp-mute)", fontSize: 12 } }, hostText(t, "skills.hint", hostSurfaceOf())),
				h("div", { className: "dshp-split" },
					h("div", { className: "dshp-rulelist" },
						h("div", { className: "dshp-rulebody" }, list),
						h("div", { className: "dshp-create" },
							h("div", { className: "dshp-create-row" },
								h("input", {
									ref: zipRef,
									type: "file",
									accept: ".zip,.tgz,.tar.gz,.tar,.skill",
									style: { display: "none" },
									onChange: (e) => {
										const file = e.target.files && e.target.files[0];
										e.target.value = "";
										importZip(file);
									},
								}),
								h("input", {
									ref: (el) => {
										folderRef.current = el;
										if (!el) return;
										el.setAttribute("webkitdirectory", "");
										el.setAttribute("directory", "");
										el.multiple = true;
									},
									type: "file",
									multiple: true,
									style: { display: "none" },
									onChange: (e) => {
										const files = Array.from((e.target && e.target.files) || []);
										e.target.value = "";
										importFolder(files);
									},
								}),
								h(Btn, {
									kind: "primary",
									tiny: true,
									disabled: busy,
									onClick: () => zipRef.current && zipRef.current.click(),
								}, t("btn.importZip")),
								h(Btn, {
									tiny: true,
									disabled: busy,
									onClick: () => folderRef.current && folderRef.current.click(),
								}, t("btn.importFolder")),
							),
						),
					),
					h("div", { className: "dshp-editor" },
						editId ? [
							h("div", { key: "meta", className: "dshp-row" },
								h("input", {
									className: "dshp-field",
									placeholder: t("ph.skill.desc"),
									value: editDesc,
									onChange: (e) => setEditDesc(e.target.value),
								}),
							),
							h("textarea", {
								key: "body",
								className: "dshp-area",
								value: content,
								onChange: (e) => setContent(e.target.value),
								spellCheck: false,
								placeholder: "",
							}),
							h("div", { key: "save", className: "dshp-row" },
								h(Btn, {
									kind: "primary",
									disabled: busy,
									onClick: () => doPost("save", { id: editId, content, description: editDesc }),
								}, t("btn.saveSkill")),
								noticeNode(notice),
							),
						] : h("div", { className: "dshp-editor-empty" }, t("skills.pick")),
					),
				),
			);
		}

		function reopenAfterRestart() {
			window.location.reload();
		}

		function waitForRestart(setNotice, setBusy, t) {
			const started = Date.now();
			// 必须先看到旧进程掉线，再等新进程就绪；否则同进程立刻 200 会被当成「重启成功」又弹重启。
			let sawDown = false;
			const ping = () => {
				fetch("/dsh-purge/status", { cache: "no-store", credentials: "same-origin" })
					.then((r) => (r.ok ? r.json() : Promise.reject()))
					.then((d) => {
						if (!sawDown) {
							retry();
							return;
						}
						if (d && d.ok && d.ready !== false) reopenAfterRestart();
						else retry();
					})
					.catch(() => {
						sawDown = true;
						retry();
					});
			};
			const retry = () => {
				if (Date.now() - started > 90000) {
					setNotice({ kind: "error", text: t("restart.timeout") });
					setBusy(false);
					return;
				}
				setTimeout(ping, 500);
			};
			setTimeout(ping, 800);
		}

		let restartOnce = false;

		function restartDsh(setNotice, setBusy, t, surface) {
			if (restartOnce) return;
			const surf = surface || clientGuessSurface() || "desktop";
			const desktop = surf === "desktop" || clientGuessSurface() === "desktop";
			restartOnce = true;
			setBusy(true);
			setNotice({ kind: "ok", text: hostText(t, "restarting", surf) });
			const stop = (error) => {
				restartOnce = false;
				setNotice({ kind: "error", text: error ? t("restart.fail", { error }) : t("restart.notStarted") });
				setBusy(false);
			};
			let sawDrop = false;
			const watch = setTimeout(() => {
				if (sawDrop) return;
				stop("");
			}, 25000);
			fetch("/dsh-purge/restart", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" })
				.then((r) => r.json())
				.then((d) => {
					if (!d.ok) throw new Error(d.error || "restart failed");
					const next = (d && d.surface) || surf;
					const full = next === "desktop" || (d && d.fullApp) || desktop;
					if (full && d.already) {
						setNotice({ kind: "ok", text: hostText(t, "restarting", next) });
						return;
					}
					if (full && d.restarting === false) {
						clearTimeout(watch);
						stop(d.error || "not started");
						return;
					}
					setNotice({ kind: "ok", text: hostText(t, "restarting", next) });
					if (full) return;
					clearTimeout(watch);
					restartOnce = false;
					waitForRestart(setNotice, setBusy, t);
				})
				.catch((e) => {
					const msg = String((e && e.message) || e || "");
					const dropped = /failed to fetch|networkerror|load failed/i.test(msg) || e.name === "TypeError";
					if (dropped && desktop) {
						sawDrop = true;
						clearTimeout(watch);
						return;
					}
					clearTimeout(watch);
					stop(msg || "restart failed");
				});
		}

		function detectHostTheme() {
			try {
				if (typeof document !== "undefined") {
					const root = document.documentElement;
					if (document.body?.hasAttribute("data-ds-dark-theme") || root?.hasAttribute("data-ds-dark-theme")) return "dusk";
					const scheme = (root.style.colorScheme || getComputedStyle(root).colorScheme || getComputedStyle(root).getPropertyValue("color-scheme") || "").toLowerCase();
					if (scheme.includes("dark")) return "dusk";
					if (scheme.includes("light")) return "white";
				}
				if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
					return "dusk";
				}
			} catch { /* ignore */ }
			return "white";
		}

		function readTheme() {
			return detectHostTheme();
		}

		function OriginalPromptEditor() {
            const [text, setText] = useState("");
            const [ready, setReady] = useState(false);
            const [busy, setBusy] = useState(false);
            const [notice, setNotice] = useState("");
            useEffect(() => {
                let cancelled = false;
                apiJson("/dsh-purge/override").then(data => {
                    if (cancelled) return;
                    if (!data || data.ok === false) throw new Error("读取未确认");
                    setText(typeof data.content === "string" ? data.content : "");
                    setReady(true);
                }).catch(() => { if (!cancelled) setNotice("提示词读取失败，请关闭后重新打开。"); });
                return () => { cancelled = true; };
            }, []);
            const save = async () => {
                if (!ready || busy) return;
                setBusy(true); setNotice("");
                try {
                    const result = await apiJson("/dsh-purge/override", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content: text }) });
                    setNotice(result?.ok ? "已保存；请新建会话使用。" : "保存结果未确认，请重新打开核对，不会自动重发。");
                } catch { setNotice("保存结果未确认，请重新打开核对，不会自动重发。"); }
                finally { setBusy(false); }
            };
            return h("section", { className: "dshp-sec" },
                h("h3", null, "原版提示词"),
                h("textarea", { "aria-label": "原版提示词", value: text, disabled: !ready || busy,
                    rows: 12, style: { width: "100%", boxSizing: "border-box", fontFamily: "monospace" },
                    onChange: event => setText(event.target.value) }),
                h("button", { type: "button", disabled: !ready || busy, onClick: save }, busy ? "保存中…" : "保存提示词"),
                h("p", { role: "status" }, notice));
        }

        function createOriginalSwitchModel({ request, publish, onVerified }) {
            let disposed = false, timer, deadline = 0, readGeneration = 0;
            let state = { enabled: null, known: false, busy: false, confirm: null, notice: "正在核对原版能力…" };
            const update = values => { if (!disposed) { state = { ...state, ...values }; publish(state); } };
            const again = () => {
                if (disposed) return;
                if (performance.now() > deadline) {
                    update({ busy: false, known: false, notice: "等待已结束，切换结果尚未确认。请点“核对当前状态”；不会自动重发。" }); return;
                }
                timer = setTimeout(refresh, 2000);
            };
            async function refresh() {
                if (disposed) return;
                clearTimeout(timer);
                const generation = ++readGeneration;
                try {
                    const data = await request("GET");
                    if (disposed || generation !== readGeneration) return;
                    if (data?.ok !== true) throw new Error("unconfirmed");
                    const operation = data.operation;
                    if (operation?.state === "running") {
                        if (!deadline) deadline = performance.now() + 180000;
                        update({ busy: true, known: false, confirm: null, notice: "正在切换并重启服务，请稍候…" }); again(); return;
                    }
                    if (typeof data.enabled !== "boolean") throw new Error("unconfirmed");
                    const matched = operation?.state === "succeeded" && operation.targetEnabled === data.enabled;
                    update({ enabled: data.enabled, known: true, busy: false, confirm: null,
                        notice: operation?.state === "unconfirmed" ? "上一笔切换结果未确认；下方显示刚核对的实际状态。不会自动重发。" : matched ? "切换完成。请重新加载页面，并新建会话使用。" : "已核对当前运行状态。" });
                    deadline = 0;
                    if (data.pluginStatus?.ready === true && data.pluginStatus.originalCapabilities?.enabled === data.enabled) onVerified(data.pluginStatus);
                } catch {
                    if (disposed || generation !== readGeneration) return;
                    update({ known: false, confirm: null, notice: state.busy ? "切换中暂时无法读取状态，正在核对；不会重发操作。" : "状态读取失败，请点“核对当前状态”。" });
                    if (state.busy) again();
                }
            }
            return {
                refresh,
                select(enabled) { if (!disposed && state.known && !state.busy && typeof enabled === "boolean" && enabled !== state.enabled) update({ confirm: enabled }); },
                cancel() { if (!state.busy) update({ confirm: null }); },
                async confirm() {
                    if (disposed || state.busy || !state.known || typeof state.confirm !== "boolean") return;
                    const enabled = state.confirm, expectedEnabled = state.enabled;
                    readGeneration++;
                    deadline = performance.now() + 180000;
                    update({ busy: true, known: false, confirm: null, notice: "正在提交切换请求…" });
                    try { await request("POST", { enabled, expectedEnabled }); }
                    catch { update({ notice: "提交结果尚未确认，正在只读核对；不会自动重发。" }); }
                    if (!disposed) await refresh();
                },
                dispose() { disposed = true; clearTimeout(timer); },
            };
        }

        function OriginalCapabilitiesSwitch({ onVerified }) {
            const [state, setState] = useState({ enabled: null, known: false, busy: false, confirm: null, notice: "正在核对原版能力…" });
            const model = useRef(null);
            useEffect(() => {
                const controller = createOriginalSwitchModel({
                    request: (method, body) => apiJson("/__harness/capabilities", { method,
                        headers: { "x-harness-local": "1", ...(method === "POST" ? { "content-type": "application/json" } : {}) },
                        ...(body === undefined ? {} : { body: JSON.stringify(body) }) }),
                    publish: setState, onVerified,
                });
                model.current = controller; controller.refresh();
                return () => { model.current = null; controller.dispose(); };
            }, []);
            return h("section", { className: "dshp-sec", "aria-label": "原版能力开关" },
                h("label", { style: { display: "flex", gap: "10px", alignItems: "center", fontWeight: "600" } },
                    h("input", { type: "checkbox", role: "switch", "aria-label": "启用原版能力",
                        checked: state.enabled === true, disabled: !state.known || state.busy,
                        onChange: event => model.current?.select(event.target.checked) }), "原版能力"),
                h("p", { role: "status", "aria-live": "polite" }, state.notice),
                h("p", null, "切换会重启 Harness 服务，请先等待任务结束；终端连接可能中断。切换后新建会话。"),
                typeof state.confirm === "boolean" ? h("div", { role: "group", "aria-label": "确认切换原版能力" },
                    h("p", null, state.confirm ? "启用后，提示词、权限与沙盒按原版补丁运行。确认现在启用并重启？" : "确认停用原版能力并重启，回到日常运行时？"),
                    h("button", { type: "button", onClick: () => model.current?.confirm() }, state.confirm ? "确认启用并重启" : "确认停用并重启"),
                    h("button", { type: "button", onClick: () => model.current?.cancel() }, "取消")) : null,
                h("button", { type: "button", disabled: state.busy, onClick: () => model.current?.refresh() }, "核对当前状态"),
                h("button", { type: "button", disabled: state.busy, onClick: () => window.location.reload() }, "重新加载 Harness"));
        }

		function SettingsRoot(props) {
			const t = typeof props.t === "function" ? props.t : ((key) => key);
			const [theme, setTheme] = useState(readTheme);
            const [capabilities, setCapabilities] = useState(null);
			useEffect(() => {
				let cancelled = false;
				let timer = 0;
				const syncFromHost = () => {
					if (!cancelled) setTheme(detectHostTheme());
				};
				const syncSoon = () => {
					if (timer) window.clearTimeout(timer);
					timer = window.setTimeout(syncFromHost, 50);
				};
				syncFromHost();
				let mq;
				try {
					mq = window.matchMedia?.("(prefers-color-scheme: dark)");
					mq?.addEventListener?.("change", syncFromHost);
				} catch { /* ignore */ }
				let obs;
				try {
					obs = new MutationObserver(syncSoon);
					if (document.body) obs.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class", "style"] });
					obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class", "style"] });
				} catch { /* ignore */ }
				return () => {
					cancelled = true;
					if (timer) window.clearTimeout(timer);
					try { mq?.removeEventListener?.("change", syncFromHost); } catch { /* ignore */ }
					try { obs?.disconnect(); } catch { /* ignore */ }
				};
			}, []);
			translate = t;
			return h("div", { className: "dshp-root", "data-theme": theme },
				h("style", null, PURGE_CSS),
                h(OriginalCapabilitiesSwitch, { onVerified: setCapabilities }),
				h("section", { className: "dshp-sec" },
					h("h3", null, "合并版 · 原版能力"),
                    h("p", { role: "status" }, capabilities ? (capabilities.originalCapabilities.enabled ? "原版能力已启用：原版运行时补丁与提示词生效。" : "原版能力已停用：当前采用日常改进版。") : "正在核对当前模式；尚未确认。"),
					h("p", null, "使用独立官方 Harness 运行时。当前权限与执行方式以会话权限菜单为准。"),
					h("ul", null,
						h("li", null, capabilities?.originalCapabilities.enabled ? "原版能力启用期间，提示词、权限与沙盒按原版补丁运行；会话权限标签不代表日常模式的审批保障。" : "用户已授权的 VM 完全访问档位可自动执行，无需逐个工具批准；人工审批档位仍逐次确认。"),
						h("li", null, "日常模式沿用官方权限配置；显式启用原版能力时切换至专用原版运行时。Mac 与 VM 隔离设置独立。"),
						h("li", null, "证据默认是声明；匹配真实执行回执才可升级。凭据默认隐藏。"),
					),
					h("p", null, "使用上方开关启用或停用原版能力。原有命令入口继续保留；项目、会话和工作台共用。"),
					h("p", null, "完整原版安装继续保留；模式开关不会覆盖它。原版自动更新不用于合并版。Mac 不授予完全访问。"),
                    capabilities?.originalCapabilities.enabled ? h("p", null, "补丁状态：", String(capabilities.patches_applied), " / ", String(capabilities.patches_total), " 已应用；跳过 ", String(capabilities.patches_skipped)) : null,
				),
                capabilities?.originalCapabilities.enabled ? h(OriginalPromptEditor) : null,
                capabilities?.originalCapabilities.enabled ? h(RulesSection) : null,
			);
		}

		const REWIND_CSS = `
.dshp-rewind-wrap{position:relative;display:inline-flex}
.dshp-rewind{appearance:none;display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 8px;border:0;border-radius:8px;background:transparent;color:var(--dsw-alias-label-secondary,currentColor);font:12px/1 var(--ds-font-sans,system-ui,sans-serif);cursor:pointer}
.dshp-rewind:hover:not(:disabled){background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12));color:var(--dsw-alias-label-primary,currentColor)}
.dshp-rewind:disabled{opacity:.4;cursor:default}
.dshp-rewind svg{display:block}
.dshp-rewind-menu{position:fixed;z-index:2147483000;box-sizing:border-box;min-width:220px;padding:4px;border:0;border-radius:12px;background:var(--dsw-specific-menu,#fff);color:var(--dsw-alias-label-primary,#1a1a1a);--dsw-elevation-stroke-color:var(--dsw-alias-border-l1);box-shadow:var(--dsw-elevation-prominent,0 8px 24px rgba(0,0,0,.16));transform:translateY(-100%)}
body[data-ds-dark-theme] .dshp-rewind-menu{background:var(--dsw-specific-menu,#32312d);color:var(--dsw-alias-label-primary,#e6e2db);--dsw-elevation-stroke-color:var(--dsw-alias-border-l1,#3f3d38);box-shadow:var(--dsw-elevation-prominent,0 10px 28px rgba(0,0,0,.45))}
.dshp-rewind-item{display:flex;flex-direction:column;gap:2px;width:100%;padding:8px 10px;border:0;border-radius:8px;background:transparent;color:inherit;text-align:left;cursor:pointer;font:12px/1.3 var(--ds-font-sans,system-ui,sans-serif)}
.dshp-rewind-item:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12))}
.dshp-rewind-item b{font-size:13px;font-weight:600;color:var(--dsw-alias-label-primary,inherit)}
.dshp-rewind-item span{color:var(--dsw-alias-label-tertiary,#9a958c);font-size:11px}
body[data-ds-dark-theme] .dshp-rewind-item span{color:var(--dsw-alias-label-tertiary,#a8a39a)}
.dshp-continue{appearance:none;display:inline-flex;align-items:center;gap:4px;height:28px;padding:0 8px;border:0;border-radius:8px;background:transparent;color:var(--dsw-alias-label-secondary,currentColor);font:12px/1 var(--ds-font-sans,system-ui,sans-serif);cursor:pointer}
.dshp-continue:hover:not(:disabled){background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12));color:var(--dsw-alias-label-primary,currentColor)}
.dshp-continue:disabled{opacity:.4;cursor:default}
.dshp-continue.is-ready{color:var(--dsw-alias-label-primary,currentColor)}
.dshp-continue svg{display:block}
`;
		const DRAFT_KEY = "dshp-rewind-draft:";
		const ARM_KEY = "dshp-rewind-arm:";
		const FILL_DELAYS = [0, 50, 180, 400, 800];
		const ARM_TTL_MS = 45 * 1000;
		let rewindSeenAt = 0;
		let rewindSessions = null;
		let rewindHost = null;
		let rewindWorkspace = null;
		let rewindConversation = null;
		let pendingComposer = { sessionId: "", text: "", at: 0 };
		let armedFill = { sessionId: "", text: "", at: 0 };

		function rewindText(t, key, fallback) {
			try {
				if (typeof t === "function") {
					const value = t(key);
					if (value && value !== key) return value;
				}
			} catch { /* ignore */ }
			return fallback;
		}

		const drillSessionId = () => {
			const selection = rewindWorkspace?.selection;
			if (typeof selection?.getSnapshot === "function") return selection.getSnapshot()?.sessionId || "";
			return currentSessionId(rewindSessions);
		};

		function currentSessionId(sessions) {
			try {
				const selected = rewindWorkspace?.selection?.getSnapshot?.()?.sessionId;
				if (typeof selected === "string" && selected) return selected;
			} catch { /* ignore */ }
			try {
				const snap = sessions?.list?.getSnapshot?.();
				if (typeof snap?.current === "string" && snap.current) return snap.current;
			} catch { /* ignore */ }
			return "";
		}

		function sessionKnown(sessions, sessionId) {
			try {
				const snap = sessions?.list?.getSnapshot?.();
				if (!snap || !sessionId) return false;
				if (snap.byId && Object.prototype.hasOwnProperty.call(snap.byId, sessionId)) return true;
				if (Array.isArray(snap.ids) && snap.ids.includes(sessionId)) return true;
			} catch { /* ignore */ }
			return false;
		}

		function waitMs(ms) {
			return new Promise((resolve) => window.setTimeout(resolve, ms));
		}

		function isPluginDraft(text) {
			const value = String(text || "").trim();
			if (!value) return false;
			return /^\[MNEMON\]/i.test(value)
				|| /MNEMON RUNTIME MEMORY SNAPSHOT/i.test(value)
				|| /^MNEMON VIEW TOOLS/im.test(value);
		}

		function writeDraft(sessionId, text) {
			if (!sessionId) return;
			const value = isPluginDraft(text) ? "" : (text || "");
			pendingComposer = { sessionId, text: value, at: Date.now() };
			try { sessionStorage.setItem(DRAFT_KEY + sessionId, value); } catch { /* ignore */ }
		}

		function peekDraft(sessionId) {
			if (!sessionId) return "";
			if (pendingComposer.sessionId === sessionId && pendingComposer.text) return pendingComposer.text;
			try { return sessionStorage.getItem(DRAFT_KEY + sessionId) || ""; } catch { return ""; }
		}

		function clearStoredDraft(sessionId) {
			if (!sessionId) return;
			if (pendingComposer.sessionId === sessionId) pendingComposer = { sessionId: "", text: "", at: 0 };
			try { sessionStorage.removeItem(DRAFT_KEY + sessionId); } catch { /* ignore */ }
			try { sessionStorage.removeItem(ARM_KEY + sessionId); } catch { /* ignore */ }
		}

		function armComposerFill(sessionId, text) {
			if (!sessionId || !text || isPluginDraft(text)) return;
			const at = Date.now();
			armedFill = { sessionId, text, at };
			writeDraft(sessionId, text);
			try { sessionStorage.setItem(ARM_KEY + sessionId, String(at)); } catch { /* ignore */ }
		}

		function takeArmedFill(sessionId) {
			if (!sessionId) return "";
			let text = "";
			let at = 0;
			if (armedFill.sessionId === sessionId && armedFill.text) {
				text = armedFill.text;
				at = armedFill.at;
			} else {
				text = peekDraft(sessionId);
				try { at = Number(sessionStorage.getItem(ARM_KEY + sessionId) || 0); } catch { at = 0; }
			}
			if (!text || !at || Date.now() - at > ARM_TTL_MS) {
				if (text && (!at || Date.now() - at > ARM_TTL_MS)) clearStoredDraft(sessionId);
				return "";
			}
			clearStoredDraft(sessionId);
			armedFill = { sessionId: "", text: "", at: 0 };
			return text;
		}

		function conversationFace() {
			if (rewindConversation) return rewindConversation;
			const host = rewindHost;
			if (host?.conversation) return host.conversation;
			if (typeof host?.get === "function") {
				try { return host.get("conversation"); } catch { return undefined; }
			}
			return undefined;
		}

		function conversationInput(sessionId) {
			try {
				const input = conversationFace()?.input;
				if (!input || !sessionId) return null;
				if (typeof input.shell === "function") {
					try { return input.shell(sessionId); } catch { /* session not retained yet */ }
				}
				const sessions = rewindHost?.sessions || rewindSessions;
				const actx = typeof sessions?.scope === "function" ? sessions.scope(sessionId) : undefined;
				if (typeof input.for === "function" && actx) return input.for(actx);
				return null;
			} catch {
				return null;
			}
		}

		function liveDraft(sessionId, inputActions) {
			try {
				const fromActions = inputActions?.state?.getSnapshot?.()?.draft;
				if (typeof fromActions === "string") return fromActions;
			} catch { /* ignore */ }
			try {
				const draft = conversationInput(sessionId)?.state?.getSnapshot?.()?.draft;
				if (typeof draft === "string") return draft;
			} catch { /* ignore */ }
			return "";
		}

		function hostSetDraft(sessionId, text) {
			if (!sessionId) return false;
			try {
				const input = conversationInput(sessionId);
				if (input && typeof input.setDraft === "function") {
					input.setDraft(text || "");
					return true;
				}
			} catch { /* ignore */ }
			return false;
		}

		function fillComposer(inputActions, text) {
			if (inputActions && typeof inputActions.setDraft === "function") {
				try { inputActions.setDraft(text || ""); } catch { /* ignore */ }
			}
		}

		function scheduleComposerFill(sessionId, text, inputActions) {
			if (!sessionId || !text || isPluginDraft(text)) return () => {};
			let stopped = false;
			let filled = false;
			const timers = [];
			const tryFill = () => {
				if (stopped) return;
				const current = liveDraft(sessionId, inputActions);
				if (filled && current !== text) {
					stopped = true;
					return;
				}
				if (current && current !== text) {
					stopped = true;
					return;
				}
				fillComposer(inputActions, text);
				hostSetDraft(sessionId, text);
				filled = true;
			};
			for (const ms of FILL_DELAYS) timers.push(window.setTimeout(tryFill, ms));
			return () => {
				stopped = true;
				for (const t of timers) { try { window.clearTimeout(t); } catch { /* ignore */ } }
			};
		}

		function scheduleEchoClear(sessionId, inputActions) {
			if (!sessionId) return () => {};
			let last = "";
			let stopped = false;
			const timers = [];
			const tryClear = () => {
				if (stopped || !last) return;
				const current = String(liveDraft(sessionId, inputActions) || "").trim();
				if (!current) {
					stopped = true;
					return;
				}
				if (current !== last) return;
				fillComposer(inputActions, "");
				hostSetDraft(sessionId, "");
				clearStoredDraft(sessionId);
				stopped = true;
			};
			apiJson("/dsh-purge/last-user?sessionId=" + encodeURIComponent(sessionId)).then((data) => {
				if (stopped) return;
				last = String(data?.text || "").trim();
				if (!last || isPluginDraft(last)) return;
				tryClear();
				for (const ms of [0, 50, 180, 400]) timers.push(window.setTimeout(tryClear, ms));
			}).catch(() => {});
			return () => {
				stopped = true;
				for (const t of timers) { try { window.clearTimeout(t); } catch { /* ignore */ } }
			};
		}

		async function dropInheritedQueue(sessions, sessionId) {
			if (!sessions || !sessionId) return;
			const drop = async () => {
				try {
					const actx = typeof sessions.scope === "function" ? sessions.scope(sessionId) : undefined;
					const face = typeof sessions.sessionOf === "function" ? sessions.sessionOf(actx) : undefined;
					const queue = face?.getSnapshot?.()?.queue || [];
					for (const item of queue) {
						const id = item?.id || item?.itemId;
						if (!id) continue;
						try { await face.updateQueue?.(id, { kind: "remove" }); } catch { /* ignore */ }
					}
				} catch { /* ignore */ }
			};
			await drop();
			window.setTimeout(() => { drop(); }, 80);
		}

		async function openRewoundSession(sessions, sessionId) {
			if (!sessionId) return;
			const workspace = rewindWorkspace;
			let lastError = null;
			for (let attempt = 0; attempt < 25; attempt += 1) {
				if (sessions && typeof sessions.refresh === "function" && !sessionKnown(sessions, sessionId)) {
					try { await sessions.refresh(); } catch (error) { lastError = error; }
				}
				const known = sessionKnown(sessions, sessionId);
				if (known || typeof sessions?.open === "function") {
					try {
						if (workspace && typeof workspace.openSession === "function") {
							workspace.openSession(sessionId);
						} else if (typeof sessions?.open === "function") {
							sessions.open(sessionId);
						} else {
							throw new Error("Cannot open the rewound session");
						}
						const selected = workspace?.selection?.getSnapshot?.()?.sessionId;
						if (!workspace || selected === sessionId) {
							await dropInheritedQueue(sessions, sessionId);
							window.setTimeout(() => { dropInheritedQueue(sessions, sessionId); }, 250);
							return;
						}
					} catch (error) {
						lastError = error;
					}
				}
				await waitMs(120);
			}
			throw new Error((lastError && lastError.message) || "The rewound session did not open");
		}

		class RewindSafe extends Component {
			constructor(p) { super(p); this.state = { failed: false }; }
			static getDerivedStateFromError() { return { failed: true }; }
			componentDidCatch(error) { try { console.error("[dsh-purge] rewind slot:", error); } catch { /* ignore */ } }
			render() {
				if (this.state.failed) return h(RewindFallback, this.props);
				return h(RewindButton, this.props);
			}
		}

		class ContinueSafe extends Component {
			constructor(p) { super(p); this.state = { failed: false }; }
			static getDerivedStateFromError() { return { failed: true }; }
			componentDidCatch(error) { try { console.error("[dsh-purge] continue slot:", error); } catch { /* ignore */ } }
			render() {
				if (this.state.failed) {
					return h("button", {
						type: "button",
						className: "dshp-continue",
						title: rewindText(translate, "continue.label", "Continue"),
						onMouseDown: (e) => e.preventDefault(),
						onClick: async () => {
							const sessionId = currentSessionId(rewindSessions);
							if (!sessionId) return;
							try {
								const data = await apiJson("/dsh-purge/continue", {
									method: "POST",
									headers: { "content-type": "application/json" },
									body: JSON.stringify({ sessionId, force: true }),
								});
								if (!data || !data.ok) throw new Error((data && data.error) || "continue");
							} catch (e) {
								window.alert(rewindText(translate, "continue.fail", "Continue failed: {error}").replace("{error}", String((e && e.message) || e)));
							}
						},
					}, rewindText(translate, "continue.label", "Continue"));
				}
				return h(ContinueButton, this.props);
			}
		}

		function ContinueButton(props) {
			const t = props.t || translate;
			const sessions = rewindSessions;
			const sessionId = props.sessionId || currentSessionId(sessions);
			const [busy, setBusy] = useState(false);
			const [notice, setNotice] = useState("");
			const [info, setInfo] = useState(null);

			useEffect(() => {
				if (!sessionId) {
					setInfo(null);
					return;
				}
				let cancelled = false;
				const tick = () => {
					apiJson("/dsh-purge/continue?sessionId=" + encodeURIComponent(sessionId))
						.then((data) => { if (!cancelled && data && data.ok) setInfo(data); })
						.catch(() => {});
				};
				tick();
				const timer = window.setInterval(tick, 1200);
				return () => {
					cancelled = true;
					window.clearInterval(timer);
				};
			}, [sessionId]);

			const canContinue = Boolean(info && info.canContinue);
			const left = info ? Math.max(0, (info.continueMax || 0) - (info.continueUsed || 0)) : 0;
			const runContinue = async () => {
				if (!sessionId || busy || !canContinue) return;
				setBusy(true);
				setNotice("");
				try {
					const data = await apiJson("/dsh-purge/continue", {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({ sessionId }),
					});
					if (!data || !data.ok) throw new Error((data && data.error) || "continue");
					setInfo((prev) => prev ? { ...prev, ...data, canContinue: false, continueUsed: data.used } : data);
				} catch (e) {
					setNotice(rewindText(t, "continue.fail", "Continue failed: {error}").replace("{error}", String((e && e.message) || e)));
				} finally {
					setBusy(false);
				}
			};

			const label = busy
				? rewindText(t, "continue.busy", "Continuing…")
				: rewindText(t, "continue.label", "Continue");
			const title = notice
				|| (canContinue
					? rewindText(t, "continue.ready", "Continue ({left} left)").replace("{left}", String(left))
					: (info && info.reason && left <= 0
						? rewindText(t, "continue.limit", "Continue limit reached")
						: rewindText(t, "continue.aria", "Continue after an abnormal stop")));
			return h("button", {
				type: "button",
				className: "dshp-continue" + (canContinue ? " is-ready" : ""),
				title,
				"aria-label": rewindText(t, "continue.aria", "Continue after an abnormal stop"),
				disabled: busy || !sessionId || !canContinue,
				onMouseDown: (e) => e.preventDefault(),
				onClick: (e) => {
					e.preventDefault();
					e.stopPropagation();
					runContinue();
				},
			},
				h("svg", { viewBox: "0 0 16 16", width: "14", height: "14", "aria-hidden": true },
					h("path", { fill: "currentColor", d: "M4.2 2.8v10.4L13 8 4.2 2.8z" }),
				),
				label,
			);
		}

		function rewindMenuNode(t, menuPos, menuRef, runRewind) {
			const menu = h("div", {
				className: "dshp-rewind-menu",
				role: "menu",
				ref: menuRef,
				style: menuPos ? { left: menuPos.left + "px", top: menuPos.top + "px" } : { left: "8px", bottom: "48px", transform: "none" },
			},
				h("button", {
					type: "button",
					className: "dshp-rewind-item",
					onMouseDown: (e) => { e.preventDefault(); e.stopPropagation(); },
					onClick: (e) => { e.preventDefault(); e.stopPropagation(); runRewind("once"); },
				},
					h("b", null, rewindText(t, "rewind.once", "Undo last step")),
					h("span", null, rewindText(t, "rewind.once.hint", "Withdraw the last step into a new session that keeps earlier context; the line returns to the box")),
				),
				h("button", {
					type: "button",
					className: "dshp-rewind-item",
					onMouseDown: (e) => { e.preventDefault(); e.stopPropagation(); },
					onClick: (e) => { e.preventDefault(); e.stopPropagation(); runRewind("round"); },
				},
					h("b", null, rewindText(t, "rewind.round", "Undo last turn")),
					h("span", null, rewindText(t, "rewind.round.hint", "Withdraw the last turn (and its subagents) into a new session that keeps earlier context; the line returns to the box")),
				),
			);
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function" && typeof document !== "undefined") {
					return rd.createPortal(menu, document.body);
				}
			} catch { /* 没有 portal 时菜单仍挂在按钮旁 */ }
			return menu;
		}

		class RewindFallback extends Component {
			constructor(p) {
				super(p);
				this.state = { menu: false, busy: false, notice: "", menuPos: null };
				this.wrap = null;
				this.menuEl = null;
				this.onDoc = (event) => {
					if (this.wrap && this.wrap.contains(event.target)) return;
					if (this.menuEl && this.menuEl.contains(event.target)) return;
					this.setState({ menu: false });
				};
			}
			componentDidMount() {
				document.addEventListener("mousedown", this.onDoc);
			}
			componentWillUnmount() {
				document.removeEventListener("mousedown", this.onDoc);
			}
			run(mode) {
				const sessionId = this.props.sessionId || currentSessionId(rewindSessions);
				if (!sessionId || this.state.busy) return;
				this.setState({ busy: true, menu: false, notice: "" });
				apiJson("/dsh-purge/rewind", {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify({ sessionId, mode }),
				}).then(async (data) => {
					if (!data || !data.ok || !data.sessionId || data.cleared === false) {
						throw new Error((data && data.error) || "The previously sent content was not cleared");
					}
					if (data.at) rewindSeenAt = data.at;
					const text = isPluginDraft(data.text) ? "" : (data.text || "");
					armComposerFill(data.sessionId, text);
					await openRewoundSession(rewindSessions, data.sessionId);
					scheduleComposerFill(data.sessionId, text);
					this.setState({ busy: false });
				}).catch((e) => {
					this.setState({
						busy: false,
						notice: "Undo failed: " + String((e && e.message) || e),
					});
				});
			}
			openMenu() {
				const rect = this.wrap && this.wrap.getBoundingClientRect ? this.wrap.getBoundingClientRect() : null;
				this.setState({
					menu: !this.state.menu,
					notice: "",
					menuPos: rect ? { left: Math.max(8, rect.right - 228), top: Math.max(8, rect.top - 8) } : null,
				});
			}
			render() {
				const sessionId = this.props.sessionId || currentSessionId(rewindSessions);
				const t = this.props.t || translate;
				const label = this.state.busy ? "Undoing…" : (this.state.notice ? this.state.notice.slice(0, 18) : "Undo");
				return h("div", { className: "dshp-rewind-wrap", ref: (node) => { this.wrap = node; } },
					h("style", null, REWIND_CSS),
					h("button", {
						type: "button",
						className: "dshp-rewind",
						disabled: this.state.busy || !sessionId,
						onMouseDown: (e) => e.preventDefault(),
						onClick: (e) => { e.preventDefault(); this.openMenu(); },
					}, label),
					this.state.menu ? rewindMenuNode(t, this.state.menuPos, (node) => { this.menuEl = node; }, (mode) => this.run(mode)) : null,
				);
			}
		}

		function RewindButton(props) {
			const t = props.t || translate;
			const sessions = rewindSessions;
			const inputActions = props.inputActions;
			const sessionId = props.sessionId || currentSessionId(sessions);
			const wrapRef = useRef(null);
			const menuRef = useRef(null);
			const [busy, setBusy] = useState(false);
			const [notice, setNotice] = useState("");
			const [menu, setMenu] = useState(false);
			const [menuPos, setMenuPos] = useState(null);

			useEffect(() => {
				if (!sessionId) return;
				const armed = takeArmedFill(sessionId);
				if (armed) {
					scheduleComposerFill(sessionId, armed, inputActions);
					return;
				}
				scheduleEchoClear(sessionId, inputActions);
			}, [sessionId, inputActions]);

			useEffect(() => {
				if (!menu) return;
				const onDoc = (event) => {
					if (wrapRef.current && wrapRef.current.contains(event.target)) return;
					if (menuRef.current && menuRef.current.contains(event.target)) return;
					setMenu(false);
				};
				document.addEventListener("mousedown", onDoc);
				return () => document.removeEventListener("mousedown", onDoc);
			}, [menu]);

			const runRewind = async (mode) => {
				if (!sessionId || busy) return;
				setBusy(true);
				setMenu(false);
				setNotice("");
				try {
					const data = await apiJson("/dsh-purge/rewind", {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({ sessionId, mode }),
					});
					if (!data || !data.ok || !data.sessionId || data.cleared === false) {
						throw new Error((data && data.error) || "The previously sent content was not cleared");
					}
					if (data.at) rewindSeenAt = data.at;
					const text = isPluginDraft(data.text) ? "" : (data.text || "");
					armComposerFill(data.sessionId, text);
					await openRewoundSession(sessions, data.sessionId);
					scheduleComposerFill(data.sessionId, text);
				} catch (e) {
					const message = rewindText(t, "rewind.fail", "Undo failed: {error}").replace("{error}", String((e && e.message) || e));
					setNotice(message);
				} finally {
					setBusy(false);
				}
			};

			const onClick = (event) => {
				event?.preventDefault?.();
				event?.stopPropagation?.();
				if (!sessionId || busy) return;
				if (menu) {
					setMenu(false);
					return;
				}
				const rect = wrapRef.current?.getBoundingClientRect?.();
				if (rect) {
					setMenuPos({
						left: Math.max(8, rect.right - 228),
						top: Math.max(8, rect.top - 8),
					});
				}
				setNotice("");
				setMenu(true);
			};

			const failLabel = notice
				? (notice.length > 18 ? notice.slice(0, 18) + "…" : notice)
				: "";
			const label = busy
				? rewindText(t, "rewind.busy", "Undoing…")
				: (failLabel || rewindText(t, "rewind.label", "Undo"));
			const title = notice || rewindText(t, "rewind.aria", "Undo");
			return h("div", { className: "dshp-rewind-wrap", ref: wrapRef },
				h("style", null, REWIND_CSS),
				h("button", {
					type: "button",
					className: "dshp-rewind",
					title,
					"aria-label": rewindText(t, "rewind.aria", "Undo"),
					"aria-expanded": menu ? "true" : "false",
					disabled: busy || !sessionId,
					onMouseDown: (e) => e.preventDefault(),
					onClick,
				},
					h("svg", { viewBox: "0 0 16 16", width: "14", height: "14", "aria-hidden": true },
						h("path", {
							fill: "currentColor",
							d: "M7.2 3.2 3.4 7l3.8 3.8V8.6c2.8 0 4.7.7 5.9 2.3-.2-2.8-1.9-5.2-5.9-5.6V3.2z",
						}),
					),
					label,
				),
				menu ? rewindMenuNode(t, menuPos, menuRef, runRewind) : null,
			);
		}

		function installRewindWatch(ctx) {
			const sessions = ctx.sessions;
			if (!sessions) return () => {};
			const tick = async () => {
				try {
					const data = await apiJson("/dsh-purge/rewind");
					if (!data || !data.sessionId || !data.at || data.at <= rewindSeenAt) return;
					rewindSeenAt = data.at;
					const current = currentSessionId(sessions);
					if (current && current !== data.parentId) return;
					const text = isPluginDraft(data.text) ? "" : (data.text || "");
					armComposerFill(data.sessionId, text);
					scheduleComposerFill(data.sessionId, text);
					await openRewoundSession(sessions, data.sessionId);
					scheduleComposerFill(data.sessionId, text);
				} catch { /* ignore */ }
			};
			const timer = window.setInterval(tick, 1200);
			return () => window.clearInterval(timer);
		}

		/* __DSH_PURGE_DRILL_BEGIN__ */
		// 内嵌演练台（源码在 lib/redteam，已并进本插件）
		const __dshPurgeDrill = (() => {
			var module = { exports: {} };
			var exports = module.exports;

// Browser-only helper, inlined by build-client.mjs and tested without React.
function createBindingMonitor({ getSessionId, read, publish, now = Date.now }) {
  let selected, generation = 0, controller, latest, checkedAt, disposed = false
  const check = (force = false) => {
    if (disposed) return
    let id
    try { id = String(getSessionId?.() || '') }
    catch { publish({ state: 'unavailable', error: '无法读取当前会话' }); return }
    if (id === selected && !force) {
      if (latest && latest.state !== 'stale' && (now() - checkedAt >= 60000 || now() < checkedAt)) {
        latest = { ...latest, state: 'stale' }; publish(latest)
      }
      return
    }
    selected = id; const token = ++generation
    controller?.abort(); controller = new AbortController(); latest = undefined
    if (!id) { publish({ state: 'no-session' }); return }
    publish({ state: 'checking', sessionId: id })
    let request
    try { request = read(id, controller.signal) } catch (error) { request = Promise.reject(error) }
    Promise.resolve(request).then(result => {
      if (disposed || token !== generation || getSessionId?.() !== id) return
      if (result?.sessionId !== id || !['bound', 'unbound', 'unavailable'].includes(result?.state) || (result.state === 'bound' && (typeof result.engagement !== 'string' || !result.engagement))) throw new Error('绑定结果与当前聊天不匹配')
      checkedAt = now(); latest = { ...result, checkedAt }; publish(latest)
    }).catch(error => {
      if (!disposed && token === generation) publish({ state: 'unavailable', sessionId: id, error: error.message })
    })
  }
  return { check, dispose() { disposed = true; generation++; controller?.abort() } }
}

// Self-contained factories, embedded by scripts/build-client.mjs; no import-time I/O.
function createJointPanel(React,api,{storage=()=>globalThis.localStorage,exclusive=async(_eng,fn)=>fn()}={}){
 const h=React.createElement,states={running:'运行中',completed:'所选步骤已结束',partial:'覆盖不完整',failed:'失败',cancelled:'已取消',interrupted:'中断',unconfirmed:'停止或结果未确认','timed-out':'预算到期',unavailable:'工具不可用','not-run':'未运行',pending:'待运行'};
 const validTask=(v,eng)=>v===null||v&&typeof v.id==='string'&&v.engagement===eng&&Object.hasOwn(states,v.state)&&Number.isSafeInteger(v.scopeRevision)&&Array.isArray(v.steps)&&v.steps.length<=6&&v.steps.every(s=>s&&['semgrep','trivy','zap','kali','rea','pentagi'].includes(s.tool)&&Object.hasOwn(states,s.state))&&Number.isSafeInteger(v.findings)&&typeof v.cleanupVerified==='boolean';
 const parse=(v,eng)=>{if(v?.ok!==true||v.engagement!==eng)throw Error(typeof v?.error==='string'?v.error:'联合回执未确认');return v};
 return function JointPanel({engagement,profile}){
  const [plan,setPlan]=React.useState(null),[task,setTask]=React.useState(null),[selected,setSelected]=React.useState([]),[busy,setBusy]=React.useState(false),[error,setError]=React.useState(''),[pending,setPending]=React.useState(false),alive=React.useRef(true),requesting=React.useRef(false);
  React.useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
  const key='dsh-joint-request-v1:'+encodeURIComponent(engagement);
  const saved=()=>{const raw=storage().getItem(key);if(!raw)return null;const v=JSON.parse(raw);if(v?.engagement!==engagement||typeof v.requestId!=='string'||!/^[A-Za-z0-9_-]{8,100}$/.test(v.requestId))throw Error('联合恢复提示无效，请核对后台原任务');return v};
  const accept=v=>{parse(v,engagement);if(!validTask(v.task,engagement))throw Error('联合任务回执与项目不匹配');if(alive.current)setTask(v.task);return v.task};
  const perform=async operation=>{
   if(requesting.current)return;requesting.current=true;if(alive.current){setBusy(true);setError('')}
   try{await operation()}catch(e){if(alive.current)setError(String(e?.message||'联合结果未确认'))}finally{requesting.current=false;if(alive.current)setBusy(false)}
  };
  const refresh=()=>perform(async()=>{
   const next=parse(await api({op:'securityJoint',engagement,action:'plan'}),engagement);
   if(!Number.isSafeInteger(next.profileRevision)||!Array.isArray(next.availableSteps)||next.availableSteps.some(s=>!['semgrep','trivy','zap'].includes(s))||typeof next.kaliAllowed!=='boolean')throw Error('联合范围资料无效');
   if(alive.current){setPlan(next);setSelected([...next.availableSteps.filter(s=>s!=='zap'),...(next.kaliAllowed?['kali']:[])])}
   const original=saved(),result=await api({op:'securityJoint',engagement,action:'status',...(original?{requestId:original.requestId}:{})}),current=accept(result);
   if(original&&(current||result.requestState==='rejected'))storage().removeItem(key);if(alive.current){setPending(!!original&&!current&&result.requestState!=='rejected');if(result.requestState==='rejected')setError('原启动请求未受理：'+String(result.rejection??'请核对范围后重新提交'))}
  });
  const start=()=>perform(()=>exclusive(engagement,async()=>{
   if(saved()){if(alive.current)setPending(true);throw Error('已有启动请求待核对，请先查询原任务，不重发启动')}
   const request={op:'securityJoint',engagement,action:'start',profileRevision:profile.revision,steps:selected,budgetSeconds:360,requestId:globalThis.crypto?.randomUUID?.()||'joint-'+Date.now()+'-'+Math.random().toString(36).slice(2)};
   storage().setItem(key,JSON.stringify(request));if(alive.current)setPending(true);
   const current=accept(await api(request));if(!current)throw Error('启动未返回任务ID');storage().removeItem(key);if(alive.current)setPending(false);
  }));
  const update=action=>perform(async()=>accept(await api({op:'securityJoint',engagement,action,id:task.id,...(action==='wait'?{waitSeconds:15}:{})})));
  const download=()=>perform(async()=>{
   const report={version:1,engagement,task:null,findings:[],files:[],exclusions:[],diagnostics:[],artifacts:[]};
   for(const section of ['findings','files','exclusions','diagnostics','artifacts']){
    let cursor;for(let n=0;n<1001;n++){
     const result=parse(await api({op:'securityJoint',engagement,action:'report',id:task.id,section,limit:10,...(cursor?{cursor}:{})}),engagement),page=result.page;
     if(!validTask(result.task,engagement)||result.task.id!==task.id||!page||page.section!==section||!Array.isArray(page.items)||typeof page.complete!=='boolean'||!Number.isSafeInteger(page.total))throw Error('报告分页未确认');
     if(report.task&&report.task.snapshot?.id!==result.task.snapshot?.id)throw Error('报告副本已变化');report.task=result.task;report[section].push(...page.items);
     if(page.complete){if(report[section].length!==page.total)throw Error('报告明细不完整');break}
     if(typeof page.nextCursor!=='string'||page.nextCursor===cursor||n===1000)throw Error('报告续读未完成');cursor=page.nextCursor;
    }
   }
   if(!alive.current)return;const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='joint-review-'+task.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  const inProgress=task&&['running','cancelling'].includes(task.state),ready=plan&&plan.profileRevision===profile?.revision&&Date.parse(profile.expiresAt)>Date.now();
  const button=(label,fn,disabled=false)=>h('button',{type:'button',className:'rt-btn',onClick:fn,disabled:busy||disabled},label);
  return h('section',{className:'rt-card','aria-label':'联合安全审查'},h('div',{className:'rts-head'},h('h4',null,'联合安全审查'),h('span',{className:'rts-state'},'VM · 受管工具')),
   h('p',null,'源码副本 / 本地HTTP → 选择静态检查 / ZAP / Kali / REA / PentAGI → 统一证据报告'),h('p',{className:'rts-meta'},'Kali离线Python检查；REA＋reverse-skill静态JavaScript图。PentAGI子任务在禁网工作容器内读取副本，模型通过既有DeepSeek账号调用：最多16次请求、每次2048输出tokens，不是货币金额上限。默认360秒，聊天费用另计。'),
   plan?.webTarget&&h('p',{className:'rts-meta'},'ZAP目标：'+plan.webTarget.origin+' · 会发送本地请求；运行应用版本与源码副本关系未证明，刷新不默认勾选。'),button('核对联合范围与原任务',refresh),plan&&h('div',{className:'rts-tools'},...['semgrep','trivy','zap','kali','rea','pentagi'].map(tool=>{const allowed={kali:plan.kaliAllowed,rea:plan.reaAllowed,pentagi:plan.pentagiAllowed}[tool]??plan.availableSteps.includes(tool);return h('label',{key:tool},h('input',{type:'checkbox',checked:selected.includes(tool),disabled:busy||!allowed,onChange:e=>setSelected(old=>e.target.checked?[...old,tool]:old.filter(s=>s!==tool))}),' '+tool+(allowed?'':' · 未授权或未就绪'))})),
   plan&&!plan.kaliAllowed&&h('p',{className:'rts-meta'},'Kali副本交接尚未授权；可在上方项目范围勾选并确认保存。'),
   h('div',{className:'rts-actions'},button('启动联合审查',start,!ready||!selected.length||pending||inProgress),task&&button('等待原联合任务',()=>update('wait'),!inProgress),task&&button('取消或核对停止',()=>update('cancel'),!inProgress&&task.cleanupVerified),task&&button('下载联合报告 JSON',download,inProgress)),
   pending&&h('p',{className:'rts-alert'},'启动请求已保留；回执未确认时先核对原任务，不自动重发。'),error&&h('p',{className:'rts-alert',role:'alert'},error),
   task&&h('div',null,h('p',null,'任务：'+task.id+' · '+(states[task.state]||task.state)),h('p',null,'工具命中 '+task.findings+' 条 · 子任务模型请求 '+(task.modelCalls??0)+' 次 · 停止核对：'+(task.cleanupVerified?'已确认':'未确认')),task.snapshot&&h('p',{className:'rts-meta'},'副本 '+task.snapshot.id+' · '+task.snapshot.files+' 文件 · 排除路径 '+task.snapshot.excluded+' · 脱敏文件 '+task.snapshot.redactedFiles),...task.steps.map(s=>h('p',{key:s.tool},s.tool+'：'+(states[s.state]||s.state)+(s.id?' · '+s.id:''))),h('p',{className:'rts-meta'},'工具命中待验证；登录、越权、业务逻辑、架构、未选工具与排除内容仍未覆盖。')));
 };
}
function createSecurityTab(React,api,options={}){
 const h=React.createElement;
 const documentState=Object.hasOwn(options,'document')?options.document:globalThis.document,timers=options.timers??globalThis,now=options.now??Date.now;
 const visible=()=>documentState?.visibilityState!=='hidden';
 const toolNames={semgrep:'Semgrep · 代码检查',trivy:'Trivy · 依赖与配置',zap:'ZAP · 本地网页基线'};
 const statusNames={unverified:'待验证',confirmed:'已确认','false-positive':'误报',fixed:'已记录修复','retest-passed':'复测通过',reopened:'再次出现',running:'运行中',completed:'已完成',partial:'覆盖不完整',failed:'失败',cancelled:'已取消',interrupted:'中断'};
 const label=(labels,key,fallback=key)=>Object.hasOwn(labels,key)?labels[key]:fallback;
 const maintenanceNames={current:'已与官方版本核对',updated:'已更新','rolled-back':'已恢复原库'};
 const comparisonLabels={added:'新增命中位置',persisting:'仍存在的命中位置',notSeen:'已覆盖文件中未再次命中',uncovered:'覆盖未证实'};
 const comparisonValid=(value,request)=>value?.ok===true&&value.engagement===request.engagement&&value.baseRunId===request.baseRunId&&value.currentRunId===request.currentRunId&&typeof value.available==='boolean'&&(value.available?typeof value.notice==='string'&&typeof value.markdown==='string'&&typeof value.truncated==='boolean'&&Object.keys(comparisonLabels).every(key=>Number.isSafeInteger(value.summary?.[key])&&value.summary[key]>=0&&Array.isArray(value.items?.[key])&&value.items[key].length<=100&&value.items[key].every(item=>item&&['rule','title','severity','location'].every(field=>typeof item[field]==='string')&&validSubject(item.subject))):typeof value.reason==='string');
 const id=()=>globalThis.crypto?.randomUUID?.()||'request-'+Date.now()+'-'+Math.random().toString(36).slice(2);
 const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
 const string=(value,max=8192)=>typeof value==='string'&&value.length<=max;
 const optionalString=value=>value==null||string(value);
 const positive=value=>Number.isSafeInteger(value)&&value>0;
 const nonnegative=value=>Number.isSafeInteger(value)&&value>=0;
 const validSubject=value=>value==null||(record(value)&&value.kind==='package'&&[['name',240],['version',240],['path',800],['purl',1200],['key',64],['family',64]].every(([key,max])=>string(value[key],max))&&!!value.name&&/^[a-f0-9]{64}$/.test(value.key)&&/^[a-f0-9]{64}$/.test(value.family));
 const subjectText=value=>value.name+'@'+(value.version||'版本未记录')+(value.path?' · '+value.path:'');
 const date=value=>string(value,64)&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
 const isTool=value=>typeof value==='string'&&Object.hasOwn(toolNames,value);
 const reviewStates={observed:'已有完整工具观察',partial:'覆盖不完整',running:'运行中',unverified:'未验证',manual:'待人工验证'};
 const validReview=(v,data)=>record(v)&&v.version===1&&v.engagement===engagementAt(data)&&v.scopeRevision===(data.profile?.revision??0)&&v.complianceClaim===false&&Array.isArray(v.blockers)&&v.blockers.length<=10&&v.blockers.every(x=>string(x,240))&&Array.isArray(v.canStartTools)&&v.canStartTools.length<=3&&v.canStartTools.every(isTool)&&Array.isArray(v.checks)&&v.checks.length<=8&&new Set(v.checks.map(x=>x?.id)).size===v.checks.length&&v.checks.every(c=>record(c)&&['code','dependencies','secrets','web','authentication','authorization','business','architecture'].includes(c.id)&&string(c.label,80)&&Object.hasOwn(reviewStates,c.state)&&(c.tool===null||isTool(c.tool))&&(c.runId===null||string(c.runId,100)))&&string(v.notice,400);
 const engagementAt=data=>data.engagement;
 const toolList=value=>Array.isArray(value)&&value.length>0&&value.length<=3&&new Set(value).size===value.length&&value.every(isTool);
 const scopePath=value=>{if(!string(value)||!value.startsWith('/'))return null;const parts=[];for(const part of value.split('/')){if(part==='..')parts.pop();else if(part&&part!=='.')parts.push(part)}return'/'+parts.join('/')};
 const storage=()=>Object.hasOwn(options,'storage')?options.storage:globalThis.localStorage;
 const receiptKey=eng=>{if(!string(eng,240)||!eng||/[\x00-\x1f]/.test(eng))throw Error('项目标识无效');return'dsh-security-request-v1:'+encodeURIComponent(eng)};
 const locks=()=>Object.hasOwn(options,'locks')?options.locks:globalThis.navigator?.locks;
 const coordinated=()=>{try{return typeof locks()?.request==='function'}catch{return false}};
 const exclusive=async(eng,action)=>{
  let entered=false,callbackError;
  try{
   const manager=locks();if(typeof manager?.request!=='function')throw Error();
   await manager.request(receiptKey(eng),{mode:'exclusive',ifAvailable:true},async lock=>{
    if(!lock)return;entered=true;
    try{return await action()}catch(error){callbackError=error;throw error}
   });
  }catch{if(callbackError)throw callbackError;throw Error('多窗口协调不可用；请刷新核对，不会自动重发操作。')}
  if(!entered)throw Error('另一窗口正在处理本项目操作；请稍后刷新核对，不会排队或自动重发。');
 };
 const validRequest=(value,eng)=>{
  if(!record(value)||value.engagement!==eng||!string(value.requestId,100)||!/^[A-Za-z0-9_-]{8,100}$/.test(value.requestId))return false;
  const keys={securityScopeSave:['confirm','expiresAt','repoRoot','revision','tools','url'],securityStart:['profileRevision','tool'],securityReview:['id','revision','status','note']};
  if(typeof value.op!=='string'||!Object.hasOwn(keys,value.op))return false;
  const expected=['op','engagement','requestId',...keys[value.op],...(value.op==='securityStart'&&Object.hasOwn(value,'retestFindingId')?['retestFindingId']:[]),...(value.op==='securityScopeSave'&&Object.hasOwn(value,'authProfile')?['authProfile']:[]),...(value.op==='securityScopeSave'?['jointKali','jointRea','jointPentagi'].filter(k=>Object.hasOwn(value,k)):[])];
  if(Object.keys(value).sort().join(',')!==expected.sort().join(','))return false;
  if(value.op==='securityScopeSave')return value.confirm===true&&nonnegative(value.revision)&&string(value.repoRoot)&&!!value.repoRoot&&optionalString(value.url)&&date(value.expiresAt)&&toolList(value.tools)&&authName(value.authProfile)&&(!value.authProfile||!!value.url&&value.tools.includes('zap'))&&['jointKali','jointRea','jointPentagi'].every(k=>value[k]===undefined||typeof value[k]==='boolean');
  if(value.op==='securityStart')return positive(value.profileRevision)&&isTool(value.tool)&&(!Object.hasOwn(value,'retestFindingId')||positive(value.retestFindingId));
  return positive(value.id)&&positive(value.revision)&&['confirmed','false-positive','fixed'].includes(value.status)&&string(value.note,2000)&&value.note.trim().length>=5;
 };
 const readReceipt=eng=>{
  let raw;
  try{
   raw=storage().getItem(receiptKey(eng));if(raw===null)return{owner:eng,raw,request:null,error:''};
   if(typeof raw!=='string'||raw.length>16384)throw Error();const value=JSON.parse(raw);
   if(!record(value)||Object.keys(value).sort().join(',')!=='createdAt,request,version'||value.version!==1||!positive(value.createdAt)||value.createdAt>Date.now()+60000||!validRequest(value.request,eng))throw Error();
   return{owner:eng,raw,request:value.request,error:''};
  }catch{return{owner:eng,raw,request:null,error:'浏览器恢复记录无法读取或无效；写入已暂停，请核对已保存任务与记录。'}}
 };
 const persistReceipt=request=>{
  const current=readReceipt(request.engagement);if(current.error)throw Error(current.error);
  if(!validRequest(request,request.engagement))throw Error('恢复记录无法保存：请求内容无效。');
  if(current.request){if(JSON.stringify(current.request)!==JSON.stringify(request))throw Error('已有另一操作等待核对，请先处理恢复记录。');return current.request}
  const raw=JSON.stringify({version:1,createdAt:Date.now(),request});if(raw.length>16384)throw Error('恢复记录无法保存：请求内容过长。');
  try{const target=storage();target.setItem(receiptKey(request.engagement),raw);if(target.getItem(receiptKey(request.engagement))!==raw)throw Error()}catch{throw Error('浏览器恢复记录无法保存；操作未发送，请恢复浏览器存储后重新读取。')}
  return JSON.parse(raw).request;
 };
 const releaseReceipt=request=>{
  const current=readReceipt(request.engagement);if(current.error)throw Error(current.error);
  if(current.request&&JSON.stringify(current.request)===JSON.stringify(request))storage().removeItem(receiptKey(request.engagement));
 };
 const authName=value=>value==null||value===''||typeof value==='string'&&/^[a-z][a-z0-9_-]{0,47}$/.test(value);
 const validAuthentication=value=>{
  if(!record(value)||Object.keys(value).sort().join(',')!==['version','profile','revision','state','verification','before','after','scannerBefore','scannerAfter','checkedRequests'].sort().join(',')||value.version!==1||!authName(value.profile)||!value.profile||!['verified','unconfirmed'].includes(value.state)||value.verification!=='controller-and-zap-before-after'||!['before','after','scannerBefore','scannerAfter'].every(key=>typeof value[key]==='boolean')||![0,2].includes(value.checkedRequests)||!(value.revision===null||typeof value.revision==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)))return false;
  return value.state!=='verified'||!!value.revision&&value.checkedRequests===2&&value.before&&value.after&&value.scannerBefore&&value.scannerAfter;
 };
 const validProfile=value=>value===null||(record(value)&&positive(value.revision)&&string(value.repoRoot)&&value.repoRoot.length>0&&optionalString(value.url)&&date(value.expiresAt)&&toolList(value.tools)&&authName(value.authProfile)&&(!value.authProfile||!!value.url&&value.tools.includes('zap'))&&['jointKali','jointRea','jointPentagi'].every(k=>value[k]===undefined||typeof value[k]==='boolean'));
 const validSession=(value,profile)=>{
  if(!record(value)||Object.keys(value).sort().join(',')!==['version','profile','revision','state','expiresAt','checkedAt'].sort().join(',')||value.version!==1||value.profile!==profile||!date(value.checkedAt)||!['ready','expiring','expired','unavailable'].includes(value.state))return false;
  if(value.state==='unavailable')return value.revision===null&&value.expiresAt===null;
  if(typeof value.revision!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value.revision)||!date(value.expiresAt))return false;
  const remaining=Date.parse(value.expiresAt)-Date.parse(value.checkedAt);return value.state==='expired'?remaining<=0:value.state==='expiring'?remaining>0&&remaining<=300000:remaining>300000&&remaining<=31*86400000;
 };
 const validRuntime=value=>{
  if(!record(value)||typeof value.ready!=='boolean'||!(value.ready?string(value.version,128)&&value.version.length>0:optionalString(value.version))||!optionalString(value.reason)||!optionalString(value.warning)||(value.checkedAt!=null&&!date(value.checkedAt))||(value.cached!==undefined&&typeof value.cached!=='boolean'))return false;
  if(value.rules!=null&&(!record(value.rules)||!string(value.rules.version,128)||!positive(value.rules.count)||value.rules.count>1000||!Array.isArray(value.rules.languages)||!value.rules.languages.length||value.rules.languages.length>100||!value.rules.languages.every(language=>string(language,128)&&language.length>0)))return false;
  if(value.database!=null&&(!record(value.database)||(value.database.updatedAt!=null&&(!date(value.database.updatedAt)||!nonnegative(value.database.ageDays)))))return false;
  return value.lastUpdate==null||(record(value.lastUpdate)&&string(value.lastUpdate.state,128)&&date(value.lastUpdate.checkedAt));
 };
 const validSupplement=s=>record(s)&&Object.keys(s).sort().join(',')===['version','policy','candidateFiles','checkedFiles','skippedFiles','hints','truncated'].sort().join(',')&&s.version===1&&s.policy==='parser-text-1'&&['candidateFiles','checkedFiles','skippedFiles','hints'].every(k=>nonnegative(s[k]))&&s.candidateFiles<=20000&&s.checkedFiles<=20&&s.checkedFiles+s.skippedFiles===s.candidateFiles&&s.hints<=s.checkedFiles*3&&typeof s.truncated==='boolean';
 const validRun=value=>{
  if(!record(value)||!string(value.id,100)||!value.id||!isTool(value.tool)||!string(value.state,128)||!value.state||![0,1].includes(value.complete)||!date(value.started_at)||!optionalString(value.revision_ref)||!optionalString(value.error_code)||(value.details!==undefined&&!record(value.details)))return false;
  if(value.details?.authentication!==undefined&&(!validAuthentication(value.details.authentication)||value.tool!=='zap'||value.details.authentication.state==='unconfirmed'&&value.complete===1))return false;
  if(value.details?.supplemental!==undefined&&(!validSupplement(value.details.supplemental)||value.tool!=='semgrep'||value.complete===1))return false;
  const diagnostics=value.details?.diagnostics;
  if(diagnostics!=null&&(!record(diagnostics)||!nonnegative(diagnostics.total)||!Array.isArray(diagnostics.items)||diagnostics.items.length>20||diagnostics.items.length>diagnostics.total||typeof diagnostics.truncated!=='boolean'||diagnostics.items.some(d=>!record(d)||!string(d.code,80)||!string(d.path,400)||!(d.line===null||positive(d.line)))))return false;
  const snapshot=value.details?.comparisonSnapshot;
  return snapshot==null||(record(snapshot)&&typeof snapshot.available==='boolean'&&optionalString(snapshot.reason));
 };
 const validFinding=value=>record(value)&&positive(value.id)&&positive(value.revision)&&isTool(value.tool)&&['title','rule','location','evidence','note','severity','status'].every(key=>string(value[key]))&&!!value.status&&!!value.rule&&!!value.location&&validSubject(value.subject)&&(value.identityVersion===undefined||[0,1].includes(value.identityVersion))&&(value.subject==null||value.identityVersion===1);
 const confirmedMutation=(value,request)=>{
  if(value?.ok!==true)return false;
  if(request.op==='securityStart')return record(value.run)&&string(value.run.id,100)&&!!value.run.id&&['running','completed','partial','failed','cancelled','interrupted'].includes(value.run.state);
  if(request.op==='securityScopeSave')return validProfile(value.profile)&&value.profile!==null&&value.profile.revision===request.revision+1&&value.profile.repoRoot===scopePath(request.repoRoot)&&(value.profile.url??'')===(request.url?new URL(request.url).origin:'')&&Date.parse(value.profile.expiresAt)===Date.parse(request.expiresAt)&&JSON.stringify(value.profile.tools)===JSON.stringify(request.tools)&&(value.profile.authProfile??'')===(request.authProfile??'')&&['jointKali','jointRea','jointPentagi'].every(k=>(value.profile[k]??false)===(request[k]??false));
  return request.op==='securityReview'&&validFinding(value.finding)&&value.finding.id===request.id&&value.finding.revision===request.revision+1&&value.finding.status===request.status;
 };
 const definiteRejection=(value,request)=>{
  const d=value.diagnostic;
  return d===undefined||record(d)&&Object.keys(d).sort().join(',')==='code,elapsedMs,operation,requestId,stage'&&string(d.requestId,36)&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(d.requestId)&&d.operation===request.op&&d.stage==='dispatch'&&d.code==='RPC_REJECTED'&&nonnegative(d.elapsedMs)&&d.elapsedMs<=86400000;
 };
 const freshPages=owner=>({owner,runs:{cursor:null,limit:10,history:[],tool:'',state:''},findings:{cursor:null,limit:50,history:[],tool:'',status:'',severity:'',search:''}});
 const requestPages=value=>Object.fromEntries(['runs','findings'].map(key=>{const {history,...query}=value[key];return[key,query]}));
 const validPage=(page,query,rows,collection)=>{
  if(!record(page)||!positive(page.limit)||page.limit!==(query.limit??(collection==='runs'?10:50))||page.cursor!==(query.cursor??null)||!nonnegative(page.total)||page.total<rows.length||rows.length>page.limit||typeof page.hasMore!=='boolean'||!record(page.filters))return false;
  const keys=collection==='runs'?['tool','state']:['tool','status','severity','search'];
  if(Object.keys(page.filters).sort().join(',')!==keys.slice().sort().join(',')||keys.some(key=>page.filters[key]!==((query[key]??'').trim())))return false;
  if(page.cursor===null&&rows.length!==Math.min(page.limit,page.total))return false;
  return page.hasMore?rows.length===page.limit&&page.total>rows.length&&string(page.nextCursor,512)&&/^[A-Za-z0-9_-]+$/.test(page.nextCursor):page.nextCursor===null;
 };
 const valid=(v,eng,query)=>{
  if(!record(v)||v.ok!==true||v.engagement!==eng||!validProfile(v.profile)||!record(v.tools)||!Object.keys(toolNames).every(tool=>validRuntime(v.tools[tool]))||!date(v.observedAt))return false;
  if(Object.hasOwn(v,'authSession')&&(v.profile?.authProfile?!validSession(v.authSession,v.profile.authProfile):v.authSession!==null))return false;
  if(v.pagination!==undefined){
   if(!record(v.pagination)||!nonnegative(v.totalRuns)||!nonnegative(v.totalFindings)||!(v.activeRun===null||validRun(v.activeRun)&&v.activeRun.state==='running')||!Array.isArray(v.comparisonRuns)||v.comparisonRuns.length>30||v.comparisonRuns.some(row=>!validRun(row)||row.state!=='completed'||row.complete!==1)||new Set(v.comparisonRuns.map(row=>row.id)).size!==v.comparisonRuns.length)return false;
   return [['runs',v.totalRuns,validRun],['findings',v.totalFindings,validFinding]].every(([key,total,check])=>Array.isArray(v[key])&&v[key].every(check)&&new Set(v[key].map(row=>row.id)).size===v[key].length&&validPage(v.pagination[key],query[key],v[key],key)&&v.pagination[key].total<=total);
  }
  return [['runs',30,'totalRuns',validRun],['findings',500,'totalFindings',validFinding]].every(([key,limit,total,check])=>Array.isArray(v[key])&&v[key].length<=limit&&v[key].every(check)&&new Set(v[key].map(row=>row.id)).size===v[key].length&&(v[total]===undefined||(nonnegative(v[total])&&v[key].length===Math.min(limit,v[total]))));
 };
 const JointPanel=createJointPanel(React,api,{storage,exclusive});
 return function SecurityTab({engagement,refreshKey}){
  const [data,setData]=React.useState(null),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false),[loading,setLoading]=React.useState(true),[draft,setDraft]=React.useState(null),[notes,setNotes]=React.useState({}),[updateGuide,setUpdateGuide]=React.useState(false),[comparison,setComparison]=React.useState({owner:engagement,base:'',current:'',result:null,error:'',loading:false});
  const [exporting,setExporting]=React.useState(false),[unconfirmed,setUnconfirmed]=React.useState(false),[searchDraft,setSearchDraft]=React.useState(''),[storageError,setStorageError]=React.useState(''),[discardAck,setDiscardAck]=React.useState(false),[authGuide,setAuthGuide]=React.useState(false);
  const guard=React.useRef({alive:true,sequence:0,writing:false,owner:engagement,context:0,read:null,confirmed:false,recover:false,authSelected:false}),dirty=React.useRef(false),writeReceipt=React.useRef(null),journal=React.useRef(null),discardApproval=React.useRef(null),compareGuard=React.useRef(0),exportGuard=React.useRef(null),pageQuery=React.useRef(freshPages(engagement));
  if(guard.current.owner!==engagement){guard.current.read?.abort();guard.current.read=null;guard.current.confirmed=false;guard.current.owner=engagement;guard.current.context++;writeReceipt.current=null;dirty.current=false;journal.current=null}
  const contextAtRender=guard.current.context;
  const restoreReceipt=()=>{const value=readReceipt(engagement);journal.current=value;writeReceipt.current=value.request;setStorageError(value.error);discardApproval.current=null;setDiscardAck(false)};
  const viewGeneration=guard.current.sequence;
  const discardRaw=journal.current?.owner===engagement?journal.current.raw:undefined;
  const load=async({refreshRuntime=false,targetPages=null,resetPages=false,automatic=false}={})=>{
   if(!guard.current.alive||guard.current.owner!==engagement||guard.current.context!==contextAtRender)return;
   if(automatic&&(!visible()||guard.current.read||guard.current.writing))return;
   guard.current.read?.abort();const controller=new AbortController();guard.current.read=controller;guard.current.confirmed=false;
   const source=(targetPages??pageQuery.current).owner===engagement?(targetPages??pageQuery.current):freshPages(engagement);
   const target=resetPages?{...source,runs:{...source.runs,cursor:null,history:[]},findings:{...source.findings,cursor:null,history:[]}}:source,pages=requestPages(target);
   const token=++guard.current.sequence;restoreReceipt();setLoading(true);exportGuard.current=null;setExporting(false);compareGuard.current++;setComparison(old=>old.owner===engagement?{...old,result:null,error:'',loading:false}:{owner:engagement,base:'',current:'',result:null,error:'',loading:false});
   try{const next=await api({op:'securityStatus',engagement,pages,...(refreshRuntime?{refreshRuntime:true}:{})},{signal:controller.signal});if(!guard.current.alive||token!==guard.current.sequence)return;if(!valid(next,engagement,pages))throw Error(next?.ok===false&&typeof next.error==='string'?next.error:'安全审计资料无效，当前结果未确认');pageQuery.current=target;guard.current.confirmed=true;guard.current.recover=false;guard.current.authSelected=!!next.profile?.authProfile;setData(next);setError('');setUnconfirmed(false);setDraft(old=>{if(dirty.current&&old)return old;const p=next.profile;return p?{...p,confirm:false}:{repoRoot:'',url:'',expiresAt:new Date(Date.now()+86400000).toISOString(),tools:['semgrep','trivy'],revision:0,confirm:false}})}
   catch(e){if(guard.current.alive&&token===guard.current.sequence){guard.current.recover=true;setError(e.message||'读取失败');setUnconfirmed(true)}}
   finally{if(guard.current.alive&&token===guard.current.sequence){guard.current.read=null;setLoading(false)}}
  };
  React.useEffect(()=>{guard.current.alive=true;if(pageQuery.current.owner!==engagement)setSearchDraft('');load({resetPages:true});return()=>{guard.current.alive=false;guard.current.sequence++;guard.current.read?.abort();guard.current.read=null;guard.current.confirmed=false}},[engagement,refreshKey]);
  React.useEffect(()=>{
   const target=Object.hasOwn(options,'events')?options.events:globalThis;
   let last=now();
   const current=()=>guard.current.alive&&guard.current.owner===engagement&&guard.current.context===contextAtRender;
   const invalidate=()=>{guard.current.read?.abort();guard.current.read=null;guard.current.sequence++;guard.current.confirmed=false;guard.current.recover=true;exportGuard.current=null;compareGuard.current++;setUnconfirmed(true);setLoading(false);setExporting(false)};
   const sync=()=>{if(!current())return;invalidate();if(visible()&&!guard.current.writing)load()};
   const changed=event=>{if(event.key!==null&&event.key!==receiptKey(engagement))return;try{if(event.storageArea&&event.storageArea!==storage())return}catch{}sync()};
   const visibility=()=>{if(!current())return;last=now();if(visible())sync();else invalidate()};
   const heartbeat=()=>{if(!current())return;const currentTime=now(),gap=currentTime-last;last=currentTime;if(!visible())return;if(gap>60000||gap<0){sync();return}if(guard.current.recover||guard.current.authSelected)load({automatic:true})};
   target?.addEventListener?.('storage',changed);target?.addEventListener?.('focus',sync);target?.addEventListener?.('pageshow',sync);documentState?.addEventListener?.('visibilitychange',visibility);
   const timer=timers.setInterval(heartbeat,30000);timer?.unref?.();
   return()=>{timers.clearInterval(timer);target?.removeEventListener?.('storage',changed);target?.removeEventListener?.('focus',sync);target?.removeEventListener?.('pageshow',sync);documentState?.removeEventListener?.('visibilitychange',visibility)};
  },[engagement,refreshKey]);
  const running=data?.activeRun??data?.runs?.find(row=>row.state==='running');
  React.useEffect(()=>{if(!running)return;const timer=timers.setInterval(()=>load({automatic:true}),2500);timer?.unref?.();return()=>timers.clearInterval(timer)},[running?.id,engagement,refreshKey]);
  const mutate=async(request,{receipt=false}={})=>{
   if(!guard.current.confirmed||viewGeneration!==guard.current.sequence||guard.current.writing||!guard.current.alive||guard.current.context!==contextAtRender||guard.current.owner!==engagement||request?.engagement!==engagement)return;
   const context=guard.current.context,current=()=>guard.current.alive&&context===guard.current.context;
   guard.current.writing=true;setBusy(true);setError('');
   try{
    await exclusive(engagement,async()=>{
    if(!current()||!guard.current.confirmed||viewGeneration!==guard.current.sequence)return;
    if(receipt){try{request=persistReceipt(request);restoreReceipt()}catch(error){setStorageError(error.message);throw error}}
    const result=await api(request);
    if(receipt&&(confirmedMutation(result,request)||result?.ok===false&&definiteRejection(result,request)))releaseReceipt(request);
    if(!current())return;
    if(receipt)restoreReceipt();
    if(result?.ok===false)throw Error(result.error||'操作已拒绝');if(result?.ok!==true||receipt&&!confirmedMutation(result,request))throw Error('操作回执无效，结果未确认');
    if(request.op==='securityScopeSave'&&(!dirty.current||['revision','repoRoot','url','expiresAt','tools','confirm','authProfile','jointKali','jointRea','jointPentagi'].every(key=>JSON.stringify(draft?.[key])===JSON.stringify(request[key])))){dirty.current=false;setDraft(old=>({...old,...result.profile,confirm:false}))}await load({resetPages:true});
    });
   }
   catch(e){if(current())setError((e.message||'操作失败')+(receipt?'；可刷新查询结果。若重试，将复用同一请求号。':''))}
   finally{guard.current.writing=false;if(guard.current.alive)setBusy(false);if(current()&&guard.current.recover&&visible())load({automatic:true})}
  };
  const choices=data?.engagement===engagement?(data.comparisonRuns??data.runs.filter(run=>run.state==='completed'&&run.complete===1)):[],ownedComparison=comparison.owner===engagement?comparison:null;
  const currentId=ownedComparison?.current||choices[0]?.id||'',baseId=ownedComparison?.base||choices[1]?.id||'';
  const selectComparison=(key,value)=>{compareGuard.current++;setComparison({owner:engagement,base:baseId,current:currentId,[key]:value,result:null,error:'',loading:false})};
  const compareSelected=async()=>{
   if(!guard.current.confirmed||viewGeneration!==guard.current.sequence||ownedComparison?.loading||!baseId||!currentId||baseId===currentId||!guard.current.alive)return;
   const request={op:'securityCompare',engagement,baseRunId:baseId,currentRunId:currentId},token=++compareGuard.current;
   setComparison({owner:engagement,base:baseId,current:currentId,result:null,error:'',loading:true});
   try{const value=await api(request);if(!guard.current.alive||token!==compareGuard.current)return;if(!comparisonValid(value,request))throw Error(value?.error||'对比结果未确认');setComparison({owner:engagement,base:baseId,current:currentId,result:value,error:'',loading:false})}
   catch(error){if(guard.current.alive&&token===compareGuard.current)setComparison({owner:engagement,base:baseId,current:currentId,result:null,error:error.message||'对比读取失败',loading:false})}
  };
  const comparisonValue=ownedComparison?.result?.baseRunId===baseId&&ownedComparison?.result?.currentRunId===currentId?ownedComparison.result:null,comparisonGeneration=compareGuard.current;
  const downloadComparison=()=>{if(!guard.current.alive||comparisonGeneration!==compareGuard.current||!comparisonValue?.available)return;const url=URL.createObjectURL(new Blob([comparisonValue.markdown],{type:'text/markdown;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='security-comparison-'+engagement+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  const change=(key,value)=>{if(!guard.current.alive||guard.current.context!==contextAtRender||writeReceipt.current||storageError)return;dirty.current=true;setDraft(old=>({...old,[key]:value}))};
  const discardReceipt=async()=>{
   const allowed=()=>guard.current.alive&&discardAck&&!busy&&!loading&&!unconfirmed&&guard.current.sequence===viewGeneration&&guard.current.context===contextAtRender&&guard.current.owner===engagement&&journal.current?.owner===engagement&&discardApproval.current?.raw===discardRaw&&discardApproval.current?.generation===viewGeneration;
   if(guard.current.writing||!allowed())return;
   guard.current.writing=true;setBusy(true);
   try{await exclusive(engagement,async()=>{if(!allowed())return;const target=storage(),key=receiptKey(engagement);if(discardRaw===undefined||journal.current.raw!==discardRaw||target.getItem(key)!==discardRaw)throw Error();target.removeItem(key);restoreReceipt();await load({resetPages:true})})}
   catch{if(guard.current.alive&&guard.current.context===contextAtRender){restoreReceipt();setError('恢复记录已变化、另一窗口正在处理或多窗口协调不可用；请重新读取后核对。')}}
   finally{guard.current.writing=false;if(guard.current.alive)setBusy(false)}
  };
  const save=()=>mutate({op:'securityScopeSave',engagement,requestId:id(),...draft},{receipt:true});
  const start=(tool,finding)=>{if(tool==='zap'&&data?.profile?.authProfile&&!['ready','expiring'].includes(data?.authSession?.state))return;return mutate({op:'securityStart',engagement,requestId:id(),profileRevision:data.profile.revision,tool,...(finding?{retestFindingId:finding.id}:{})},{receipt:true})};
  const review=(finding,status)=>mutate({op:'securityReview',engagement,requestId:id(),id:finding.id,revision:finding.revision,status,note:notes[finding.id]||''},{receipt:true});
  const download=async()=>{
   if(!guard.current.confirmed||!guard.current.alive||viewGeneration!==guard.current.sequence||exportGuard.current||loading||error||data?.engagement!==engagement)return;
   const token={generation:viewGeneration};exportGuard.current=token;setExporting(true);
   const current=()=>guard.current.alive&&viewGeneration===guard.current.sequence&&exportGuard.current===token;
   try{
    const report=await api({op:'securityReport',engagement});if(!current())return;
    if(report?.ok!==true||report.engagement!==engagement||typeof report.markdown!=='string')throw Error('报告未确认，请刷新后重试');
    const url=URL.createObjectURL(new Blob([report.markdown],{type:'text/markdown;charset=utf-8'}));
    try{const a=document.createElement('a');a.href=url;a.download='security-audit-'+engagement+'.md';a.click()}finally{setTimeout(()=>URL.revokeObjectURL(url),1000)}
   }catch(e){if(current())setError(e.message||'报告下载失败')}
   finally{if(current()){exportGuard.current=null;setExporting(false)}}
  };
  const button=(label,onClick,disabled=false)=>h('button',{type:'button',className:'rt-btn',onClick,disabled:busy||disabled},label);
  const field=(label,key,type='text')=>h('label',{className:'rts-field'},h('span',null,label),h('input',{className:'rt-input',type,value:draft?.[key]||'',disabled:busy||!!writeReceipt.current||!!storageError,onChange:e=>change(key,e.target.value)}));
  const actionable=data&&data.engagement===engagement&&!error&&!loading&&!busy&&!running&&!writeReceipt.current&&!storageError&&coordinated();
  const pageDisabled=loading||busy||!!error||data?.engagement!==engagement;
  const movePage=(collection,forward)=>{
   if(pageDisabled)return;const current=pageQuery.current[collection],meta=data?.pagination?.[collection];if(!meta||forward&&!meta.hasMore||!forward&&!current.history.length)return;
   const next=forward?{...current,cursor:meta.nextCursor,history:[...current.history,current.cursor]}:{...current,cursor:current.history.at(-1),history:current.history.slice(0,-1)};
   return load({targetPages:{...pageQuery.current,[collection]:next}});
  };
  const filterPage=(collection,key,value)=>{if(pageDisabled)return;return load({targetPages:{...pageQuery.current,[collection]:{...pageQuery.current[collection],[key]:value,cursor:null,history:[]}}})};
  const pageTitle=collection=>{const meta=data?.pagination?.[collection],current=pageQuery.current[collection];return meta?'第'+(current.history.length+1)+'页 · 本页 '+data[collection].length+' · 匹配 '+meta.total+' / 全部 '+data[collection==='runs'?'totalRuns':'totalFindings']:null};
  const pendingRequest=writeReceipt.current;
  const pageControls=collection=>{
   const meta=data?.pagination?.[collection];if(!meta)return null;const name=collection==='runs'?'任务':'发现',current=pageQuery.current[collection];
   const select=(key,title,values)=>h('label',{className:'rts-field'},title,h('select',{'aria-label':title,className:'rt-input',value:current[key],disabled:pageDisabled,onChange:e=>filterPage(collection,key,e.target.value)},h('option',{value:''},'全部'),...values.map(value=>h('option',{key:value,value},key==='tool'?label(toolNames,value):label(statusNames,value,value)))));
   return h('div',null,h('div',{className:'rts-grid'},select('tool',name+'工具',Object.keys(toolNames)),...(collection==='runs'?[select('state','任务状态',['running','completed','partial','failed','cancelled','interrupted'])]:[select('status','发现状态',['unverified','confirmed','false-positive','fixed','retest-passed','reopened']),select('severity','发现严重性',['critical','high','medium','low','info','unknown']),h('label',{className:'rts-field'},'标题、规则或位置',h('input',{'aria-label':'发现搜索',className:'rt-input',value:searchDraft,maxLength:160,disabled:pageDisabled,onChange:e=>setSearchDraft(e.target.value),onKeyDown:e=>{if(e.key==='Enter')filterPage('findings','search',searchDraft.trim())}}))])),h('nav',{'aria-label':name+'分页',className:'rts-actions'},button(name+'上一页',()=>movePage(collection,false),pageDisabled||!current.history.length),button(name+'下一页',()=>movePage(collection,true),pageDisabled||!meta.hasMore),collection==='findings'&&button('搜索发现',()=>filterPage('findings','search',searchDraft.trim()),pageDisabled)),h('p',{className:'rts-meta'},'筛选仅影响列表；报告仍按项目全部记录生成。'));
  };
  const expired=!data?.profile||Date.parse(data.profile.expiresAt)<=Date.now();
  const comparisonFields=[['基线任务','base',baseId],['本次任务','current',currentId]].map(([label,key,value])=>{
   const options=choices.map(run=>h('option',{key:run.id,value:run.id},run.tool.toUpperCase()+' · '+run.started_at+' · '+run.id.slice(0,8)+(run.details?.comparisonSnapshot?.available?'':' · 无完整快照')));
   return h('label',{key,className:'rts-field'},label,h('select',{className:'rt-input',value,disabled:loading||busy,onChange:e=>selectComparison(key,e.target.value)},h('option',{value:''},'选择任务'),...options));
  });
  const comparisonGroups=comparisonValue?.available?Object.entries(comparisonLabels).map(([key,label])=>{
   const rows=comparisonValue.items[key].map((item,index)=>h('li',{key:index},item.rule+' · '+item.location+(item.subject?' · '+subjectText(item.subject):'')+' · '+item.title));
   return h('details',{key},h('summary',null,label+' · '+comparisonValue.summary[key]),h('ul',null,...rows));
  }):[];
  return h('div',{className:'rt-pane rt-security'},
   h('style',null,'.rt-security{display:flex;flex-direction:column;gap:14px}.rts-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.rts-head h3{margin:0}.rts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px}.rts-field{display:flex;flex-direction:column;gap:5px;font-size:13px}.rt-security .rt-card{margin:0;padding:16px}.rt-security .rt-input{box-sizing:border-box;width:100%}.rts-tools{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.rts-meta{font-size:12px;opacity:.8;overflow-wrap:anywhere}.rts-findings{display:flex;flex-direction:column;gap:10px}.rts-findings h4{margin:0 0 6px}.rts-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.rts-state{display:inline-block;border:1px solid currentColor;border-radius:12px;padding:2px 9px;font-size:12px}.rts-alert{border-left:3px solid #b7791f;padding:8px 12px;background:rgba(183,121,31,.07)}.rt-security button:disabled{opacity:.5;cursor:default}.rts-run{padding:8px 0;border-bottom:1px solid var(--dsw-alias-border-primary,#ddd)}'),
   h('div',{className:'rts-head'},h('div',null,h('h3',null,'安全审计'),h('p',{className:'rts-meta'},'确认项目范围 → 运行检查 → 验证发现 → 记录修复 → 复测')),h('div',{className:'rts-actions'},button(loading?'读取中…':'刷新',()=>load({resetPages:true}),loading),button('重新核对运行资源',()=>load({refreshRuntime:true,resetPages:true}),loading),button('漏洞库更新',()=>setUpdateGuide(value=>!value)),button(exporting?'正在导出…':'导出报告',download,!data||data.engagement!==engagement||!!error||loading||exporting))),
   h('div',{className:'rts-alert'},'扫描命中先进入“待验证”，复测通过仅代表所选规则与本次覆盖。新增范围限制覆盖本页和对应审计工具；通用 Shell、浏览器和原版能力沿用原权限。'),
   updateGuide&&h('section',{className:'rt-card','aria-label':'漏洞库更新说明'},h('h4',null,'在 Mac 上更新漏洞库'),h('p',null,'打开 Harness.command，选择选项 9。先检查版本；结束任务后选择更新并确认。下载及校验完成后会短暂重启 Harness，保留原库备份，不更换扫描器镜像。'),h('p',null,'若更新中断，请先选择检查；如提示维护未完成，再选择恢复。请勿重复提交更新。'),button('收起说明',()=>setUpdateGuide(false))),
   h('p',{className:'rts-meta'},'任务由 VM 独立后台持有，关闭网页或结束会话后继续运行。回来后刷新查看原任务；VM 关机或后台服务停止仍会中断，不会自动重跑。'),
   error&&h('div',{className:'rt-err',role:'alert'},error),
   !coordinated()&&h('p',{className:'rts-alert'},'本浏览器的多窗口协调不可用，审计写入和清除恢复记录已暂停；请使用支持 Web Locks 的同源浏览器页面。'),
   data&&unconfirmed&&h('p',{className:'rts-alert'},'当前资料未确认，以下为上次成功读取结果；写入和导出已暂停，请刷新核对。'),
   running&&!data.runs.some(row=>row.id===running.id)&&h('div',{className:'rts-alert'},'当前运行任务：'+running.id,button('取消当前任务',()=>mutate({op:'securityCancel',engagement,id:running.id}),loading||unconfirmed)),
   (pendingRequest||storageError)&&h('section',{className:'rts-alert','aria-label':'恢复未确认操作'},h('h4',null,'恢复未确认操作'),h('p',null,storageError||'发现本浏览器保存的未确认操作；不会自动重发。请先核对已保存任务与以下原始请求内容。'),pendingRequest&&h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},JSON.stringify(pendingRequest,null,2)),pendingRequest&&button('重试同一请求',()=>mutate(pendingRequest,{receipt:true}),loading||unconfirmed||!!storageError||!coordinated()),button('重新读取恢复记录',()=>load({resetPages:true}),loading),journal.current?.raw!==undefined&&journal.current?.raw!==null&&h('div',null,h('label',null,h('input',{type:'checkbox','aria-label':'确认清除恢复提示',checked:discardAck,disabled:busy||loading||unconfirmed,onChange:e=>{if(guard.current.context!==contextAtRender||guard.current.sequence!==viewGeneration||journal.current?.raw!==discardRaw)return;discardApproval.current=e.target.checked?{raw:discardRaw,generation:viewGeneration}:null;setDiscardAck(e.target.checked)}}),' 我已核对记录；清除此提示不会取消、撤销或证明原操作未执行。'),button('仅清除恢复提示',discardReceipt,!discardAck||loading||unconfirmed||!coordinated()))),
   !data&&!error&&h('p',null,'正在读取项目配置…'),
   data&&draft&&h('section',{className:'rt-card','aria-label':'项目审计范围'},h('h4',null,'项目审计范围'),h('p',{className:'rts-meta'},'仅扫描 /home/purge/workspace 下的所选目录；ZAP 第一期仅接入 VM 内 127.0.0.1 的明确端口。'),
    h('div',{className:'rts-grid'},field('仓库绝对路径','repoRoot'),field('VM 本地网址（ZAP 必填）','url','url'),field('授权到期时间（ISO 8601）','expiresAt'),field('ZAP 会话配置名（可选）','authProfile')),
    h('p',{className:'rts-meta'},'仅填写 VM 私有会话配置名；请在 Shell 工作台导入私有配置，勿把 Cookie 或令牌填入网页或聊天。会话需自行续期；认证仅核对扫描前后状态，不保证全程持续登录。'),
    h('div',{className:'rts-tools'},...Object.keys(toolNames).map(tool=>h('label',{key:tool},h('input',{type:'checkbox',checked:draft.tools.includes(tool),disabled:busy,onChange:e=>change('tools',e.target.checked?[...draft.tools,tool]:draft.tools.filter(v=>v!==tool))}),' '+tool.toUpperCase()))),
    ...['jointRea','jointPentagi'].map(key=>h('label',{key},h('input',{type:'checkbox',checked:!!draft[key],disabled:busy,onChange:e=>change(key,e.target.checked)}),key==='jointRea'?' 允许REA＋reverse-skill分析本项目脱敏JavaScript副本（固定静态图，不执行源码）':' 允许PentAGI向现有DeepSeek服务发送脱敏副本进行隔离静态审查（至多16次请求，每次2048输出tokens，无货币金额硬上限）')),
    h('label',null,h('input',{type:'checkbox',checked:!!draft.jointKali,disabled:busy,onChange:e=>change('jointKali',e.target.checked)}),' 允许联合审查向专用Kali交接本项目脱敏Python副本并执行固定离线Bandit检查'),
    h('label',null,h('input',{type:'checkbox',checked:!!draft.confirm,disabled:busy,onChange:e=>change('confirm',e.target.checked)}),' 我确认上述目录和本地网址可进行所选检查'),
    h('div',{className:'rts-actions'},button('保存范围',save,!actionable||!draft.confirm||!draft.repoRoot||!draft.tools.length),draft.revision!==(data.profile?.revision||0)&&button('采用最新范围（丢弃本地草稿）',()=>{dirty.current=false;setDraft({...data.profile,confirm:false})},!!running||!!writeReceipt.current||!!storageError),h('span',{className:'rts-meta'},'当前版本 '+(data.profile?.revision||0)+(expired?' · 未配置或已过期':'')))),
   data?.profile?.authProfile&&h('section',{className:'rt-card','aria-label':'私有会话配置状态'},h('h4',null,({ready:'会话配置有效',expiring:'会话配置即将到期',expired:'会话配置已过期',unavailable:'会话配置不可用'})[data.authSession?.state]||'会话配置状态未提供'),h('p',null,'当前已保存会话：'+data.profile.authProfile),data.authSession?.expiresAt&&h('p',null,'配置到期：'+data.authSession.expiresAt),data.authSession?.checkedAt&&h('p',{className:'rts-meta'},'配置核对：'+data.authSession.checkedAt),h('p',{className:'rts-meta'},'仅核对私有文件格式与有效期，未探测当前登录；开始扫描时仍会验证登录标记。网页不接收 Cookie 或令牌。'),button('重新导入说明',()=>setAuthGuide(value=>!value)),authGuide&&h('div',null,h('p',null,'原配置保留。先在 VM 私有文件中准备新的 value 与 expiresAt，再用新名称导入；在本页填写新名称并确认保存后才切换。'),data.authSession?.revision&&h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},'python3 /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/security-local-lab.py renew-session '+data.profile.authProfile+' new-session --origin '+data.profile.url+' --expected-revision '+data.authSession.revision+' --confirm < /home/purge/downloads/private-renewal.json'),h('p',null,'原配置不可读取时，使用 import-session 导入完整的新配置。真实登录、MFA 与续期需自行完成，勿把私有值粘贴到网页或聊天。'))),
   data?.profile&&h(JointPanel,{key:engagement,engagement,profile:data.profile}),
   data?.review&&h('section',{className:'rt-card','aria-label':'审查预检与覆盖清单'},h('h4',null,'审查预检与覆盖清单'),validReview(data.review,data)?h('div',null,h('p',{className:'rts-meta'},'范围版本 '+data.review.scopeRevision+' · 只读清单 · '+(unconfirmed||loading?'当前资料未确认':'最近成功读取')),data.review.blockers.length>0&&h('p',{className:'rts-alert'},data.review.blockers.join('；')),h('p',null,'当前可提交的受管工具：'+(data.review.canStartTools.join(' / ')||'无，请核对范围和运行资源')),h('div',{className:'rts-grid'},...data.review.checks.map(c=>h('div',{key:c.id,className:'rts-run'},h('strong',null,c.label),h('p',null,reviewStates[c.state]),c.runId&&h('small',{className:'rts-meta'},'依据任务：'+c.runId)))),h('p',{className:'rts-meta'},data.review.notice),h('p',{className:'rts-meta'},'新聊天可选择“安全审查 · 受限工具”预设；保留现有原版模式。Kali合成验收可在聊天调用 kali_check，或在VM Shell按文档使用固定脚本。')):h('p',{className:'rts-alert'},'审查清单与当前项目不匹配或结构无效，资料未确认。')),
   data&&h('div',{className:'rts-grid'},...Object.keys(toolNames).map(tool=>h('section',{key:tool,className:'rt-card'},h('h4',null,toolNames[tool]),h('div',{className:'rts-meta'},data.tools[tool]?.ready?'已就绪 · '+data.tools[tool].version:(data.tools[tool]?.reason||'工具或离线数据库未就绪')),data.tools[tool]?.rules&&h('p',{className:'rts-meta'},'本地规则：'+data.tools[tool].rules.version+' · '+data.tools[tool].rules.count+' 条 · '+data.tools[tool].rules.languages.join(' / ')),data.tools[tool]?.checkedAt&&h('p',{className:'rts-meta'},'资源核对：'+data.tools[tool].checkedAt+(data.tools[tool].cached?' · 30秒内缓存':'')),data.tools[tool]?.database?.updatedAt&&h('p',{className:'rts-meta'},'漏洞库更新：'+data.tools[tool].database.updatedAt+' · '+data.tools[tool].database.ageDays+'天'),data.tools[tool]?.lastUpdate&&h('p',{className:'rts-meta'},'上次维护：'+label(maintenanceNames,data.tools[tool].lastUpdate.state,'未确认')+' · '+data.tools[tool].lastUpdate.checkedAt),data.tools[tool]?.warning&&h('p',{className:'rts-alert'},data.tools[tool].warning),h('p',{className:'rts-meta'},tool==='semgrep'?'本地启发式规则；需人工复核，不代表完整覆盖；不上传源码':tool==='trivy'?'离线数据库；检查依赖、配置和凭据痕迹':'被动检查与短时爬取；会向所选本地应用发送请求'),button('开始检查',()=>start(tool),!actionable||expired||!data.profile?.tools.includes(tool)||!data.tools[tool]?.ready||tool==='zap'&&!!data.profile?.authProfile&&!['ready','expiring'].includes(data.authSession?.state)||dirty.current)))),
   data&&h('section',{className:'rt-card','aria-label':'审计任务'},h('h4',null,'审计任务 · '+(pageTitle('runs')??('最近 '+data.runs.length+(data.totalRuns===undefined?'':' / '+data.totalRuns)))),pageControls('runs'),!data.runs.length&&h('p',null,data.pagination?'当前筛选没有匹配任务':'尚未运行检查'),...data.runs.map(run=>h('div',{key:run.id,className:'rts-run'},h('div',null,run.tool.toUpperCase()+' · '+label(statusNames,run.state)+' · '+run.started_at),h('div',{className:'rts-meta'},run.id+' · '+(run.revision_ref||'工作区扫描')+(run.error_code?' · '+run.error_code:'')),run.details?.supplemental&&h('p',{className:'rts-alert'},'有限文本补查 '+run.details.supplemental.checkedFiles+'/'+run.details.supplemental.candidateFiles+' 个候选文件；跳过 '+run.details.supplemental.skippedFiles+'；提示 '+run.details.supplemental.hints+(run.details.supplemental.truncated?'；窗口已截断':'')+'。仅匹配固定字样，注释或字符串也可能命中；语义解析缺口仍保留，不计完整覆盖。'),run.details?.authentication&&h('p',{className:'rts-meta'},'认证 '+(run.details.authentication.state==='verified'?'前后核对通过':'未确认')+' · '+run.details.authentication.profile+'；仅核对扫描前后，不保证持续登录。'),run.details?.diagnostics&&h('div',{className:'rts-alert'},'扫描诊断 '+run.details.diagnostics.total+' 项'+(run.details.diagnostics.truncated?' · 显示前20项':''),...run.details.diagnostics.items.map((d,index)=>h('p',{key:index},d.code+' · '+d.path+(d.line?':'+d.line:'')))),run.state==='partial'&&!run.details?.diagnostics&&h('p',{className:'rts-meta'},'旧任务未保存具体覆盖诊断；保持覆盖不完整，请重新检查后核对。'),run.state==='running'&&button('取消任务',()=>mutate({op:'securityCancel',engagement,id:run.id}),loading||unconfirmed)))),
   data&&h('section',{className:'rt-card','aria-label':'扫描结果对比'},
    h('h4',null,'扫描结果对比'),h('p',{className:'rts-meta'},'选择最近30次任务中的两个完整任务。新任务保存观察快照，旧任务缺少快照时无法推断；对比不会修改发现状态。'),
    h('div',{className:'rts-grid'},...comparisonFields),
    h('div',{className:'rts-actions'},button(ownedComparison?.loading?'正在对比…':'对比所选任务',compareSelected,!actionable||!!ownedComparison?.loading||!baseId||!currentId||baseId===currentId),comparisonValue?.available&&button('下载对比报告',downloadComparison)),
    ownedComparison?.error&&h('p',{className:'rt-err',role:'alert'},ownedComparison.error),
    comparisonValue&&!comparisonValue.available&&h('p',{className:'rts-alert'},comparisonValue.reason),
    comparisonValue?.available&&h('div',null,
     h('p',{className:'rts-alert'},comparisonValue.notice),
     h('div',{className:'rts-grid'},...Object.entries(comparisonLabels).map(([key,label])=>h('div',{key},label+'：'+comparisonValue.summary[key]))),
     comparisonValue.truncated&&h('p',{className:'rts-alert'},'每类仅展示前100条，统计来自完整已保存快照；对比报告也包含此截断说明。'),
     ...comparisonGroups)),
   data&&h('section',{className:'rt-card','aria-label':'审计发现'},h('h4',null,'发现 · '+(pageTitle('findings')??('显示 '+data.findings.length+(data.totalFindings===undefined?'':' / '+data.totalFindings)))),pageControls('findings'),!data.findings.length&&h('p',null,data.pagination?'当前筛选没有匹配发现；请结合任务覆盖判断。':data.runs.length?'当前没有已收录发现，请结合任务完成状态判断覆盖。':'运行检查后在此验证发现。'),h('div',{className:'rts-findings'},...data.findings.map(f=>h('article',{key:f.id,className:'rt-card'},h('h4',null,f.title),h('span',{className:'rts-state'},label(statusNames,f.status)),h('p',{className:'rts-meta'},f.severity+' · '+f.tool+' / '+f.rule+' · '+f.location),h('p',null,f.evidence),f.subject&&h('p',{className:'rts-meta'},'依赖包：'+subjectText(f.subject)),f.tool==='trivy'&&f.identityVersion!==1&&h('p',{className:'rts-alert'},'旧记录未区分依赖包身份，历史可能已合并；请重新扫描并人工核对。'),f.note&&h('p',{className:'rts-meta'},'上次说明：'+f.note),h('label',{className:'rts-field'},'验证或修复说明（至少 5 字）',h('textarea',{className:'rt-input',value:notes[f.id]||'',disabled:busy,onChange:e=>{const note=e.target.value;setNotes(old=>({...old,[f.id]:note}))}})),h('div',{className:'rts-actions'},...(['unverified','reopened','false-positive','retest-passed','fixed'].includes(f.status)?[button('确认发现',()=>review(f,'confirmed'),!actionable||(notes[f.id]||'').trim().length<5)]:[]),...(['unverified','reopened','confirmed'].includes(f.status)?[button('标记误报',()=>review(f,'false-positive'),!actionable||(notes[f.id]||'').trim().length<5)]:[]),f.status==='confirmed'&&button('记录修复',()=>review(f,'fixed'),!actionable||(notes[f.id]||'').trim().length<5),f.status==='fixed'&&button('复测此发现',()=>start(f.tool,f),!actionable||expired||dirty.current||!data.profile?.tools.includes(f.tool)||!data.tools[f.tool]?.ready)))))),
   data&&h('p',{className:'rts-meta'},'资料读取时间：'+data.observedAt));
 };
}


    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    const React = require('react')
    const h = React.createElement

    /*
     * 演练台自己是一块浮动窗：position:fixed，用 left/top/width/height 放。
     * 不给官方 frame 加 padding，不改官方输入框的宽度。嵌在清洗面板里时走 .rt-embedded。
     */
    const CSS = `
.rt-dock{position:fixed;top:12px;right:12px;z-index:20;display:flex;flex-direction:column;box-sizing:border-box;
  background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#1c1c1c) 52%,transparent);
  backdrop-filter:blur(20px) saturate(1.3);-webkit-backdrop-filter:blur(20px) saturate(1.3);
  border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,#444) 70%,transparent);
  border-radius:12px;
  box-shadow:0 18px 48px color-mix(in srgb,#000 28%,transparent);pointer-events:auto;color:var(--dsw-alias-label-primary);
  font-size:13px;line-height:1.5}
.rt-dock.rt-embedded{position:relative;inset:auto;width:100%;height:100%;max-width:none;border:0;border-radius:0;box-shadow:none;background:transparent!important;backdrop-filter:none;-webkit-backdrop-filter:none}
.rt-grip,.rt-resize-r,.rt-resize-b,.rt-resize-c{position:absolute;z-index:3;touch-action:none}
.rt-grip{left:-3px;top:0;bottom:0;width:8px;cursor:ew-resize;background:transparent}
.rt-resize-r{right:-3px;top:0;bottom:14px;width:8px;cursor:ew-resize}
.rt-resize-b{left:8px;right:14px;bottom:-3px;height:8px;cursor:ns-resize}
.rt-resize-c{right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize}
.rt-head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--dsw-alias-border-l1)}
.rt-title{font-weight:600;font-size:14px;display:flex;align-items:center;gap:6px;white-space:nowrap}
.rt-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-alias-brand-primary)}
.rt-spacer{flex:1}
.rt-btn{border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-2);color:inherit;
  border-radius:6px;padding:3px 9px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap}
.rt-btn:hover{border-color:var(--dsw-alias-border-l2)}
.rt-btn-primary{background:var(--dsw-alias-brand-primary);border-color:var(--dsw-alias-brand-primary);color:#fff}
.rt-btn-primary:hover{opacity:.9}
.rt-btn:disabled{opacity:.5;cursor:default}
.rt-tabs{display:flex;flex-wrap:wrap;gap:2px;padding:6px 12px 0;border-bottom:1px solid var(--dsw-alias-border-l1)}
.rt-tab{padding:8px 10px 7px;border-radius:0;cursor:pointer;font-size:12.5px;color:var(--dsw-alias-label-secondary);
  display:inline-flex;align-items:center;gap:5px;border-bottom:2px solid transparent;margin-bottom:-1px;background:transparent}
.rt-tab:hover{color:var(--dsw-alias-label-primary)}
.rt-tab.on{color:var(--dsw-alias-label-primary);background:transparent;font-weight:600;border-bottom-color:var(--dsw-alias-brand-primary,#6dbf8c)}
/* 未读红点：该页签有新内容（新资产/新漏洞/新得分/新步骤…），点开看过就消失 */
.rt-tab-dot{width:7px;height:7px;border-radius:50%;background:#ef4444;flex:none;
  box-shadow:0 0 0 2px color-mix(in srgb, #ef4444 22%, transparent)}
.rt-binding{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:10px 12px;border-bottom:1px solid var(--dsw-alias-border-l1);font-size:12px;overflow-wrap:anywhere}.rt-binding strong{font-weight:600}.rt-binding>div{min-width:0;flex:1 1 220px}\n.rt-body{flex:1;min-height:0;display:flex;flex-direction:column}
.rt-split{flex:1;min-height:0;display:flex}
.rt-side{width:200px;flex:none;border-right:1px solid var(--dsw-alias-border-l1);overflow:auto;padding:8px}
.rt-main{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.rt-seg{padding:7px 8px;border-radius:6px;cursor:pointer;margin-bottom:4px;border:1px solid transparent}
.rt-seg:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-seg.on{background:var(--dsw-alias-bg-layer-2);border-color:var(--dsw-alias-brand-primary)}
.rt-seg-cidr{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.rt-seg-meta{font-size:11px;color:var(--dsw-alias-label-secondary);margin-top:2px}
.rt-toolbar{display:flex;gap:6px;padding:8px 10px;border-bottom:1px solid var(--dsw-alias-border-l1);flex-wrap:wrap;align-items:center}
.rt-input{background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);color:inherit;
  border-radius:6px;padding:4px 8px;font-size:12px;font-family:inherit;outline:none;min-width:0}
.rt-input:focus{border-color:var(--dsw-alias-brand-primary)}
.rt-input option,.rt-eng-select option{background:var(--dsw-alias-bg-layer-1,#1c1c1c);color:var(--dsw-alias-label-primary,#f2f2f2)}
.rt-eng-select{color:var(--dsw-alias-label-primary,#f2f2f2);background:var(--dsw-alias-bg-layer-2,#2a2a2a)}
.rt-table{flex:1;overflow:auto}
.rt-row{display:grid;grid-template-columns:150px 74px 104px 1.15fr 1fr;gap:8px;padding:6px 10px;
  border-bottom:1px solid var(--dsw-alias-border-l1);align-items:center;cursor:pointer;font-size:12.5px}
.rt-row:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-row.head{cursor:default;color:var(--dsw-alias-label-secondary);font-size:11.5px;font-weight:600;position:sticky;top:0;
  background:var(--dsw-alias-bg-layer-1);z-index:1}
.rt-row.head:hover{background:var(--dsw-alias-bg-layer-1)}
.rt-mono{font-family:ui-monospace,Menlo,monospace}
.rt-tag{display:inline-block;padding:0 5px;border-radius:4px;font-size:11px;margin-right:4px;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-tag-passive{color:#8b5cf6;border-color:#8b5cf655;background:#8b5cf61a}
.rt-tag-active{color:#f59e0b;border-color:#f59e0b55;background:#f59e0b1a}
.rt-tag-live{color:#10b981;border-color:#10b98155;background:#10b9811a}
.rt-tag-warn{color:#ef4444;border-color:#ef444455;background:#ef44441a}
/* 纪律提示条：不满足交付要求（非冰蝎/哥斯拉马、没有 suo5 隧道）时顶在区块最上方 */
.rt-hint{border-radius:6px;padding:7px 9px;margin-bottom:8px;font-size:11.5px;line-height:1.6;
  border:1px dashed #ef444488;background:#ef44440f;color:var(--dsw-alias-label-primary)}
.rt-hint b{color:#ef4444}
.rt-tag-dead{color:var(--dsw-alias-label-secondary)}
.rt-expand{grid-column:1/-1;padding:8px 4px 10px;font-size:12px;color:var(--dsw-alias-label-secondary)}
.rt-kv{display:flex;gap:8px;margin-bottom:3px;align-items:baseline}
.rt-kv b{color:var(--dsw-alias-label-primary);font-weight:600;min-width:64px;flex:none}
/* 图谱视图已移除（见 AssetsTab：资产关系由「域名维度」与 redteam_attack_path 工具承担） */
.rt-pane{flex:1;min-height:0;overflow:auto;padding:12px}
.rt-card{border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1,#444) 75%,transparent);border-radius:8px;padding:10px;margin-bottom:10px;
  background:color-mix(in srgb,var(--dsw-alias-bg-layer-2,#2a2a2a) 48%,transparent);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.rt-card h4{margin:0 0 6px;font-size:13px}
.rt-textarea{width:100%;min-height:260px;background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l1);
  color:inherit;border-radius:6px;padding:8px;font-size:12.5px;font-family:ui-monospace,Menlo,monospace;
  line-height:1.6;resize:vertical;outline:none;box-sizing:border-box}
.rt-textarea:focus{border-color:var(--dsw-alias-brand-primary)}
.rt-list{width:210px;flex:none;border-right:1px solid var(--dsw-alias-border-l1);overflow:auto;padding:8px}
.rt-item{padding:7px 8px;border-radius:6px;cursor:pointer;margin-bottom:4px;border:1px solid transparent}
.rt-item:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-item.on{background:var(--dsw-alias-bg-layer-2);border-color:var(--dsw-alias-brand-primary)}
.rt-item-name{font-weight:600;font-size:12.5px}
.rt-item-desc{font-size:11px;color:var(--dsw-alias-label-secondary);margin-top:2px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rt-empty{padding:24px;text-align:center;color:var(--dsw-alias-label-secondary);font-size:12.5px}
.rt-err{color:var(--dsw-alias-state-error-primary);font-size:12px;padding:6px 10px}
.rt-foot{padding:8px 12px;border-top:1px solid var(--dsw-alias-border-l1);font-size:11px;
  color:var(--dsw-alias-label-secondary);display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.rt-icon-btn{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;border:1px solid var(--dsw-alias-border-l1);
  background:transparent;color:inherit;border-radius:6px;padding:6px 8px;cursor:pointer;font-family:inherit;font-size:12.5px}
.rt-icon-btn:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-icon-btn.on{border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-brand-primary)}
.rt-hbtn{border:1px solid var(--dsw-alias-border-l1);background:transparent;color:inherit;border-radius:6px;
  padding:2px 8px;font-size:12px;cursor:pointer;font-family:inherit;display:flex;align-items:center;gap:5px}
.rt-hbtn:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-hbtn.on{border-color:var(--dsw-alias-brand-primary);color:var(--dsw-alias-brand-primary)}
.rt-test{display:inline-block;padding:0 5px;border-radius:4px;font-size:11px;white-space:nowrap;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary)}
.rt-test-testing{color:#f59e0b;border-color:#f59e0b55;background:#f59e0b1a}
.rt-test-tested{color:#10b981;border-color:#10b98155;background:#10b9811a}
.rt-test-blocked{color:#fff;background:#ef4444;border-color:#ef4444}
.rt-test-abandoned{color:#94a3b8;border-color:#94a3b855;background:#94a3b81a}
.rt-test-no_surface{color:#6366f1;border-color:#6366f155;background:#6366f11a}
.rt-scope-testing{color:#5b21b6;background:#ddd6fe}
.rt-pri{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap}
.rt-pri-high{color:#fff;background:#ef4444}
.rt-pri-medium{color:#fff;background:#f59e0b}
.rt-pri-low{color:#fff;background:#94a3b8}
.rt-score-row{display:grid;grid-template-columns:16px 62px minmax(0,1fr) 116px 66px;gap:8px;padding:7px 10px;
  border-bottom:1px solid var(--dsw-alias-border-l1);align-items:center;font-size:12.5px;cursor:pointer}
.rt-score-row:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-score-row.head{cursor:default;color:var(--dsw-alias-label-secondary);font-size:11.5px;font-weight:600;
  position:sticky;top:0;background:var(--dsw-alias-bg-layer-1);z-index:1}
.rt-score-detail{grid-column:1/-1;padding:8px 4px 10px;font-size:12px;color:var(--dsw-alias-label-secondary)}
/* 得分目标按合并版的 8 个类别分组：类别头 + 组内按分值升序 */
.rt-score-group{display:flex;align-items:center;gap:8px;padding:7px 10px 5px;margin-top:2px;
  font-size:12px;font-weight:600;border-top:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-2)}
.rt-score-group:first-child{border-top:none}
.rt-score-group .rt-sg-sub{font-weight:400;font-size:11px;color:var(--dsw-alias-label-secondary)}
/* ── 会话与入口：每张卡片分「标题行 / 关键事实 / 可用命令 / 备注」四段，避免一行糊在一起 ── */
.rt-sess-facts{display:flex;flex-direction:column;gap:2px;margin-top:5px}
.rt-sess-fact{display:flex;gap:6px;font-size:11.5px;line-height:1.5}
.rt-sess-fact>b{flex:none;min-width:62px;font-weight:600;color:var(--dsw-alias-label-secondary)}
.rt-sess-fact>span{min-width:0;overflow-wrap:anywhere}
.rt-sess-cmd{margin-top:6px}
.rt-sess-cmd>b{display:block;font-size:11px;color:var(--dsw-alias-label-secondary);margin-bottom:3px;font-weight:600}
.rt-sess-fold{margin-top:6px;font-size:11.5px}
.rt-sess-fold>summary{cursor:pointer;color:var(--dsw-alias-label-secondary);user-select:none}
.rt-sess-fold>summary:hover{color:var(--dsw-alias-label-primary)}
.rt-score-row .rt-scope{font-size:10.5px;color:var(--dsw-alias-label-secondary)}
.rt-score-form{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px}
.rt-score-form input,.rt-score-form select{width:100%;box-sizing:border-box}
.rt-vrow{display:grid;grid-template-columns:62px minmax(0,1fr) 132px 108px 74px 52px;gap:8px;padding:6px 10px;
  border-bottom:1px solid var(--dsw-alias-border-l1);align-items:center;font-size:12.5px;cursor:pointer}
.rt-vrow:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-vrow.head{cursor:default;color:var(--dsw-alias-label-secondary);font-size:11.5px;font-weight:600;
  position:sticky;top:0;background:var(--dsw-alias-bg-layer-1);z-index:1}
.rt-vdetail{grid-column:1/-1;padding:8px 4px 10px;font-size:12px;color:var(--dsw-alias-label-secondary)}
.rt-vdetail .rt-kv{margin-bottom:4px}
.rt-actions{display:flex;gap:6px;margin-top:6px}
.rt-section{padding:8px 10px 2px;font-size:11.5px;font-weight:600;color:var(--dsw-alias-label-secondary)}
.rt-link{color:var(--dsw-alias-brand-primary);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-link:hover{text-decoration:underline}
.rt-full{position:fixed;inset:0;z-index:60;display:flex;flex-direction:column;
  background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-primary);font-size:13px;line-height:1.5;
  border-top:3px solid var(--dsw-alias-brand-primary)}
.rt-full .rt-head{padding:12px 18px}
.rt-full .rt-tabs{padding:10px 18px 0;gap:6px;flex-wrap:wrap}
.rt-full .rt-side{width:260px}
.rt-full .rt-list{width:280px}
.rt-full .rt-row{grid-template-columns:190px 90px 130px 1.4fr 1.2fr}
.rt-full .rt-vrow{grid-template-columns:80px minmax(0,1.6fr) 200px 150px 90px 64px}
.rt-full .rt-pane{padding:18px}
.rt-full .rt-textarea{min-height:60vh}
.rt-full .rt-foot{padding:10px 18px;font-size:12px}
.rt-full .rt-body{max-width:1400px;width:100%;margin:0 auto;flex:1;min-height:0;display:flex;flex-direction:column}
.rt-chain{flex:1;overflow:auto;padding:10px 12px}
.rt-step{display:flex;gap:10px;padding:8px 6px;border-left:2px solid var(--dsw-alias-border-l1);margin-left:6px}
.rt-step:last-child{border-left-color:transparent}
.rt-step-dot{width:22px;height:22px;flex:none;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;color:#fff;background:#64748b;margin-left:-13px}
.rt-step-body{min-width:0}
.rt-step-title{font-weight:600;font-size:13px}
.rt-step-meta{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:2px;word-break:break-word}
.rt-stage-recon{background:#6366f1}
.rt-stage-vuln{background:#f59e0b}
.rt-stage-exploit{background:#ef4444}
.rt-stage-access{background:#10b981}
.rt-stage-pivot{background:#8b5cf6}
.rt-stage-data{background:#0ea5e9}
.rt-stage-other{background:#64748b}
.rt-step-head{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.rt-step-time{font-size:11px;color:var(--dsw-alias-label-secondary);margin-left:auto;white-space:nowrap}
.rt-step-detail{font-size:12px;margin-top:5px;white-space:pre-wrap;word-break:break-word;
  border-left:2px solid var(--dsw-alias-border-l1);padding:2px 0 2px 9px;line-height:1.6}
.rt-chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:1px 7px;border-radius:5px;
  border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-2);margin:4px 5px 0 0;max-width:100%}
.rt-chip>i{font-style:normal;color:var(--dsw-alias-label-secondary);font-size:10.5px}
.rt-chip>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:420px}
.rt-stage-tag{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;color:#fff;font-weight:600}
.rt-st-recon{background:#6366f1}.rt-st-vuln{background:#f59e0b}.rt-st-exploit{background:#ef4444}
.rt-st-access{background:#10b981}.rt-st-pivot{background:#8b5cf6}.rt-st-data{background:#0ea5e9}.rt-st-other{background:#64748b}
.rt-sev{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid transparent}
.rt-sev-critical{color:#fff;background:#b91c1c}.rt-sev-high{color:#fff;background:#ef4444}
.rt-sev-medium{color:#7c2d12;background:#fdba74}.rt-sev-low{color:#1e3a8a;background:#bfdbfe}
.rt-sev-info{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-2);border-color:var(--dsw-alias-border-l1)}
.rt-dot-on{display:inline-block;width:7px;height:7px;border-radius:50%;background:#10b981;box-shadow:0 0 0 3px #10b98133}
.rt-dot-off{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ef4444;box-shadow:0 0 0 3px #ef444433}
.rt-dot-unk{display:inline-block;width:7px;height:7px;border-radius:50%;background:#94a3b8;box-shadow:0 0 0 3px #94a3b833}
.rt-sess-grid{display:grid;grid-template-columns:1fr;gap:8px;padding:10px 12px}
.rt-sess{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:9px 10px;background:var(--dsw-alias-bg-layer-2)}
.rt-sess-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.rt-sess-title{font-weight:600;font-size:12.5px;font-family:ui-monospace,Menlo,monospace;word-break:break-all}
.rt-sess-sub{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:3px;word-break:break-word}
.rt-code{font-family:ui-monospace,Menlo,monospace;font-size:11px;background:var(--dsw-alias-bg-base);
  border:1px solid var(--dsw-alias-border-l1);border-radius:4px;padding:1px 5px;cursor:pointer;word-break:break-all}
.rt-code:hover{border-color:var(--dsw-alias-brand-primary)}
.rt-evi{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;overflow:hidden;margin-top:8px}
.rt-evi-head{display:flex;align-items:center;gap:8px;padding:5px 9px;background:var(--dsw-alias-bg-layer-2);
  font-size:11.5px;font-weight:600;border-bottom:1px solid var(--dsw-alias-border-l1)}
.rt-evi-body{margin:0;padding:9px 11px;font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.6;
  white-space:pre-wrap;word-break:break-word;max-height:340px;overflow:auto;background:var(--dsw-alias-bg-base)}
.rt-evi-body.req{max-height:220px}
.rt-hl-req{color:#10b981;font-weight:600}
.rt-hl-res{color:#0ea5e9;font-weight:600}
.rt-gain{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:12px;
  color:#065f46;background:#a7f3d0;border:1px solid #10b98155}
.rt-total{font-size:20px;font-weight:700;font-family:ui-monospace,Menlo,monospace}
.rt-sidehead{padding:7px 8px 2px;font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);
  display:flex;align-items:center;gap:5px}
.rt-sidehead-btn{cursor:pointer;outline:none;padding:6px 6px 5px;border-radius:5px;user-select:none}
.rt-sidehead-btn:hover{color:var(--dsw-alias-label-primary);background:var(--dsw-alias-bg-layer-1)}
.rt-sidehead-btn:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-scope{display:inline-block;padding:0 4px;border-radius:3px;font-size:10px;font-weight:700;line-height:15px;flex:none}
.rt-scope-internal{color:#0e7490;background:#a5f3fc}
.rt-scope-external{color:#9a3412;background:#fed7aa}
.rt-hits{display:flex;flex-direction:column;gap:6px;margin-top:7px}
.rt-hit{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #10b981;border-radius:6px;
  padding:7px 9px;background:var(--dsw-alias-bg-layer-2)}
.rt-hit-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.rt-hit-idx{width:16px;height:16px;border-radius:50%;background:#10b981;color:#fff;font-size:10.5px;font-weight:700;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.rt-hit-target{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:12px;word-break:break-all}
.rt-hit-time{margin-left:auto;font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-hit-evi{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.65;white-space:pre-wrap;word-break:break-word;
  background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l1);border-radius:5px;padding:6px 8px;margin-top:5px}
.rt-hit-note{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:4px}
.rt-cred{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #f59e0b;border-radius:6px;
  padding:8px 10px;background:var(--dsw-alias-bg-layer-2);margin-bottom:7px}
.rt-cred-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.rt-cred-host{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:12.5px;word-break:break-all}
.rt-secret{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;line-height:1.6;background:#fef3c7;color:#78350f;
  border:1px solid #f59e0b66;border-radius:5px;padding:6px 9px;margin-top:6px;white-space:pre-wrap;word-break:break-all;
  user-select:all;cursor:text}
.rt-secret-none{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--dsw-alias-state-error-primary);
  border:1px dashed var(--dsw-alias-state-error-primary);border-radius:5px;padding:5px 9px;margin-top:6px}
.rt-cred-meta{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:5px;word-break:break-word}
.rt-stage-score{background:#10b981}
.rt-counted{font-family:ui-monospace,Menlo,monospace;font-size:12px;font-weight:700;color:#065f46;background:#a7f3d0;border:1px solid #10b98155;border-radius:9px;padding:0 7px}
.rt-scorepts{font-size:11.5px;font-weight:700;color:#065f46;background:#a7f3d0;border:1px solid #10b98155;
  border-radius:10px;padding:0 7px;white-space:nowrap}
.rt-livebar{display:flex;align-items:center;gap:7px;padding:7px 12px;border-bottom:1px solid var(--dsw-alias-border-l1);
  background:var(--dsw-alias-bg-layer-2);flex-wrap:wrap}
.rt-live-dot{width:8px;height:8px;border-radius:50%;background:#10b981;flex:none;animation:rt-pulse 1.6s ease-in-out infinite}
.rt-live-dot.idle{background:#94a3b8;animation:none}
@keyframes rt-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 #10b98166}50%{opacity:.5;box-shadow:0 0 0 5px #10b98100}}
.rt-live-body{padding:8px 12px 2px;max-height:44vh;overflow:auto}
.rt-atest{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #10b981;border-radius:6px;
  padding:7px 10px;background:var(--dsw-alias-bg-layer-2);margin-bottom:6px}
.rt-atest.past{border-left-color:#94a3b8;opacity:.85}
.rt-atest-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.rt-atest-ip{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:12.5px;word-break:break-all}
.rt-atest-meta{font-size:11.5px;color:var(--dsw-alias-label-secondary);margin-top:3px;word-break:break-word}
.rt-atest-notes{font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.6;white-space:pre-wrap;
  word-break:break-word;background:var(--dsw-alias-bg-base);border-radius:4px;padding:5px 7px;margin-top:4px;max-height:76px;overflow:auto}
.rt-concl{display:flex;align-items:center;gap:4px;padding:6px 12px;border-bottom:1px solid var(--dsw-alias-border-l1);
  background:var(--dsw-alias-bg-layer-2);flex-wrap:wrap}
.rt-concl-i{display:inline-flex;align-items:baseline;gap:4px;padding:2px 8px;border-radius:6px;cursor:pointer;
  border:1px solid transparent}
.rt-concl-i:hover{border-color:var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1)}
.rt-concl-i.on{border-color:var(--dsw-alias-brand-primary);background:var(--dsw-alias-bg-layer-1)}
.rt-concl-i b{font-family:ui-monospace,Menlo,monospace;font-size:14px;font-weight:700}
.rt-concl-i>span{color:var(--dsw-alias-label-secondary);font-size:11.5px}
.rt-more{color:var(--dsw-alias-brand-primary);font-size:11.5px;cursor:pointer;user-select:none;margin-top:4px;display:inline-block}
.rt-more:hover{text-decoration:underline}
.rt-subtabs{display:flex;gap:4px;padding:6px 10px 0;border-bottom:1px solid var(--dsw-alias-border-l1);align-items:center}
.rt-subtab{padding:4px 10px;border-radius:6px 6px 0 0;cursor:pointer;font-size:12px;color:var(--dsw-alias-label-secondary)}
.rt-subtab.on{color:var(--dsw-alias-label-primary);background:var(--dsw-alias-bg-layer-2);font-weight:600}
.rt-sevbar{width:3px;border-radius:2px;align-self:stretch;flex:none;margin-right:2px}
/* ── 折叠层次体系 ─────────────────────────────────────────────────────────────
   L1 折叠头 .rt-sec   ：通栏、无圆角无边框、左色条、深底 —— 永远是"扁"的
   L2 内容卡 .rt-atest/.rt-hit/.rt-cred/.rt-evi：内缩、有边框、圆角 —— 立起来
   L3 详情/长文本 .rt-clip-body / .rt-evi-body ：无边框、最浅、等宽
   L4 子项容器 .rt-sec-body：左缩进 + 竖引导线，表明"属于上面那个头"
   ──────────────────────────────────────────────────────────────────────────── */
.rt-sec-wrap{margin:0}
.rt-sec{display:flex;align-items:center;gap:8px;padding:7px 12px 7px 9px;cursor:pointer;
  background:var(--dsw-alias-bg-layer-2);border-left:3px solid var(--dsw-alias-border-l2);
  border-top:1px solid var(--dsw-alias-border-l1);user-select:none;outline:none}
.rt-sec:hover{background:var(--dsw-alias-bg-layer-1)}
.rt-sec:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-sec.flat{cursor:default}
.rt-sec.flat:hover{background:var(--dsw-alias-bg-layer-2)}
.rt-sec-caret{flex:none;width:11px;font-size:10px;color:var(--dsw-alias-label-secondary);text-align:center}
.rt-sec-title{font-weight:600;font-size:13px;white-space:nowrap}
.rt-sec-count{font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-sec-sub{font-size:11.5px;color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-sec-right{margin-left:auto;font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap;flex:none}
.rt-sec.t-stage{border-left-color:#8b5cf6}
.rt-sec.t-target{border-left-color:#0ea5e9}
.rt-sec.t-folder{border-left-color:#64748b}
.rt-sec.t-test{border-left-color:#10b981}
.rt-sec.t-queue{border-left-color:#f59e0b}
.rt-sec.t-past{border-left-color:#94a3b8}
.rt-sec-body{margin-left:12px;border-left:1px solid var(--dsw-alias-border-l1);padding:7px 0 3px 10px}
.rt-sec-body>.rt-atest:last-child,.rt-sec-body>.rt-hit:last-child{margin-bottom:2px}
/* 长文本折叠（L3）：默认预览 2 行并渐隐，展开后限高滚动 */
.rt-clip{margin-top:6px}
.rt-clip-head{display:flex;align-items:center;gap:6px}
.rt-clip-label{font-size:11px;color:var(--dsw-alias-label-secondary);font-weight:600}
.rt-clip-body{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.65;white-space:pre-wrap;
  word-break:break-word;background:var(--dsw-alias-bg-base);border-radius:5px;padding:6px 8px;margin-top:3px}
.rt-clip:not(.open) .rt-clip-body{max-height:46px;overflow:hidden;
  -webkit-mask-image:linear-gradient(180deg,#000 55%,transparent);mask-image:linear-gradient(180deg,#000 55%,transparent)}
.rt-clip.open .rt-clip-body{max-height:340px;overflow:auto}
.rt-flow{padding:10px 12px 16px}
.rt-flow-start,.rt-flow-end{font-size:11.5px;color:var(--dsw-alias-label-secondary);padding:4px 0}
.rt-flow-end{font-weight:600;color:var(--dsw-alias-label-primary)}
.rt-flow-link{display:flex;align-items:center;gap:8px;padding:3px 0 3px 10px}
.rt-flow-arrow{color:var(--dsw-alias-border-l2);font-size:11px;flex:none}
.rt-flow-action{font-size:11.5px;color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-flow-action.inferred{opacity:.7;font-style:italic}
.rt-flow-node{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #10b981;border-radius:8px;
  padding:8px 11px;background:var(--dsw-alias-bg-layer-2);cursor:pointer;outline:none}
.rt-flow-node:hover{border-color:var(--dsw-alias-border-l2)}
.rt-flow-node:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-flow-node.overflow{border-left-color:#94a3b8;opacity:.75}
.rt-flow-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rt-flow-idx{width:18px;height:18px;border-radius:50%;background:#10b981;color:#fff;font-size:11px;font-weight:700;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.rt-flow-node.overflow .rt-flow-idx{background:#94a3b8}
.rt-flow-name{font-weight:600;font-size:13px}
.rt-flow-pts{margin-left:auto;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;font-weight:700;color:#065f46;
  background:#a7f3d0;border:1px solid #10b98155;border-radius:10px;padding:0 8px;white-space:nowrap}
.rt-flow-pts.off{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-1);border-color:var(--dsw-alias-border-l1)}
.rt-flow-times{font-size:11px;color:var(--dsw-alias-label-secondary)}
.rt-flow-target{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;margin-top:4px;word-break:break-all;
  color:var(--dsw-alias-label-secondary)}
.rt-flow-gain{font-size:12px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-flow-detail{margin-top:7px;padding-top:7px;border-top:1px dashed var(--dsw-alias-border-l1)}
.rt-hflow-wrap{flex:1;min-height:0;display:flex;flex-direction:column;overflow:auto}
.rt-hflow{display:flex;align-items:center;gap:0;padding:16px 12px;overflow-x:auto;flex-wrap:nowrap}
.rt-hflow-item{display:flex;align-items:center;flex:none}
.rt-hflow-start,.rt-hflow-end{font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;padding:0 4px}
.rt-hflow-end{font-weight:600;color:var(--dsw-alias-label-primary)}
.rt-hflow-arrow{color:var(--dsw-alias-border-l2);padding:0 5px;font-size:13px;flex:none}
.rt-hflow-node{display:flex;align-items:center;gap:5px;border:1px solid var(--dsw-alias-border-l1);
  border-left:3px solid #10b981;border-radius:7px;padding:5px 8px;background:var(--dsw-alias-bg-layer-2);
  cursor:pointer;white-space:nowrap;outline:none}
.rt-hflow-node:hover{border-color:var(--dsw-alias-border-l2)}
.rt-hflow-node:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-hflow-node.overflow{border-left-color:#94a3b8;opacity:.72}
.rt-hflow-node.open{border-color:var(--dsw-alias-brand-primary)}
.rt-hflow-pts{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;font-weight:700;color:#065f46;background:#a7f3d0;
  border-radius:8px;padding:0 6px}
.rt-hflow-node.overflow .rt-hflow-pts{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-1)}
.rt-hflow-name{font-size:11.5px}
.rt-hflow-n{font-size:10.5px;color:var(--dsw-alias-label-secondary)}
.rt-rep-list{padding:10px 12px 14px}
.rt-rep-tools{display:flex;gap:6px;justify-content:flex-end;margin-bottom:8px}
.rt-rep{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #10b981;border-radius:8px;
  padding:9px 11px;margin-bottom:10px;background:var(--dsw-alias-bg-layer-2)}
.rt-rep-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rt-rep-idx{font-size:15px;color:#10b981;font-weight:700;flex:none}
.rt-rep-name{font-weight:600;font-size:13px}
.rt-rep-meta{font-size:12px;margin-top:4px;color:var(--dsw-alias-label-secondary);word-break:break-word}
.rt-rep-meta b{color:var(--dsw-alias-label-primary);font-weight:600;margin-right:2px}
.rt-rep-missing{font-size:11.5px;color:var(--dsw-alias-state-error-primary);margin-top:6px;
  border:1px dashed var(--dsw-alias-state-error-primary);border-radius:5px;padding:5px 8px}
.rt-rep-req{margin-top:7px;border:1px solid var(--dsw-alias-border-l1);border-radius:6px;overflow:hidden}
.rt-rep-req-head{display:flex;align-items:center;gap:7px;padding:4px 8px;font-size:11.5px;font-weight:600;
  background:var(--dsw-alias-bg-layer-1);border-bottom:1px solid var(--dsw-alias-border-l1)}
.rt-rep-http{margin:0;padding:8px 10px;font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto;background:var(--dsw-alias-bg-base)}
/* ── 报告里的「这一步怎么来的」：动作步骤 / 命令 / 凭据 / 隧道 ───────────── */
.rt-rep-trace{margin-top:8px;border:1px solid var(--dsw-alias-border-l1);border-radius:7px;padding:8px 10px;
  background:var(--dsw-alias-bg-base)}
.rt-rep-trace-head{display:flex;align-items:center;gap:7px;margin-bottom:5px}
.rt-rep-trace-title{font-weight:600;font-size:12.5px}
.rt-rep-trace-how{font-size:12px;color:var(--dsw-alias-label-secondary);margin-bottom:6px}
.rt-rep-step{border-left:2px solid var(--dsw-alias-border-l1);padding:2px 0 6px 9px;margin-bottom:6px}
.rt-rep-step-head{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.rt-rep-step-no{width:17px;height:17px;border-radius:50%;background:var(--dsw-alias-brand-primary);color:#fff;
  font-size:10.5px;display:flex;align-items:center;justify-content:center;flex:none}
.rt-rep-step-title{font-weight:600;font-size:12.5px}
.rt-rep-step-detail{font-size:12px;color:var(--dsw-alias-label-secondary);margin-top:2px}
.rt-rep-step-cmd{font-size:11.5px;margin-top:4px;display:flex;gap:6px;align-items:flex-start;flex-wrap:wrap}
.rt-rep-step-cmd .rt-mono{background:var(--dsw-alias-bg-layer-2);border:1px solid var(--dsw-alias-border-l1);
  border-radius:5px;padding:2px 6px;word-break:break-all}
.rt-rep-step-result{font-size:11.5px;margin-top:3px;word-break:break-word}
.rt-rep-src{margin-top:6px;padding-top:6px;border-top:1px dashed var(--dsw-alias-border-l1)}
.rt-rep-src-title{font-weight:600;font-size:12px;margin-bottom:3px}
/* ── 全链路攻击路径图 ─────────────────────────────────────────────── */
.rt-ap{padding:10px 12px 18px;overflow:auto}
.rt-ap-stage{margin-bottom:2px}
.rt-ap-head{display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--dsw-alias-bg-layer-2);
  border-left:4px solid #64748b;border-top:1px solid var(--dsw-alias-border-l1);border-radius:6px 6px 0 0}
.rt-ap-no{width:20px;height:20px;border-radius:5px;color:#fff;font-size:11px;font-weight:700;flex:none;
  display:inline-flex;align-items:center;justify-content:center}
.rt-ap-name{font-weight:700;font-size:13.5px}
.rt-ap-en{font-size:10px;color:var(--dsw-alias-label-secondary);letter-spacing:.3px}
.rt-ap-phase{font-size:10.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-ap-goal{display:flex;align-items:baseline;gap:8px;padding:6px 10px 6px 9px;font-size:12px;
  border-left:4px solid #64748b;background:var(--dsw-alias-bg-layer-1)}
.rt-ap-goal-tag{font-size:10.5px;font-weight:700;border:1px solid;border-radius:4px;padding:0 5px;white-space:nowrap;flex:none}
.rt-ap-result{padding:7px 10px 3px;border-left:4px solid transparent}
.rt-ap-result-head{display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap}
.rt-ap-pts{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;font-weight:700;color:#065f46;background:#a7f3d0;
  border:1px solid #10b98155;border-radius:10px;padding:0 7px;white-space:nowrap}
.rt-ap-pts.off{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-1);border-color:var(--dsw-alias-border-l1)}
/* 按服务封顶/自建而不计分的命中：分值标灰（+0），避免看着像又加了分 */
.rt-ap-pts.uncounted{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-1);border-color:var(--dsw-alias-border-l1)}
.rt-ap-nth{font-size:10.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-ap-hit{border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #10b981;border-radius:6px;
  padding:6px 9px;margin-bottom:5px;background:var(--dsw-alias-bg-layer-2);cursor:pointer;outline:none}
.rt-ap-hit:hover{border-color:var(--dsw-alias-border-l2)}
.rt-ap-hit:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-ap-hit.overflow{border-left-color:#94a3b8;opacity:.75}
.rt-ap-hit-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.rt-ap-hit-name{font-weight:600;font-size:12.5px}
.rt-ap-hit-target{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--dsw-alias-label-secondary);
  margin-left:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46%}
.rt-ap-act{font-size:11px;color:var(--dsw-alias-label-secondary);margin-top:3px}
.rt-ap-act.inferred{font-style:italic;opacity:.75}
.rt-ap-none{font-size:11.5px;color:var(--dsw-alias-label-secondary);padding:2px 0 4px}
.rt-ap-trans{display:flex;align-items:center;gap:7px;padding:2px 0 2px 14px}
.rt-ap-trans-t{font-size:11px;color:var(--dsw-alias-label-secondary)}
/* 横向路径图 */
.rt-ap-h{display:flex;align-items:stretch;padding:10px 12px 14px;overflow-x:auto;flex:1;min-height:0}
.rt-ap-col{display:flex;align-items:stretch;flex:none}
.rt-ap-col-arrow{align-self:center;color:var(--dsw-alias-border-l2);padding:0 6px;font-size:12px;flex:none}
.rt-hcol{width:228px;display:flex;flex-direction:column;border:1px solid var(--dsw-alias-border-l1);
  border-top:3px solid #64748b;border-radius:7px;background:var(--dsw-alias-bg-layer-1);overflow:hidden}
.rt-hcol-goal{font-size:11px;color:var(--dsw-alias-label-secondary);padding:5px 8px;line-height:1.45;
  border-bottom:1px solid var(--dsw-alias-border-l1);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rt-hcol-body{padding:6px 8px;flex:1;min-height:0;overflow:auto}
.rt-hcol-hit{display:flex;align-items:center;gap:5px;font-size:11px;margin-bottom:3px}
.rt-hcol-hit.off{opacity:.6}
.rt-hcol-pts{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;font-weight:700;color:#065f46;background:#a7f3d0;
  border-radius:7px;padding:0 5px;flex:none}
.rt-hcol-hit.off .rt-hcol-pts{color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-2)}
.rt-hcol-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-hcol-none{font-size:11px;color:var(--dsw-alias-label-secondary)}
.rt-hcol-secs{display:flex;flex-wrap:wrap;gap:3px;margin-top:6px}
.rt-hcol-sec{font-size:10px;color:var(--dsw-alias-label-secondary);border:1px solid var(--dsw-alias-border-l1);
  border-radius:4px;padding:0 4px}
.rt-hcol-attck{font-family:ui-monospace,Menlo,monospace;font-size:9.5px;color:var(--dsw-alias-label-secondary);
  padding:4px 8px;border-top:1px solid var(--dsw-alias-border-l1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-ap-cum{font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
.rt-ap-sub{font-size:11px;font-weight:600;color:var(--dsw-alias-label-secondary);margin:6px 0 3px}
.rt-ap-assets,.rt-ap-tunnels{display:flex;flex-direction:column;gap:3px}
.rt-ap-asset{display:flex;align-items:center;gap:6px;font-size:11.5px;padding:3px 6px;border-radius:5px;
  background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1)}
.rt-ap-tunnel{display:flex;align-items:center;gap:6px;font-size:11.5px;padding:4px 7px;border-radius:5px;
  background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-left:3px solid #f59e0b}
.rt-hcol-sub{font-size:10.5px;color:var(--dsw-alias-label-secondary);margin-bottom:2px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:flex;gap:5px;align-items:center}
.rt-hcol-sub.off{opacity:.6}
.rt-hit-row{display:flex;flex-wrap:wrap;align-items:center;gap:2px 7px;font-size:11.5px;padding:4px 7px;border-radius:5px;
  background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);margin-bottom:3px}
/* 资产与内容都自适应换行：长域名/长口令/长结果一律换行显示，不截断成省略号 */
.rt-hit-asset{font-family:ui-monospace,Menlo,monospace;font-weight:600;flex:0 1 auto;max-width:100%;
  overflow-wrap:anywhere;word-break:break-word}
.rt-hit-txt{flex:1 1 100%;color:var(--dsw-alias-label-primary);line-height:1.55;
  white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
.rt-hit-txt.none{color:var(--dsw-alias-state-error-primary)}
.rt-hit-row .rt-hit-time{flex:none;margin-left:auto}
/* 自己注册/自建的账号：留痕但不计分，整行压暗 */
.rt-hit-row.self-created{opacity:.72;border-left:3px solid #ef444488}
/* 同一资产同一端口的重复账号/库权限：服务已拿满，不计分（只作留痕） */
.rt-hit-row.service-capped{opacity:.72;border-left:3px solid #f59e0b88}
.rt-hit-row.service-capped .rt-hit-idx{background:#f59e0b}
.rt-rep-group{margin-bottom:14px}
.rt-rep-stage{display:flex;align-items:center;gap:8px;padding:7px 10px;margin-bottom:7px;
  background:var(--dsw-alias-bg-layer-2);border-left:4px solid #64748b;border-radius:6px;
  cursor:pointer;outline:none;user-select:none}
.rt-rep-stage:hover{background:var(--dsw-alias-bg-layer-1)}
.rt-rep-stage:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-rep-no{width:20px;height:20px;border-radius:5px;color:#fff;font-size:11px;font-weight:700;flex:none;
  display:inline-flex;align-items:center;justify-content:center}
.rt-rep-stage-name{font-weight:700;font-size:13px}
.rt-rep-stage-n{font-size:11px;color:var(--dsw-alias-label-secondary)}
/* 折叠后仍要能一眼看到"这一阶段拿了多少分"，所以分数留在头上 */
.rt-rep-pts{font-size:11px;font-weight:600;padding:1px 6px;border-radius:5px;border:1px solid transparent;flex:none}
.rt-rep-body{padding-left:6px}
/* ── 知识库（POC/EXP） ──────────────────────────────────────────── */
.rt-kb-filter{display:flex;align-items:center;gap:7px;padding:8px 10px;border-bottom:1px solid var(--dsw-alias-border-l1)}
/* 知识库归类总览：一行标签，点一下按该类筛选 */
.rt-kb-cats{display:flex;flex-wrap:wrap;gap:6px;padding:8px 10px;border-bottom:1px solid var(--dsw-alias-border-l1)}
/* 知识库分组标题（按归类分组时每组一条） */
.rt-kb-cat{display:flex;align-items:center;gap:7px;padding:7px 10px;background:var(--dsw-alias-bg-layer-2);
  border-bottom:1px solid var(--dsw-alias-border-l1);position:sticky;top:0;z-index:1}
.rt-kb-cat-name{font-weight:600;font-size:12.5px}
/* 技能可用性徽章（技能库页签） */
.rt-avail{display:inline-block;padding:0 5px;border-radius:4px;font-size:10.5px;white-space:nowrap;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary)}
.rt-avail-available{color:#10b981;border-color:#10b98155;background:#10b9811a}
.rt-avail-broken{color:#ef4444;border-color:#ef444455;background:#ef44441a}
.rt-avail-unknown{color:#94a3b8;border-color:#94a3b855;background:#94a3b81a}
/* 版本 / 更新弹窗 */
.rt-modal{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center}
.rt-modal-box{width:min(560px,92vw);max-height:80vh;overflow:auto;background:var(--dsw-alias-bg-layer-1);
  border:1px solid var(--dsw-alias-border-l1);border-radius:10px;padding:14px 16px;font-size:12.5px;line-height:1.7;
  box-shadow:0 18px 48px rgba(0,0,0,.35);color:var(--dsw-alias-label-primary)}
.rt-modal-box .rt-kv b{min-width:76px}
.rt-kb-check{display:flex;align-items:center;gap:5px;font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;cursor:pointer}
.rt-kb{border:1px solid var(--dsw-alias-border-l1);border-radius:7px;margin:0 0 8px;overflow:hidden;
  background:var(--dsw-alias-bg-layer-2)}
.rt-kb.open{border-color:var(--dsw-alias-brand-primary)}
.rt-kb-head{display:flex;align-items:center;gap:7px;padding:7px 9px;cursor:pointer;outline:none;flex-wrap:wrap}
.rt-kb-head:hover{background:var(--dsw-alias-bg-layer-1)}
.rt-kb-head:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:-2px}
.rt-kb-title{font-weight:600;font-size:12.5px;overflow-wrap:anywhere}
.rt-kb-kind{font-size:10px;font-weight:700;letter-spacing:.4px;padding:1px 5px;border-radius:4px;
  color:#fff;background:#64748b;flex:none}
.rt-kb-kind.k-exp{background:#ef4444}
.rt-kb-kind.k-poc{background:#f59e0b}
.rt-kb-kind.k-template{background:#8b5cf6}
.rt-kb-kind.k-script{background:#0ea5e9}
.rt-kb-kind.k-payload{background:#10b981}
.rt-kb-sub{font-size:11px;color:var(--dsw-alias-label-secondary);padding:0 9px 7px;overflow-wrap:anywhere}
.rt-kb-body{padding:0 9px 9px}
.rt-kb-actions{display:flex;gap:6px;margin:7px 0}
.rt-kb-body .rt-kv span{overflow-wrap:anywhere;word-break:break-word}
/* 本机 nuclei 模板命中：路径要能完整看到（复制成命令直接跑） */
.rt-kb-tpl{margin-top:12px;border-top:1px dashed var(--dsw-alias-border-l1);padding-top:8px}
.rt-kb-tpl-row{display:flex;align-items:center;gap:7px;font-size:11.5px;padding:3px 7px;border-radius:5px;
  background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);margin-bottom:3px}
.rt-kb-tpl-path{flex:0 1 auto;font-weight:600;overflow-wrap:anywhere}
.rt-kb-tpl-name{flex:1 1 auto;min-width:0;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.rt-md{flex:1;overflow:auto;margin:0;padding:14px 16px;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;
  line-height:1.65;white-space:pre-wrap;word-break:break-word;background:var(--dsw-alias-bg-base)}
.rt-weblink{display:block;font-size:11.5px;margin-top:1px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rt-shots{margin:8px 0 4px;padding:7px 8px;border:1px solid var(--dsw-alias-border-l1);border-radius:7px;
  background:var(--dsw-alias-bg-layer-1)}
.rt-shots-head{display:flex;align-items:baseline;gap:8px;font-size:11.5px;margin-bottom:6px}
.rt-shots-n{color:var(--dsw-alias-label-secondary)}
.rt-shot-row{display:flex;gap:8px;flex-wrap:wrap}
.rt-shot{display:flex;flex-direction:column;gap:3px;max-width:220px}
.rt-shot-thumb{border:1px solid var(--dsw-alias-border-l1);border-radius:5px;background:#0b1020;
  object-fit:contain;display:block;width:auto;max-width:216px}
.rt-shot-loading{display:flex;align-items:center;justify-content:center;width:150px;font-size:11px;
  color:var(--dsw-alias-label-secondary)}
.rt-shot-cap{display:flex;align-items:center;gap:5px;font-size:10.5px;overflow-wrap:anywhere}
.rt-shot-label{color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px}
.rt-shot-zoom{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.82);display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:10px;cursor:zoom-out;padding:18px}
.rt-shot-zoom img{max-width:96vw;max-height:86vh;border-radius:6px;box-shadow:0 18px 48px rgba(0,0,0,.5)}
.rt-shot-zoom-cap{color:#e5e7eb;font-size:12px;text-align:center;max-width:90vw;overflow-wrap:anywhere}`    /* ---------------------------------------------------------- 桥接与状态 */
    /** 是否在「全面浏览」独立窗口里（URL hash 标记，复用同一套界面代码）。 */
    const isFullWindow = () => {
      try { return String(window.location.hash || '') === '#redteam-full' } catch { return false }
    }

    // Every request has a deadline, including response-body parsing. A caller can
    // cancel its own generation without changing another tab's requests.
    const api = async (req, options = {}) => {
      // Explicit read allowlist: never replay writes, execution, secret reveal,
      // or future operations whose idempotency has not been established.
      const attempts = ['bootstrap', 'vulns', 'credentials', 'access', 'attackFiles'].includes(req.op) ? 3 : 1
      const controller = new AbortController()
      let timer, onAbort
      const stopped = new Promise((_, reject) => {
        onAbort = () => {
          controller.abort()
          const error = new Error('请求已取消')
          error.name = 'AbortError'
          reject(error)
        }
        if (options.signal?.aborted) onAbort()
        else options.signal?.addEventListener('abort', onAbort, { once: true })
        timer = setTimeout(() => {
          controller.abort()
          reject(new Error('请求超时，请重试'))
        }, 15000)
      })
      try {
        return await Promise.race([stopped, (async () => {
          for (let attempt = 0; attempt < attempts; attempt++) {
            if (controller.signal.aborted) { const error = new Error('请求已取消'); error.name = 'AbortError'; throw error }
            try {
              const res = await fetch('/redteam/api', {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify(req),
                signal: controller.signal,
              })
              if (!res.ok) throw new Error('请求失败（HTTP ' + res.status + '）')
              try { return await res.json() }
              catch (error) {
                if (error?.name === 'TypeError') throw error
                throw new Error('服务器返回了无效数据，请重试')
              }
            } catch (error) {
              if (error?.name !== 'TypeError' || controller.signal.aborted || attempt + 1 >= attempts) throw error
              await new Promise(resolve => setTimeout(resolve, 200 * (attempt + 1)))
            }
          }
        })()])
      } finally {
        clearTimeout(timer)
        options.signal?.removeEventListener('abort', onAbort)
      }
    }

    let ui = { open: true, tab: 'assets' }
    const subs = new Set()
    const setUI = (patch) => {
      ui = Object.assign({}, ui, patch)
      const snap = Object.assign({}, ui)
      for (const f of Array.from(subs)) {
        try { f(snap) } catch { /* ignore subscriber errors */ }
      }
    }
    /* 保留导出。面板尺寸只写在自己的元素上，不再改官方 frame 的宽度。 */
    let dockWidthTag = null
    const setDockWidth = () => {}
    let SecurityView
    function SecurityTab(props) {
      if (!SecurityView) SecurityView = createSecurityTab(React, api)
      return h(SecurityView, props)
    }
    const useUI = () => {
      const [st, setSt] = React.useState(() => Object.assign({}, ui))
      React.useEffect(() => {
        const f = (snap) => setSt(Object.assign({}, snap || ui))
        subs.add(f)
        setSt(Object.assign({}, ui))
        return () => { subs.delete(f) }
      }, [])
      return st
    }

    /* 知识库归类（与 core.js 的 POC_CATEGORIES 一致；面板按它分组） */
    const POC_CAT_NAME = {
      rce: '远程命令执行', deserialization: '反序列化', 'file-upload': '文件上传 getshell',
      sqli: 'SQL 注入', unauthorized: '未授权访问', 'auth-bypass': '认证绕过 / 越权',
      'weak-password': '弱口令 / 爆破', ssrf: 'SSRF', xxe: 'XXE',
      'path-traversal': '目录穿越 / 任意文件读', 'info-leak': '信息泄露',
      privesc: '提权 / 横向', tunnel: '隧道 / 代理', other: '其它',
    }
    const POC_CAT_ORDER = Object.keys(POC_CAT_NAME)
    /* 角色 code → 中文（报告/知识库都要标"谁发现的"） */
    const ROLE_LABEL = {
      plan: '主会话（指挥）', recon: '信息收集', assess: '资产梳理',
      'vuln-scan': '漏洞发现', exploit: '漏洞利用', internal: '内网渗透',
    }

    const fmt = (s) => (s ? String(s).replace('T', ' ').slice(0, 16) : '—')
    const shotCache = new Map()
    const shotLoading = new Map()
    const shotSrc = (eng, id) => shotCache.get(eng + ':' + id) || null
    const loadShot = (eng, id) => {
      const key = eng + ':' + id
      if (shotCache.has(key) || shotLoading.has(key)) return
      const p = api({ op: 'shotData', engagement: eng, id: id }).then((r) => {
        shotCache.set(key, r && r.base64 ? 'data:' + (r.mime || 'image/png') + ';base64,' + r.base64 : '')
        shotLoading.delete(key)
        const snap = Object.assign({}, ui)
        for (const f of Array.from(subs)) {
          try { f(snap) } catch { /* ignore subscriber errors */ }
        }
      }).catch(() => { shotLoading.delete(key) })
      shotLoading.set(key, p)
    }
    const SHOT_KIND = { screenshot: '现场截图', card: '记录生成的证据摘录' }
    const ShotImage = ({ eng, shot, height }) => {
      const [zoom, setZoom] = React.useState(false)
      const src = shotSrc(eng, shot.id)
      if (src === null) { loadShot(eng, shot.id); }
      const card = shot.kind === 'card'
      return h('div', { className: 'rt-shot' },
        src === null
          ? h('div', { className: 'rt-shot-thumb rt-shot-loading', style: { height: (height || 96) + 'px' } }, '载入中…')
          : h('img', {
              className: 'rt-shot-thumb', src: src, alt: shot.label || ('证据 ' + shot.id),
              style: { height: (height || 96) + 'px', cursor: 'zoom-in' },
              onClick: () => setZoom(true),
            }),
        h('div', { className: 'rt-shot-cap' },
          h('span', { className: 'rt-tag ' + (card ? 'rt-tag-warn' : 'rt-tag-live'), title: card
            ? '由当日记录生成的证据摘录，不是现场截图 —— 报告里同样会标注'
            : '现场截图' }, SHOT_KIND[shot.kind] || shot.kind || '证据'),
          h('span', { className: 'rt-shot-label', title: shot.label || shot.note || '' },
            shot.label || shot.target || ('#' + shot.id))),
        zoom
          ? h('div', { className: 'rt-shot-zoom', onClick: () => setZoom(false) },
              h('img', { src: src, alt: shot.label || '' }),
              h('div', { className: 'rt-shot-zoom-cap' }, (shot.label || shot.target || '')
                + (card ? '　·　由当日记录生成（非现场截图）' : '')
                + (shot.captured_at ? '　·　' + fmt(shot.captured_at) : '')
                + '　·　点击任意处关闭'))
          : null)
    }
    const ShotStrip = ({ eng, shots, total, title }) => {
      const list = shots || []
      if (list.length === 0) return null
      return h('div', { className: 'rt-shots' },
        h('div', { className: 'rt-shots-head' },
          h('b', null, title || '证据截图'),
          h('span', { className: 'rt-shots-n' }, '显示 ' + list.length + ' 张'
            + (total && total > list.length ? '（该得分点共 ' + total + ' 张，取代表图）' : ''))),
        h('div', { className: 'rt-shot-row' }, list.map((sh) => h(ShotImage, { key: 'sh' + sh.id, eng: eng, shot: sh }))))
    }
    /** 发现时间在列表里只留「月-日 时:分」：整行宽度紧张，完整时间进悬浮提示 */
    const fmtShort = (s) => {
      const t = String(s || '').replace('T', ' ')
      return t.length >= 16 ? t.slice(5, 16) : (t || '—')
    }
    const provLabel = (p) => (p === 'passive' ? '被动' : p === 'active' ? '主动' : '未知')

    /**
     * 给「可点击但不是 <button>」的元素补上键盘可达性，返回可直接展开进 props 的对象。
     *
     * 为什么需要：面板里大量用 div/span 当按钮（表格行、页签、结论条、C 段条目…），
     * 它们鼠标能点、键盘完全够不着 —— 而这类元素此前有 16 处是各写各的，
     * 写法还不一致（有的只有 role、有的漏了 Space 键）。
     * 统一到一个工厂后，新增可点击元素只要 `...clickable(fn, { label })` 就有完整语义。
     *
     * 注意：**不要**用它包真正的 `<button>`（原生按钮自带全部语义）。
     * @param onActivate - 激活回调（鼠标点击 / Enter / Space 都走它）。
     * @param options - `{ label?, expanded? }`：label 进 aria-label，expanded 进 aria-expanded。
     * @returns props 片段：role / tabIndex / onClick / onKeyDown / aria-*
     */
    const clickable = (onActivate, options = {}) => {
      const props = {
        role: 'button',
        tabIndex: 0,
        onClick: onActivate,
        onKeyDown: (e) => {
          /* Enter 与 Space 是按钮的标准激活键；Space 还要阻止页面滚动 */
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onActivate(e)
          }
        },
      }
      if (options.label !== undefined) props['aria-label'] = String(options.label)
      if (options.expanded !== undefined) props['aria-expanded'] = options.expanded ? 'true' : 'false'
      return props
    }

    /**
     * 复制文本到剪贴板，**返回真实的成功与否**。
     *
     * clipboard API 在非安全上下文（http + 非 localhost）、页面失焦、权限被拒时都会
     * 返回被拒绝的 Promise —— 同步 try/catch 抓不到，于是界面会显示"已复制"而剪贴板是空的。
     * 这里 await 真实结果，并在不可用时退回 execCommand('copy')（老浏览器/非安全上下文仍可用）。
     * @param text - 要复制的文本。
     * @returns Promise<boolean>
     */
    const copyText = async (text) => {
      const value = text === undefined || text === null ? '' : String(text)
      if (value === '') return false
      try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          await navigator.clipboard.writeText(value)
          return true
        }
      } catch (e) { /* 落到下面的兜底方案 */ }
      /* 兜底：临时 textarea + execCommand —— 非安全上下文里唯一还能用的办法 */
      try {
        const ta = document.createElement('textarea')
        ta.value = value
        ta.setAttribute('readonly', '')
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        document.body.appendChild(ta)
        ta.select()
        const okFlag = document.execCommand('copy')
        document.body.removeChild(ta)
        return okFlag === true
      } catch (e) { return false }
    }

    /**
     * 复制并给出**如实**的界面反馈（成功/失败文案统一）。
     * @param text - 要复制的文本。
     * @param label - 成功时提示里显示的名字。
     * @param onResult - 可选回调：`(ok, message) => void`；不传时返回 Promise<boolean>。
     */
    const copyWithFeedback = async (text, label, onResult) => {
      const okFlag = await copyText(text)
      const message = okFlag ? '已复制：' + label : '复制失败（浏览器未授权剪贴板）—— 请手动选中文本复制'
      if (typeof onResult === 'function') onResult(okFlag, message)
      return okFlag
    }

    function ProvTag(props) {
      if (!props.p) return h('span', { className: 'rt-tag' }, '未知')
      return h('span', { className: 'rt-tag rt-tag-' + props.p }, provLabel(props.p))
    }

    const TEST_LABEL = { untested: '未测试', testing: '测试中', tested: '已测试', blocked: '被封禁', abandoned: '已放弃', no_surface: '无攻击面' }
    const PRI_LABEL = { high: '高', medium: '中', low: '低' }

    /** 资产易打性徽章。 */
    function PriTag(props) {
      if (!props.p) return h('span', { className: 'rt-tag' }, '未评')
      return h('span', { className: 'rt-pri rt-pri-' + props.p, title: props.title || '' }, PRI_LABEL[props.p] || props.p)
    }

    /** 资产测试状态徽章。 */
    function TestTag(props) {
      const st = props.s || 'untested'
      return h('span', { className: 'rt-test rt-test-' + st }, TEST_LABEL[st] || st)
    }

    /* ---------------------------------------------------------- 资产测绘 */
    function AssetsTab(props) {
      const eng = props.engagement
      const snapshot = props.snapshot
      const refreshKey = props.refreshKey || 0
      const onRefresh = props.onRefresh
      const [view, setView] = React.useState('list')
      const [cidr, setCidr] = React.useState(null)
      const [q, setQ] = React.useState('')
      const [qApplied, setQApplied] = React.useState('')
      const [service, setService] = React.useState('')
      const [port, setPort] = React.useState('')
      const [prov, setProv] = React.useState('')
      const [testStatus, setTestStatus] = React.useState('')
      const [priority, setPriority] = React.useState('')
      const [scope, setScope] = React.useState('')
      const [assetState, setAssetState] = React.useState('')
      const [sort, setSort] = React.useState('priority')
      const [showAll, setShowAll] = React.useState(null)
      const [state, setState] = React.useState({ loading: false, error: null, total: 0, items: [] })
      const [domains, setDomains] = React.useState(null)
      const [web, setWeb] = React.useState(null)
      const [openId, setOpenId] = React.useState(null)
      const [detail, setDetail] = React.useState(null)
      /* 左侧「外网 C 段 / 内网 C 段」两组各自折叠，状态按靶标记住 */
      const sideCollapse = useCollapse('assets-side:' + eng)
      const seq = React.useRef(0)
      const onData = props.onData

      React.useEffect(() => {
        if (!eng) return
        const my = ++seq.current
        setState((s) => Object.assign({}, s, { loading: true, error: null }))
        api({
          op: 'assets', engagement: eng, cidr: cidr || undefined, q: qApplied || undefined,
          service: service || undefined, port: port || undefined,
          provenance: prov || undefined, test_status: testStatus || undefined,
          priority: priority || undefined, scope: scope || undefined,
          state: assetState || undefined, sort: sort, limit: 400,
        }).then((r) => {
          if (my !== seq.current) return
          if (!r || r.ok === false) {
            setState({ loading: false, error: (r && r.error) || '查询失败', total: 0, items: [] })
            return
          }
          setState({ loading: false, error: null, total: r.total, items: r.items || [] })
          /* C 段/统计可能因本轮采集新增：让外层重新拉一次快照，左侧分类立即更新 */
          if (onData) onData()
        }, (e) => {
          if (my === seq.current) setState({ loading: false, error: String((e && e.message) || e), total: 0, items: [] })
        })
      }, [eng, cidr, qApplied, service, port, prov, testStatus, priority, scope, assetState, sort, refreshKey])

      React.useEffect(() => {
        if (!eng || view !== 'domain') return
        setDomains(null)
        api({ op: 'domains', engagement: eng, cidr: cidr || undefined })
          .then((r) => setDomains((r && r.items) || []), () => setDomains([]))
      }, [eng, view, cidr, refreshKey])

      React.useEffect(() => {
        if (!eng || view !== 'web') return
        setWeb(null)
        api({ op: 'web', engagement: eng, cidr: cidr || undefined })
          .then((r) => setWeb((r && r.items) || []), () => setWeb([]))
      }, [eng, view, cidr, refreshKey])


      const toggleRow = (id) => {
        if (openId === id) { setOpenId(null); setDetail(null); return }
        setOpenId(id)
        setDetail(null)
        api({ op: 'asset', engagement: eng, id: id }).then((r) => {
          if (r && r.ok && r.asset) setDetail(r.asset)
        }, () => {})
      }

      const segs = (snapshot && snapshot.segments) || []

      const sideChildren = []
      sideChildren.push(h('div', Object.assign({
        key: 'all', className: 'rt-seg' + (cidr === null && view !== 'testing' ? ' on' : ''),
      }, clickable(() => { setView('list'); setCidr(null) }, { label: '全部 C 段', expanded: cidr === null && view !== 'testing' })),
        h('div', { className: 'rt-seg-cidr' }, '全部 C 段'),
        h('div', { className: 'rt-seg-meta' }, segs.length + ' 个网段')))
      sideChildren.push(h('div', Object.assign({
        key: 'testing', className: 'rt-seg' + (view === 'testing' ? ' on' : ''),
        title: '正在跑的扫描 / 探测与进度（5 秒自动刷新）',
      }, clickable(() => { setView('testing'); setCidr(null) }, { label: '当前测试', expanded: view === 'testing' })),
        h('div', { className: 'rt-seg-cidr', style: { display: 'flex', alignItems: 'baseline', gap: 5 } },
          h('span', { className: 'rt-scope rt-scope-testing', title: '当前测试（既非内网也非外网）' }, '测'),
          h('span', { style: { flex: 1 } }, '当前测试')),
        h('div', { className: 'rt-seg-meta' }, '正在跑的扫描与探测')))
      /* C 段按内外网分组：先外网（互联网可达，通常是入口）再内网（打进去之后才看得到） */
      const segBlock = (title, list, kind) => {
        /* 外网 / 内网两组各自可折叠（状态按靶标记住），默认展开 */
        const open = sideCollapse.isOpen('scope:' + kind, true)
        const toggle = sideCollapse.toggle('scope:' + kind, true)
        const out = [h('div', {
          key: 'h' + kind, className: 'rt-sidehead rt-sidehead-btn',
          role: 'button', tabIndex: 0, 'aria-expanded': open ? 'true' : 'false',
          title: (open ? '收起本组' : '展开本组') + '（并切回资产列表）',
          onClick: () => { setView('list'); toggle() },
          onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setView('list'); toggle(e) } },
        },
          h('span', { className: 'rt-sec-caret' }, open ? '▾' : '▸'),
          h('span', { className: 'rt-scope rt-scope-' + kind }, kind === 'internal' ? '内网' : '外网'),
          h('span', null, title + ' · ' + list.length + ' 个 C 段'),
          h('span', { className: 'rt-spacer' }),
          h('span', { style: { fontWeight: 400 } }, list.reduce((n, x) => n + (x.assets || 0), 0) + ' 资产'))]
        if (!open) return out
        for (const s of list) {
          /* 一段一行：只给 C 段 + 资产数（端口数不再占位，归属与存活放进悬浮提示） */
          out.push(h('div', Object.assign({
            key: s.cidr, className: 'rt-seg' + (cidr === s.cidr ? ' on' : ''),
            title: (s.org || '未知归属') + ' · 存活 ' + (s.live || 0) + '/' + (s.assets || 0) + ' 台',
          }, clickable(() => { setView('list'); setCidr(s.cidr) },
            { label: '筛选 C 段 ' + s.cidr, expanded: cidr === s.cidr && view !== 'testing' })),
            h('div', { className: 'rt-seg-cidr', style: { display: 'flex', alignItems: 'baseline', gap: 5 } },
              h('span', { className: 'rt-scope rt-scope-' + kind }, kind === 'internal' ? '内' : '外'),
              h('span', { style: { flex: 1 } }, s.cidr),
              h('span', { className: 'rt-seg-meta', style: { margin: 0, whiteSpace: 'nowrap' } },
                s.assets + ' 台'))))
        }
        return out
      }
      const segExternal = segs.filter((x) => x.scope !== 'internal')
      const segInternal = segs.filter((x) => x.scope === 'internal')
      if (segExternal.length) sideChildren.push(...segBlock('外网资产', segExternal, 'external'))
      if (segInternal.length) sideChildren.push(...segBlock('内网资产', segInternal, 'internal'))
      const side = h('div', { className: 'rt-side' }, sideChildren)

      const toolbar = h('div', { className: 'rt-toolbar' },
        h('input', {
          className: 'rt-input', style: { flex: '1 1 150px' }, placeholder: '搜索 IP / 域名 / 指纹（回车）',
          value: q, onChange: (e) => setQ(e.target.value),
          onKeyDown: (e) => { if (e.key === 'Enter') setQApplied(q) },
        }),
        h('button', { className: 'rt-btn', onClick: () => setQApplied(q) }, '搜索'),
        h('input', {
          className: 'rt-input', style: { width: '78px' }, placeholder: '服务',
          value: service, onChange: (e) => setService(e.target.value),
        }),
        h('input', {
          className: 'rt-input', style: { width: '60px' }, placeholder: '端口',
          value: port, onChange: (e) => setPort(e.target.value),
        }),
        h('select', { className: 'rt-input', value: scope, onChange: (e) => setScope(e.target.value) },
          h('option', { value: '' }, '内外网不限'),
          h('option', { value: 'external' }, '仅外网资产'),
          h('option', { value: 'internal' }, '仅内网资产')),
        h('select', { className: 'rt-input', value: prov, onChange: (e) => setProv(e.target.value), title: '按端口来源过滤（列表已不再单列显示，详情里可见）' },
          h('option', { value: '' }, '来源不限'),
          h('option', { value: 'passive' }, '仅被动'),
          h('option', { value: 'active' }, '仅主动')),
        h('select', { className: 'rt-input', value: priority, onChange: (e) => setPriority(e.target.value) },
          h('option', { value: '' }, '易打性不限'),
          h('option', { value: 'high' }, '易打（高）'),
          h('option', { value: 'medium' }, '一般（中）'),
          h('option', { value: 'low' }, '难打（低）')),
        h('select', { className: 'rt-input', value: testStatus, onChange: (e) => setTestStatus(e.target.value) },
          h('option', { value: '' }, '测试状态不限'),
          h('option', { value: 'untested' }, '未测试'),
          h('option', { value: 'testing' }, '测试中'),
          h('option', { value: 'tested' }, '已测试'),
          h('option', { value: 'blocked' }, '被封禁'),
          h('option', { value: 'abandoned' }, '已放弃'),
          h('option', { value: 'no_surface' }, '无攻击面')),
        h('div', { className: 'rt-spacer' }),
        h('button', { className: 'rt-btn', title: '重新拉取快照与当前视图数据', onClick: () => { if (onRefresh) onRefresh() } }, '刷新'),
        h('button', { className: 'rt-btn' + (view === 'list' ? ' rt-btn-primary' : ''), onClick: () => setView('list') }, '列表'),
        h('button', { className: 'rt-btn' + (view === 'timeline' ? ' rt-btn-primary' : ''), title: '按发现时间看资产（什么时候发现、哪天收了多少）', onClick: () => setView('timeline') }, '发现时间'),
        h('button', { className: 'rt-btn' + (view === 'domain' ? ' rt-btn-primary' : ''), onClick: () => setView('domain') }, '域名'),
        h('button', { className: 'rt-btn' + (view === 'web' ? ' rt-btn-primary' : ''), onClick: () => setView('web') }, 'Web'))

      /* ── 结论行：一屏看清家底，数字点一下就是筛选 ───────────────────── */
      const tests = (snapshot && snapshot.tests) || {}
      const snapStats = (snapshot && snapshot.stats) || {}
      const noFilter = !testStatus && !priority && !scope && !prov && !assetState && !cidr
      const conclItem = (key, label, value, active, onClick) => h('span', Object.assign({
        key: key, className: 'rt-concl-i' + (active ? ' on' : ''), title: '点击筛选 / 再点取消',
      }, clickable(onClick, { label: '按「' + label + '」筛选（' + (value || 0) + '）', expanded: active })),
        h('b', null, String(value || 0)), h('span', null, label))
      const toggleTest = (v) => { setTestStatus((cur) => (cur === v ? '' : v)); setAssetState('') }
      const conclusion = h('div', { className: 'rt-concl' },
        conclItem('all', '台资产', snapStats.assets, noFilter, () => {
          setTestStatus(''); setPriority(''); setScope(''); setProv(''); setAssetState(''); setCidr(null)
        }),
        conclItem('live', '存活', snapStats.liveAssets, assetState === 'live', () => { setAssetState((v) => (v === 'live' ? '' : 'live')); setTestStatus('') }),
        conclItem('untested', '待测', tests.untested, testStatus === 'untested', () => toggleTest('untested')),
        conclItem('testing', '测试中', tests.testing, testStatus === 'testing', () => toggleTest('testing')),
        conclItem('tested', '已测', tests.tested, testStatus === 'tested', () => toggleTest('tested')),
        conclItem('giveup', '放弃', (tests.abandoned || 0) + (tests.blocked || 0), testStatus === 'abandoned,blocked', () => toggleTest('abandoned,blocked')),
        h('div', { className: 'rt-spacer' }),
        h('select', {
          className: 'rt-input', value: sort, onChange: (e) => setSort(e.target.value),
          title: '列表排序方式',
        },
          h('option', { value: 'priority' }, '排序：易打性优先'),
          h('option', { value: 'todo' }, '排序：待测优先'),
          h('option', { value: 'discovered' }, '排序：最近发现优先'),
          h('option', { value: 'ports' }, '排序：端口多优先'),
          h('option', { value: 'ip' }, '排序：按 IP')))

      const head = h('div', { className: 'rt-row head' },
        h('span', null, 'IP'), h('span', null, '易打'), h('span', null, '测试状态'),
        h('span', null, '开放端口 / 服务'), h('span', null, '指纹'))

      const rowNodes = []
      for (const it of state.items) {
        const openPorts = it.ports.filter((p) => p.state === 'open')
        const portText = openPorts.map((p) => p.port + (p.service ? '/' + p.service : '')).join(', ') || '—'
        const fpText = it.fingerprints.map((f) => [f.vendor, f.product, f.version].filter(Boolean).join(' ')).join(' / ') || '—'
        /* 端口最多列 3 个，其余用 +N；主被动来源不再占列，进详情 */
        const shownPorts = openPorts.slice(0, 3).map((p) => p.port + (p.service ? '/' + p.service : '')).join(', ')
        const morePorts = openPorts.length > 3 ? ' +' + (openPorts.length - 3) : ''
        rowNodes.push(h('div', Object.assign({
          key: 'r' + it.id, className: 'rt-row',
        }, clickable(() => toggleRow(it.id), { label: '展开资产 ' + it.ip, expanded: openId === it.id })),
          h('span', { className: 'rt-mono', style: { display: 'flex', alignItems: 'baseline', gap: 4, flexWrap: 'wrap' } },
            h('span', {
              className: 'rt-scope rt-scope-' + (it.scope === 'internal' ? 'internal' : 'external'),
            }, it.scope === 'internal' ? '内' : '外'),
            h('span', {
              title: it.state === 'live' ? '存活' : String(it.state),
              style: {
                width: 7, height: 7, borderRadius: '50%', flex: 'none', marginTop: 4,
                background: it.state === 'live' ? '#10b981' : '#94a3b8',
              },
            }),
            h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis' } }, it.ip),
            /* 发现时间挂在 IP 下面一行：IP 列宽度有限，不另开列（列宽一改整表要跟着调） */
            h('span', {
              style: { fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)', whiteSpace: 'nowrap' },
              title: '发现时间：' + (it.discovered_at ? fmt(it.discovered_at) : '未记录')
                + (it.last_seen ? '\n最近采集：' + fmt(it.last_seen) : ''),
            }, it.discovered_at ? fmtShort(it.discovered_at) : '发现时间未知')),
          h('span', null, h(PriTag, { p: it.priority, title: it.potential || '' })),
          h('span', null, h(TestTag, { s: it.test_status }),
            it.blocked_count ? h('span', { className: 'rt-tag', style: { color: '#ef4444', borderColor: '#ef444455', marginLeft: 4 } }, '封' + it.blocked_count) : null),
          h('span', { title: portText }, (shownPorts || '—') + morePorts),
          h('span', { title: fpText }, fpText.length > 30 ? fpText.slice(0, 30) + '…' : fpText)))

        if (openId !== it.id) continue
        const d = detail && detail.id === it.id ? detail : null
        const portRows = []
        const fpRows = []
        const obsRows = []
        if (d) {
          for (const p of (d.ports || [])) {
            if (p.state !== 'open') continue
            portRows.push(h('div', { key: 'p' + p.port, className: 'rt-kv' },
              h('b', { className: 'rt-mono' }, p.port + '/' + p.proto),
              h('span', null, [p.service, p.product, p.version].filter(Boolean).join(' ') || '未知服务'),
              p.url ? h('a', { className: 'rt-link', href: p.url, target: '_blank', rel: 'noreferrer', title: p.url }, p.title ? p.title : p.url) : null,
              h(ProvTag, { p: p.provenance })))
          }
          for (const f of (d.fingerprints || [])) {
            fpRows.push(h('div', { key: 'f' + (f.product || '') + (f.version || '') + (f.evidence || ''), className: 'rt-kv' },
              h('b', null, f.category || '—'),
              h('span', null, [f.vendor, f.product, f.version].filter(Boolean).join(' ') + (f.evidence ? '（' + f.evidence + '）' : '')),
              h(ProvTag, { p: f.provenance })))
          }
          for (const o of (d.observations || []).slice(0, 8)) {
            obsRows.push(h('div', { key: 'o' + (o.attr || '') + (o.value || '') + (o.collected_at || ''), className: 'rt-kv' },
              h('b', null, o.attr || '—'),
              h('span', null, (o.value || '') + ' · ' + (o.tool || '未知工具') + ' · ' + fmt(o.collected_at)),
              h(ProvTag, { p: o.provenance })))
          }
        }
        /* 详情分三层：3 行必读 → 「展开全部」后才是溯源、原始记录与备注全文 */
        const all = showAll === it.id
        const noteLines = d && d.test_notes ? d.test_notes.split('\n').filter(Boolean) : []
        const inner = d
          ? h('div', null,
              /* 必读三行 */
              h('div', { className: 'rt-kv' }, h('b', null, '测试'), h('span', null,
                h(TestTag, { s: d.test_status }),
                d.blocked_count ? h('span', { className: 'rt-tag', style: { marginLeft: 6, color: '#ef4444', borderColor: '#ef444455' } }, '被封 ' + d.blocked_count + ' 次') : null,
                h('span', { style: { marginLeft: 8, color: 'var(--dsw-alias-label-secondary)' } },
                  (d.test_updated_at ? fmt(d.test_updated_at) : '未测过') + (d.test_updated_by ? ' · ' + d.test_updated_by : '')))),
              h('div', { className: 'rt-kv' }, h('b', null, '易打性'), h('span', null,
                h(PriTag, { p: d.priority }),
                h('span', { style: { marginLeft: 8 } }, d.potential || '未评估'),
                d.assess_reason ? h('span', { style: { marginLeft: 8, color: 'var(--dsw-alias-label-secondary)' } }, d.assess_reason) : null)),
              h('div', { className: 'rt-kv' }, h('b', null, '攻击面'), h('span', null,
                d.test_surface || (portRows.length ? '未记录（开放端口见下）' : '无开放端口'),
                d.scope ? h('span', { className: 'rt-scope rt-scope-' + (d.scope === 'internal' ? 'internal' : 'external'), style: { marginLeft: 8 } },
                  d.scope === 'internal' ? '内网资产' : '外网资产') : null)),
              h('span', Object.assign({ className: 'rt-more' },
                clickable(() => setShowAll(all ? null : it.id), { label: all ? '收起资产详情' : '展开资产详情', expanded: all })),
                all ? '收起全部 ▲' : '展开全部（端口 · 指纹 · 采集溯源 · 测试记录）▼'),
              all ? h('div', null,
                h('div', { className: 'rt-kv' }, h('b', null, '主机名'), h('span', null, (d.names || []).map((n) => n.name).join(', ') || '—')),
                h('div', { className: 'rt-kv' }, h('b', null, '发现时间'),
                  h('span', { title: '本条资产第一次进入资产库的时刻（重复采集只刷新"最近采集"）' }, fmt(d.discovered_at)),
                  h('b', { style: { minWidth: 0, marginLeft: 8 } }, '最近采集'), h('span', null, fmt(d.last_seen)),
                  h('b', { style: { minWidth: 0, marginLeft: 8 } }, '数据源首见'), h('span', null, fmt(d.first_seen))),
                h('div', { className: 'rt-kv' }, h('b', null, 'C 段'), h('span', null, d.segment_cidr)),
                h('div', { className: 'rt-kv' }, h('b', null, '易打性'), h('span', null,
                  (d.priority || '未评估') + (d.potential ? ' · 预期：' + d.potential : '')
                  + (d.assess_reason ? ' · 依据：' + d.assess_reason : '')
                  + (d.assessed_at ? '（' + fmt(d.assessed_at) + '）' : ''))),
                h('div', { className: 'rt-kv' }, h('b', null, '来源'), h('span', null,
                  '被动端口 ' + (d.passive || 0) + ' · 主动端口 ' + (d.active || 0))),
                h('div', { style: { margin: '6px 0 3px', fontWeight: 600 } }, '开放端口 / 服务'),
                h('div', null, portRows.length ? portRows : '—'),
                h('div', { style: { margin: '6px 0 3px', fontWeight: 600 } }, '指纹'),
                h('div', null, fpRows.length ? fpRows : '—'),
                noteLines.length
                  ? h(Clip, { key: 'notes', label: '测试记录（' + noteLines.length + ' 条）', text: noteLines.join('\n') })
                  : null,
                h('div', { style: { margin: '6px 0 3px', fontWeight: 600 } }, '采集溯源（最近 8 条）'),
                h('div', null, obsRows.length ? obsRows : '—'))
                : null)
          : h('div', null, '加载中…')
        rowNodes.push(h('div', {
          key: 'd' + it.id, className: 'rt-row',
          style: { cursor: 'default', gridTemplateColumns: '1fr' },
        }, h('div', { className: 'rt-expand' }, inner)))
      }

      const listPane = h('div', { className: 'rt-table' }, head, rowNodes,
        !state.loading && !state.items.length ? h('div', { className: 'rt-empty' }, '没有匹配的资产') : null)

      /* 域名维度：域名 → 关联资产 */
      const domainPane = h('div', { className: 'rt-table' },
        domains === null ? h('div', { className: 'rt-empty' }, '加载中…')
          : domains.length
          ? domains.map((g) => h('div', { key: g.domain },
              h('div', { className: 'rt-section', style: { padding: '8px 10px 4px' } },
                h('a', { className: 'rt-link', href: 'http://' + g.domain, target: '_blank', rel: 'noreferrer' }, g.domain),
                h('span', { className: 'rt-tag', style: { marginLeft: 8 } }, g.count + ' 个资产')),
              g.assets.map((a) => h('div', {
                key: String(g.domain) + '\u0000' + a.id + '\u0000' + a.ip, className: 'rt-row',
                style: { gridTemplateColumns: '150px 130px 70px 1fr', cursor: 'pointer' },
                onClick: () => { setView('list'); setQ(''); setQApplied(a.ip) },
              },
                h('span', { className: 'rt-mono' }, a.ip),
                h('span', { className: 'rt-mono' }, a.segment),
                h('span', null, h('span', { className: 'rt-tag rt-tag-' + (a.state === 'live' ? 'live' : 'dead') }, a.state === 'live' ? '存活' : a.state)),
                h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } }, (a.names || []).join(', '))))))
          : h('div', { className: 'rt-empty' }, cidr ? '该 C 段下暂无域名（切换到「全部 C 段」看全量）' : '暂无域名数据（信息收集阶段会写入域名）'))

      /* Web 资产：标题 + 可直接点击的 URL */
      const webPane = h('div', { className: 'rt-table' },
        h('div', { className: 'rt-row head', style: { gridTemplateColumns: '1.6fr 1.2fr 130px 110px' } },
          h('span', null, 'URL（可点击）'), h('span', null, '标题'), h('span', null, '资产'), h('span', null, '服务')),
        (web || []).map((w) => {
          const url = w.url || ('http' + (w.port === 443 || w.port === 8443 || w.port === 9443 ? 's' : '') + '://' + w.ip + (w.port === 80 || w.port === 443 ? '' : ':' + w.port))
          return h('div', {
            key: 'w' + w.port_id, className: 'rt-row',
            style: { gridTemplateColumns: '1.6fr 1.2fr 130px 110px', cursor: 'default' },
          },
            h('a', { className: 'rt-link rt-mono', href: url, target: '_blank', rel: 'noreferrer', title: url }, url),
            h('span', { title: w.title || '' }, w.title || '—'),
            h('span', { className: 'rt-mono' }, w.ip + ' · ' + w.segment_cidr),
            h('span', { style: { fontSize: 11 } }, [w.service, w.product, w.version].filter(Boolean).join(' ')))
        }),
        web === null ? h('div', { className: 'rt-empty' }, '加载中…')
          : (!web.length ? h('div', { className: 'rt-empty' }, cidr ? '该 C 段下暂无 Web 资产' : '暂无 Web 资产（HTTP 探测后会写入 URL 与标题）') : null))


      let pane = listPane
      if (view === 'testing') pane = h(TestingTab, { engagement: eng, refreshKey: refreshKey })
      else if (view === 'domain') pane = domainPane
      else if (view === 'web') pane = webPane
      /* 发现时间视图自带滚动容器，直接放进 rt-main 的 flex 里 */
      else if (view === 'timeline') pane = h(DiscoveryView, { engagement: eng, refreshKey: refreshKey })

      return h('div', { className: 'rt-split' }, side,
        h('div', { className: 'rt-main' }, view === 'testing' ? null : toolbar,
          conclusion,
          state.error ? h('div', { className: 'rt-err' }, state.error) : null,
          pane))
    }

    /* ---------------------------------------------------------- 资产发现时间线 */
    /**
     * 资产发现时间线：什么时候发现了什么、哪天收了多少。
     * ⚠️ 这个组件曾在"移除图谱视图"时被连带删掉 —— 删除区间的结束标记选得太宽
     *    （图谱画布的收尾与它挨着），bundle 自检的 "client.js 有资产「发现时间」视图"
     *    因此变红。恢复时把插入点固定成"资产测绘注释块之前"，避免再被别的删除波及。
     */
    function DiscoveryView(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [day, setDay] = React.useState('')
      React.useEffect(() => {
        if (!eng) return
        setData(null)
        api({ op: 'discoveryTimeline', engagement: eng, limit: 200 })
          .then((r) => { if (!r || r.ok === false) setErr((r && r.error) || '加载失败'); else { setErr(null); setData(r) } },
            (e) => setErr(String((e && e.message) || e)))
      }, [eng, refreshKey])
      if (err) return h('div', { className: 'rt-pane' }, h('div', { className: 'rt-err' }, err))
      if (!data) return h('div', { className: 'rt-empty' }, '加载中…')
      const recent = (data.recent || []).filter((a) => day === '' || String(a.discovered_at || '').slice(0, 10) === day)
      return h('div', { className: 'rt-pane', style: { flex: 1, minHeight: 0 } },
        h('div', { className: 'rt-card' },
          h('h4', null, '资产发现时间线'),
          h('div', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)' } },
            '共 ' + ((data.span && data.span.total) || 0) + ' 台 · 最早 '
            + (data.span && data.span.first ? fmt(data.span.first) : '—')
            + ' · 最近 ' + (data.span && data.span.last ? fmt(data.span.last) : '—')
            + '（发现时间 = 第一次进入资产库的时刻；重复采集只刷新"最近采集"）')),
        (data.days || []).length === 0 ? h('div', { className: 'rt-empty' }, '还没有资产。') : null,
        h('div', { className: 'rt-card' },
          h('h4', null, '按天统计', day
            ? h('span', Object.assign({ className: 'rt-tag', style: { marginLeft: 6, cursor: 'pointer' } },
                clickable(() => setDay(''), { label: '清除按天筛选：' + day })), '清除筛选：' + day)
            : null),
          h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8 } },
            (data.days || []).map((d) => h('div', Object.assign({
              key: d.day, className: 'rt-seg' + (day === d.day ? ' on' : ''), style: { marginBottom: 0, cursor: 'pointer' },
              title: d.day + '：新增 ' + d.assets + ' 台（内网 ' + d.internal + ' / 外网 ' + d.external + '）',
            }, clickable(() => setDay(day === d.day ? '' : d.day),
              { label: '筛选 ' + d.day + ' 发现的资产', expanded: day === d.day })),
              h('div', { className: 'rt-seg-cidr' }, d.day),
              h('div', { className: 'rt-seg-meta' }, d.assets + ' 台 · 内 ' + d.internal + ' / 外 ' + d.external))))),
        h('div', { className: 'rt-card' },
          h('h4', null, day ? day + ' 发现的资产（' + recent.length + '）' : '最近发现的资产（' + recent.length + '）'),
          recent.length === 0 ? h('div', { className: 'rt-empty' }, '这一天没有新增资产。') : null,
          recent.map((a) => h('div', { key: a.id, className: 'rt-kv' },
            h('b', { className: 'rt-mono', style: { minWidth: 110 } },
              h('span', { className: 'rt-scope rt-scope-' + (a.scope === 'internal' ? 'internal' : 'external'), style: { marginRight: 4 } },
                a.scope === 'internal' ? '内' : '外'),
              a.ip),
            h('span', { style: { minWidth: 132, fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' } },
              a.discovered_at ? fmt(a.discovered_at) : '时间未知'),
            h('span', { style: { flex: 1 } }, (a.primary_name || '—') + (a.open_ports ? ' · ' + a.open_ports + ' 端口' : '')),
            h(PriTag, { p: a.priority })))))
    }

    /* ---------------------------------------------------------- 智能体提示词 */
    function PromptsTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [roles, setRoles] = React.useState([])
      const [active, setActive] = React.useState(null)
      const [draft, setDraft] = React.useState('')
      const [msg, setMsg] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [reloadKey, setReloadKey] = React.useState(0)

      const [loadedView, setLoadedView] = React.useState(undefined)
      const [loading, setLoading] = React.useState(true)
      const generation = React.useRef(0)
      const owner = React.useRef({ eng, refreshKey, reloadKey })
      const writing = React.useRef(false)
      const reader = React.useRef(null)
      const editEpoch = React.useRef(0), editVersion = editEpoch.current
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey || owner.current.reloadKey !== reloadKey) owner.current = { eng, refreshKey, reloadKey }
      const view = owner.current
      const ready = !loading && loadedView === view

      React.useEffect(() => {
        const token = ++generation.current, controller = new AbortController()
        reader.current = controller; writing.current = false
        setLoading(true); setLoadedView(undefined); setRoles([]); setActive(null); setDraft(''); setMsg(null); setBusy(false)
        api(eng ? { op: 'prompts', engagement: eng } : { op: 'prompts' }, { signal: controller.signal }).then((r) => {
          if (generation.current !== token || owner.current !== view) return
          setLoading(false)
          if (!r || r.ok === false) { setMsg({ err: r?.error || '读取失败，请刷新后再编辑' }); return }
          setLoadedView(view); setRoles(r.roles || []); setActive(r.roles?.[0]?.role || null)
          if (r.builtin) setMsg({ ok: '当前为内置默认提示词（创建靶标后可按靶标保存修改）' })
        }, (e) => {
          if (generation.current !== token || owner.current !== view) return
          setLoading(false); setMsg({ err: String(e?.message || e) })
        })
        return () => { generation.current++; controller.abort() }
      }, [eng, refreshKey, reloadKey])

      React.useEffect(() => {
        const r = roles.find((x) => x.role === active)
        if (ready && r) setDraft(r.content || '')
      }, [active, roles, ready])

      const save = () => {
        if (!eng || !ready || !active || owner.current !== view || writing.current || editVersion !== editEpoch.current) return
        const token = generation.current, role = active, content = draft
        const valid = () => token === generation.current && owner.current === view
        writing.current = true; setBusy(true); setMsg(null)
        // Writes are never replayed; changing views only discards their UI result.
        api({ op: 'savePrompt', engagement: eng, role, content }).then((r) => {
          if (!valid()) return
          writing.current = false; setBusy(false)
          if (!r || r.ok === false) { setMsg({ err: r?.error || '保存失败' }); return }
          setRoles((list) => list.map((x) => (x.role === role
            ? Object.assign({}, x, { content, updated_at: new Date().toISOString() }) : x)))
          setMsg({ ok: '已保存' })
        }, (e) => { if (valid()) { writing.current = false; setBusy(false); setMsg({ err: String(e?.message || e) }) } })
      }

      const reset = (all) => {
        if (!eng || !ready || owner.current !== view || writing.current || editVersion !== editEpoch.current || (!all && !active)) return
        const token = generation.current, role = active, signal = reader.current?.signal
        const valid = () => token === generation.current && owner.current === view
        writing.current = true; setBusy(true); setMsg(null)
        let committed = false
        const invalidate = () => { setLoadedView(undefined); setRoles([]); setDraft('') }
        editEpoch.current++; invalidate()
        api({ op: 'resetPrompts', engagement: eng, role: all ? undefined : role }).then(async (r) => {
          if (!valid()) return
          if (!r || r.ok === false) throw new Error(r?.error || '恢复失败')
          committed = true; invalidate()
          const rr = await api({ op: 'prompts', engagement: eng }, { signal })
          if (!valid()) return
          if (!rr || rr.ok === false) throw new Error(rr?.error || '恢复后读取失败，请刷新核对')
          setLoadedView(view); setRoles(rr.roles || [])
          setMsg({ ok: '已恢复内置默认：' + (r.reset || []).join('、') })
        }).catch(e => { if (valid()) { invalidate(); setMsg({ err: (committed ? '恢复已提交，但角色稿读取未确认：' : '恢复结果尚未确认：') + String(e?.message || e) + '。请重新核对角色稿后再保存。' }) } })
          .finally(() => { if (valid()) { writing.current = false; setBusy(false) } })
      }

      const visibleRoles = ready ? roles : []
      const cur = visibleRoles.find((x) => x.role === active)
      const items = visibleRoles.map((r) => h('div', Object.assign({
        key: r.role, className: 'rt-item' + (active === r.role ? ' on' : ''),
      }, clickable(() => { if (!busy) { setActive(r.role); setMsg(null) } },
        { label: '查看「' + r.title + '」提示词', expanded: active === r.role })),
        h('div', { className: 'rt-item-name' }, r.title),
        h('div', { className: 'rt-item-desc' }, (r.content || '').replace(/[#*`]/g, '').slice(0, 60) || '（空）')))

      return h('div', { className: 'rt-split' },
        h('div', { className: 'rt-list' }, items),
        h('div', { className: 'rt-main' },
          h('div', { className: 'rt-toolbar' },
            h('span', { style: { fontWeight: 600 } }, cur ? cur.title : '提示词'),
            h('span', { className: 'rt-tag' }, '更新 ' + fmt(cur && cur.updated_at)),
            h('div', { className: 'rt-spacer' }),
            h('button', {
              className: 'rt-btn', disabled: busy || !ready || !eng || !active, title: '把当前角色恢复成内置最新版提示词',
              onClick: () => reset(false),
            }, '恢复默认为当前'),
            h('button', {
              className: 'rt-btn', disabled: busy || !ready || !eng, title: '四个角色全部恢复成内置最新版提示词',
              onClick: () => reset(true),
            }, '全部恢复默认'),
            h('button', { className: 'rt-btn rt-btn-primary', disabled: busy || !ready || !eng || !active, onClick: save }, busy ? '保存中…' : '保存')),
          !ready && !loading && eng ? h('button', { className: 'rt-btn', type: 'button', disabled: busy, onClick: () => { if (owner.current === view && !writing.current) setReloadKey(k => k + 1) } }, '重新核对角色稿') : null,
          loading ? h('div', { className: 'rt-foot', role: 'status' }, '正在读取当前项目角色稿…') : null,
          msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
          h('div', { className: 'rt-pane' },
            h('textarea', {
              className: 'rt-textarea', value: ready ? draft : '', spellCheck: false, disabled: busy || !ready || !eng,
              onChange: (e) => setDraft(e.target.value),
              placeholder: '该角色的系统提示词（Markdown）',
            }),
            h('div', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)', marginTop: 6 } },
              '保存后写入 agents/' + (active || 'role') + '.md。子会话任务第一行写 redteamRole: recon、assess、vuln-scan、exploit 或 internal 后，对应文件进入系统提示词。'))))
    }

    /* ---------------------------------------------------------- 技能库（DSH 原生） */
    function SkillsTab(props) {
      const refreshKey = props.refreshKey || 0
      const [items, setItems] = React.useState([])
      const [meta, setMeta] = React.useState({})
      const [err, setErr] = React.useState(null)
      const [q, setQ] = React.useState('')
      const [srcOnly, setSrcOnly] = React.useState(false)
      const [active, setActive] = React.useState(null)
      const [detail, setDetail] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [brokenOnly, setBrokenOnly] = React.useState(false)

      /* refresh=true 跳过后端 30 秒可用性缓存（技能正文/环境变量可能刚改过） */
      const load = (force) => {
        setBusy(true)
        api({ op: 'skillCatalog', refresh: force === true }).then((r) => {
          setBusy(false)
          if (!r || r.ok === false) { setErr((r && r.error) || '读取失败'); return }
          setErr(null)
          setMeta(r || {})
          setItems(r.items || [])
        }, (e) => { setBusy(false); setErr(String((e && e.message) || e)) })
      }
      React.useEffect(load, [refreshKey])

      const open = (skill) => {
        const name = skill && skill.name
        const key = (skill && skill.library ? skill.library : 'redteam') + ':' + name
        if (active === key) { setActive(null); setDetail(null); return }
        setActive(key)
        setDetail(null)
        api({ op: 'skillRead', name: name, library: skill.library || 'redteam' }).then((r) => {
          if (r && r.ok) setDetail(r)
          else setErr((r && r.error) || '读取失败')
        }, (e) => setErr(String((e && e.message) || e)))
      }

      const needle = q.trim().toLowerCase()
      let filtered = needle
        ? items.filter((s) => (s.name + ' ' + s.description + ' ' + s.whenToUse).toLowerCase().indexOf(needle) >= 0)
        : items
      if (srcOnly) filtered = filtered.filter((s) => s.library !== 'official' && s.fromPlugin === true)
      if (brokenOnly) filtered = filtered.filter((s) => s.library !== 'official' && (s.availability === 'broken' || s.availability === 'unknown'))
      /* 目录聚合：一眼看出"这么多技能是哪来的"（本项目/别的插件/自带根…） */
      const dirs = (meta.byDir || []).filter((d) => d.n > 0).slice(0, 6)
      const availSummary = meta.availability ? meta.availability.summary : null
      const needRestart = err !== null && String(err).indexOf('unknown op') >= 0

      const renderSkill = (s) => h('div', Object.assign({
        key: (s.library || 'redteam') + ':' + s.name, className: 'rt-item' + (active === ((s.library || 'redteam') + ':' + s.name) ? ' on' : ''),
      }, clickable(() => open(s), { label: '查看技能 ' + s.name, expanded: active === ((s.library || 'redteam') + ':' + s.name) })),
        h('div', { className: 'rt-item-name' }, s.name,
          s.modelInvocable === false ? h('span', { className: 'rt-tag', style: { marginLeft: 6 } }, '仅人工') : null,
          s.library === 'official'
            ? h('span', { className: 'rt-tag', style: { marginLeft: 6 }, title: '官方技能目录，不按红队工具路径检查' }, '官方')
            : h('span', {
              className: 'rt-avail rt-avail-' + (s.availability || 'unknown'),
              style: { marginLeft: 6 },
              title: (s.availability === 'available'
                ? '可用：技能正文可以加载。缺的外部工具或密钥记在详情里，不阻止调用。'
                : (s.problems || []).join('\n') || '未知'),
            }, s.availability === 'available' ? '可用' : s.availability === 'broken' ? '不可用' : '未知'),
        h('div', { className: 'rt-item-desc' }, s.description || '（无描述）'),
        h('div', { className: 'rt-kb-sub' },
          [s.source ? '来源 ' + s.source : null,
            s.fromPlugin ? '本插件自带' : null,
            s.provider ? s.provider : null,
            s.dir ? s.dir : null].filter(Boolean).join(' · ')),
        (s.problems || []).length > 0 && s.availability !== 'available' && s.library !== 'official'
          ? h('div', { className: 'rt-kb-sub', style: { color: 'var(--dsw-alias-state-warn-primary, #f59e0b)' } },
              '⚠ ' + String(s.problems[0]).slice(0, 60))
          : null))
      const redteamRows = filtered.filter((s) => s.library !== 'official').map(renderSkill)
      const officialRows = filtered.filter((s) => s.library === 'official').map(renderSkill)
      const listItems = []
      if (redteamRows.length > 0) {
        listItems.push(h('div', { key: 'head-redteam', className: 'rt-kb-sub', style: { margin: '8px 0 4px', fontWeight: 600 } }, '红队技能'))
        listItems.push.apply(listItems, redteamRows)
      }
      if (officialRows.length > 0) {
        listItems.push(h('div', { key: 'head-official', className: 'rt-kb-sub', style: { margin: '8px 0 4px', fontWeight: 600 } }, '官方技能'))
        listItems.push.apply(listItems, officialRows)
      }

      return h('div', { className: 'rt-split' },
        h('div', { className: 'rt-list' },
          h('input', {
            className: 'rt-input', style: { width: '100%', marginBottom: 8, boxSizing: 'border-box' },
            placeholder: '过滤技能', value: q, onChange: (e) => setQ(e.target.value),
          }),
          h('label', { className: 'rt-kb-check', style: { display: 'flex', margin: '0 0 6px' } },
            h('input', { type: 'checkbox', checked: srcOnly, onChange: (e) => setSrcOnly(e.target.checked) }),
            '只看本插件自带（' + (meta.fromPlugin || 0) + ' 个）'),
          availSummary && (availSummary.broken > 0 || availSummary.unknown > 0)
            ? h('label', {
                className: 'rt-kb-check', style: { display: 'flex', margin: '0 0 8px' },
                title: '只看有明确缺口（缺 key / 缺本机路径 / 基础设施还是占位符）或判不了可用性的技能',
              },
                h('input', { type: 'checkbox', checked: brokenOnly, onChange: (e) => setBrokenOnly(e.target.checked) }),
                '只看不可用/未知（' + ((availSummary.broken || 0) + (availSummary.unknown || 0)) + ' 个）')
            : null,
          availSummary
            ? h('div', { style: { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 } },
                h('span', { className: 'rt-avail rt-avail-available' }, '可用 ' + (availSummary.available || 0)),
                availSummary.broken > 0 ? h('span', { className: 'rt-avail rt-avail-broken' }, '不可用 ' + availSummary.broken) : null,
                availSummary.unknown > 0 ? h('span', { className: 'rt-avail rt-avail-unknown' }, '未知 ' + availSummary.unknown) : null,
                h('span', Object.assign({
                  className: 'rt-tag', style: { cursor: 'pointer' },
                  title: '技能正文或环境变量刚改过？点这里跳过 30 秒缓存重查',
                }, clickable(() => load(true), { label: '重新检查技能可用性' })), '重查可用性'))
            : null,
          h('div', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)', marginBottom: 6 } },
            '红队 ' + ((meta.libraries && meta.libraries.redteam) || 0) + ' · 官方 ' + ((meta.libraries && meta.libraries.official) || 0),
            items.length > 100 ? h('div', { style: { marginTop: 3 } },
              '（技能多来自其它插件注册的根或你自己的技能目录；本插件只自带 ' + (meta.fromPlugin || 0) + ' 个）') : null),
          listItems),
        h('div', { className: 'rt-main' },
          h('div', { className: 'rt-toolbar' },
            h('span', { style: { fontWeight: 600 } }, detail ? detail.name : '技能目录（DSH 原生）'),
            h('div', { className: 'rt-spacer' }),
            h('button', { className: 'rt-btn', disabled: busy, onClick: () => load(true) }, busy ? '刷新中…' : '刷新')),
          err
            ? (needRestart
                ? h('div', { className: 'rt-empty' }, '该模块的宿主代码已更新，需重启一次当前宿主（官方 exe / 社区版 / dsh web）后生效')
                : h('div', { className: 'rt-err' }, err))
            : null,
          detail
            ? h('div', { className: 'rt-pane' },
                h('div', { className: 'rt-kv' }, h('b', null, '描述'), h('span', null, detail.description || '—')),
                h('div', { className: 'rt-kv' }, h('b', null, '何时使用'), h('span', null, detail.whenToUse || '—')),
                h('div', { className: 'rt-kv' }, h('b', null, '来源'), h('span', null, (detail.provider || '—') + ' / ' + (detail.source || '—'))),
                (() => {
                  const s2 = items.find((x) => ((x.library || 'redteam') + ':' + x.name) === active)
                  if (!s2) return null
                  if (s2.library === 'official') {
                    return h('div', { className: 'rt-kv' }, h('b', null, '类型'), h('span', null, '官方技能。由宿主按任务调用，不按红队工具路径检查。'))
                  }
                  const avail = s2.availability || 'unknown'
                  return h('div', null,
                    h('div', { className: 'rt-kv' }, h('b', null, '可用性'),
                      h('span', { className: 'rt-avail rt-avail-' + avail },
                        avail === 'available' ? '可用' : avail === 'broken' ? '不可用（有明确缺口）' : '未知（正文读不到）')),
                    (s2.problems || []).length > 0
                      ? h('div', { className: 'rt-kv' }, h('b', null, avail === 'available' ? '未装上的外部工具' : '缺口'),
                          h('span', null, s2.problems.map((x, i) => h('div', { key: 'p' + i }, '· ' + x))))
                      : null,
                    (s2.needs_user || []).length > 0
                      ? h('div', { className: 'rt-kv' }, h('b', null, '需要你提供'),
                          h('span', { style: { color: 'var(--dsw-alias-state-warn-primary, #f59e0b)' } },
                            s2.needs_user.map((x, i) => h('div', { key: 'n' + i }, '· ' + x))))
                      : null)
                })(),
                detail.path ? h('div', { className: 'rt-kv' }, h('b', null, '文件'), h('span', { className: 'rt-mono', style: { wordBreak: 'break-all' } }, detail.path)) : null,
                h('pre', { className: 'rt-md', style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 6, maxHeight: '52vh' } }, detail.content || '（空）'))
            : h('div', { className: 'rt-pane' },
                h('div', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)', marginBottom: 8 } },
                  meta.note || '技能由 DSH 原生 skill 体系管理，红队智能体通过 skill 工具调用。'),
                availSummary
                  ? h('div', { style: { fontSize: 12, marginBottom: 8, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } },
                      h('span', { className: 'rt-avail rt-avail-available' }, '可用 ' + (availSummary.available || 0)),
                      availSummary.broken > 0 ? h('span', { className: 'rt-avail rt-avail-broken' }, '不可用 ' + availSummary.broken) : null,
                      availSummary.unknown > 0 ? h('span', { className: 'rt-avail rt-avail-unknown' }, '未知 ' + availSummary.unknown) : null,
                      h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } },
                        '（' + (meta.availability && meta.availability.cached ? '缓存于 ' : '检查于 ')
                        + (meta.availability && meta.availability.checked_at ? fmt(meta.availability.checked_at) : '—') + '）'))
                  : null,
                meta.availability && (meta.availability.broken || []).length > 0
                  ? h('div', { className: 'rt-hint' },
                      h('div', { style: { fontWeight: 600, marginBottom: 4 } }, '现在跑不起来的技能：'),
                      meta.availability.broken.slice(0, 12).map((b) => h('div', { key: b.name },
                        '· ' + b.name + (b.problems && b.problems.length ? ' — ' + b.problems[0] : ''))))
                  : null,
                (meta.byDir || []).slice(0, 6).map((d) => h('div', { key: d.key, className: 'rt-mono', style: { fontSize: 11, marginBottom: 2, overflowWrap: 'anywhere' } },
                  d.n + ' 个 · ' + d.key)),
                (meta.byDir || []).length > 6
                  ? h('div', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } },
                      '…另有 ' + ((meta.byDir || []).length - 6) + ' 个目录（共 ' + items.length + ' 个技能）')
                  : null,
                h('div', { className: 'rt-empty' }, '左侧选择技能查看内容')))
      )
    }

    /* ---------------------------------------------------------- 漏洞战果 */
    const SEV_LABEL = { critical: '严重', high: '高危', medium: '中危', low: '低危', info: '信息' }
    const STATUS_LABEL = { candidate: '待验证', confirmed: '已确认', 'false-positive': '误报', exploited: '已利用', fixed: '已修复' }
    const sevClass = (s) => 'rt-sev rt-sev-' + (SEV_LABEL[s] ? s : 'info')


    /** 目标归并：按「scheme://host:port」聚合，避免带路径的 URL 把分组打散。 */
    function targetKeyOf(v) {
      const t = String(v.target || '').trim()
      if (t !== '') {
        const url = /^([a-z][a-z0-9+.-]*:\/\/[^/?#\s]+)/i.exec(t)
        if (url) return url[1]
        const head = /^([^\s/?#]+)/.exec(t)
        if (head) return head[1]
        return t
      }
      return v.asset_ip || '(未指定目标)'
    }

    /* ---------------------------------------------------------- 证据渲染 */
    /** 把一段原始 HTTP 报文按「请求行/状态行 + 头 + 体」着色，便于人眼扫读。 */
    function HttpBlock(props) {
      const text = String(props.text || '')
      if (!text) return null
      const lines = text.split(/\r?\n/)
      const nodes = lines.map((ln, i) => {
        let cls = null
        if (i === 0 && /^(GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH|TRACE)\s/.test(ln)) cls = 'rt-hl-req'
        else if (i === 0 && /^HTTP\//.test(ln)) cls = 'rt-hl-res'
        else if (/^[A-Za-z0-9-]+:/.test(ln)) {
          const name = ln.split(':')[0].toLowerCase()
          if (name === 'host' || name === 'cookie' || name === 'authorization' || name === 'content-type') cls = 'rt-hl-req'
        }
        return h('div', { key: 'l' + i, className: cls || undefined }, ln === '' ? '\u00a0' : ln)
      })
      return h('pre', { className: 'rt-evi-body' + (props.compact ? ' req' : '') }, nodes)
    }

    /** 漏洞详情里的证据区：结构化证据文本 + 该漏洞的原始 HTTP 请求/响应记录。 */
    function detailEvidence(v) {
      const evi = String(v.evidence || '').trim()
      const looksHttp = /^(GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH|HTTP\/)/m.test(evi) || /\n[A-Za-z-]+: /.test(evi)
      const blocks = []
      if (evi) {
        blocks.push(h('div', { key: 'ev', className: 'rt-evi' },
          h('div', { className: 'rt-evi-head' }, '证据摘要',
            h('span', { className: 'rt-tag' }, looksHttp ? '原始报文' : '文本'),
            h('div', { className: 'rt-spacer' }),
            h('button', {
              className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
              onClick: (e) => { e.stopPropagation(); copyText(evi) },
            }, '复制')),
          looksHttp ? h(HttpBlock, { text: evi }) : h('pre', { className: 'rt-evi-body' }, evi)))
      }
      const http = v.http_evidence || []
      for (const e of http) {
        blocks.push(h('div', { key: 'h' + e.id, className: 'rt-evi' },
          h('div', { className: 'rt-evi-head' },
            e.label || 'HTTP 证据',
            h('span', { className: 'rt-tag' }, (e.method || '') + ' ' + (e.status === null || e.status === undefined ? '' : e.status)),
            h('div', { className: 'rt-spacer' }),
            h('span', { style: { fontWeight: 400, color: 'var(--dsw-alias-label-secondary)' } }, fmt(e.captured_at || e.created_at))),
          e.request ? h('div', null,
            h('div', { className: 'rt-evi-head', style: { borderTop: 'none' } }, '▸ 请求（可直接粘进 Burp Repeater）'),
            h(HttpBlock, { text: e.request, compact: true })) : null,
          e.response ? h('div', null,
            h('div', { className: 'rt-evi-head' }, '▸ 响应'),
            h(HttpBlock, { text: e.response })) : null,
          e.note ? h('pre', { className: 'rt-evi-body', style: { maxHeight: 80 } }, e.note) : null))
      }
      if (blocks.length === 0) {
        blocks.push(h('div', { key: 'none', className: 'rt-kv' }, h('b', null, '证据'),
          h('span', { style: { color: 'var(--dsw-alias-state-error-primary)' } }, '缺失 —— 未验证/无证据的漏洞不计入报告，请补 redteam_http_evidence_add')))
      }
      return h('div', { key: 'eviwrap' }, blocks)
    }

    function FindingsTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [sev, setSev] = React.useState('')
      const [status, setStatus] = React.useState('')
      const [q, setQ] = React.useState('')
      const [qApplied, setQApplied] = React.useState('')
      const [state, setState] = React.useState({ loading: false, error: null, total: 0, items: [], stats: null })
      const [creds, setCreds] = React.useState([])
      const [accesses, setAccesses] = React.useState([])
      const [files, setFiles] = React.useState([])
      const [openId, setOpenId] = React.useState(null)
      const [msg, setMsg] = React.useState(null)
      /* 子页签：漏洞 / 凭据 / 访问会话（凭据不再铺在漏洞页底部） */
      const [subTab, setSubTab] = React.useState('vulns')
      /* 默认按目标聚合：322 条平铺没法读，先看"哪台被打下什么" */
      const [grouped, setGrouped] = React.useState(true)
      const collapse = useCollapse('findings:' + eng)
      const generation = React.useRef(0)
      const requests = React.useRef(null)
      const currentEng = React.useRef(eng)
      currentEng.current = eng
      const [secrets, setSecrets] = React.useState({})
      const [page, setPage] = React.useState({ key: null, offset: 0 })
      const filterKey = JSON.stringify([eng, sev, status, qApplied])
      const offset = page.key === filterKey ? page.offset : 0
      const pageSize = 200

      const load = () => {
        if (!eng || currentEng.current !== eng) return
        requests.current?.abort()
        const controller = new AbortController()
        requests.current = controller
        const my = ++generation.current
        const active = () => my === generation.current && currentEng.current === eng
        const opts = { signal: controller.signal }
        setState({ loading: true, error: null, total: 0, items: [], stats: null })
        setCreds([]); setAccesses([]); setFiles([]); setSecrets({}); setMsg(null)
        api({
          op: 'vulns', engagement: eng, severity: sev || undefined,
          status: status || undefined, q: qApplied || undefined, limit: pageSize, offset: offset,
        }, opts).then((r) => {
          if (!active()) return
          if (!r || r.ok === false) {
            setState({ loading: false, error: (r && r.error) || '查询失败', total: 0, items: [], stats: null })
            return
          }
          setState({ loading: false, error: null, total: r.total, items: r.items || [], stats: r.stats || null })
        }, (e) => {
          if (active()) setState({ loading: false, error: String((e && e.message) || e), total: 0, items: [], stats: null })
        })
        const auxiliary = (op, setter) => api({ op, engagement: eng }, opts).then((r) => {
          if (!active()) return
          if (!r || r.ok === false) throw new Error((r && r.error) || '查询失败')
          setter(r.items || [])
        }).catch((e) => {
          if (active()) setMsg({ err: '部分资料未加载：' + String(e?.message || e) })
        })
        auxiliary('credentials', setCreds)
        auxiliary('access', setAccesses)
        auxiliary('attackFiles', setFiles)
        return () => {
          if (my === generation.current) generation.current++
          controller.abort()
        }
      }
      React.useEffect(load, [eng, sev, status, qApplied, refreshKey, offset])

      const revealCredential = async (credential, copyOnly) => {
        const my = generation.current
        const active = () => currentEng.current === eng && generation.current === my
        if (!active()) return
        setMsg(null)
        try {
          const r = await api({ op: 'credentialReveal', engagement: eng, id: credential.id }, { signal: requests.current?.signal })
          if (!active()) return
          if (!r || r.ok === false || typeof r.item?.secret_value !== 'string') throw new Error((r && r.error) || '无法读取这条凭据')
          if (copyOnly) {
            await copyWithFeedback(r.item.secret_value, '所选凭据', (ok, message) => {
              if (active()) setMsg(ok ? { ok: message } : { err: message })
            })
          } else setSecrets((previous) => ({ engagement: eng, values: Object.assign({}, previous.engagement === eng ? previous.values : {}, { [credential.id]: r.item.secret_value }) }))
        } catch (e) {
          if (active()) setMsg({ err: String(e?.message || e) })
        }
      }

      const setVulnStatus = (id, next) => {
        const my = generation.current
        setMsg(null)
        api({ op: 'updateVuln', engagement: eng, id: id, patch: { status: next } }).then((r) => {
          if (currentEng.current !== eng || generation.current !== my) return
          if (!r || r.ok === false) { setMsg({ err: (r && r.error) || '更新失败' }); return }
          setMsg({ ok: '已更新为「' + (STATUS_LABEL[next] || next) + '」' })
          load()
        }, (e) => {
          if (currentEng.current === eng && generation.current === my) setMsg({ err: String((e && e.message) || e) })
        })
      }

      const stats = (state.stats && state.stats.bySeverity) ? state.stats : { bySeverity: {}, byStatus: {} }
      const needRestart = state.error !== null && String(state.error).indexOf('unknown op') >= 0

      const allFiles = (files || []).flatMap((g) => (g.files || []).map((f) => Object.assign({ target: g.target }, f)))
      const filesByVuln = new Map()
      const orphanFiles = []
      for (const f of allFiles) {
        const vid = f.vuln_id === null || f.vuln_id === undefined ? null : Number(f.vuln_id)
        if (vid === null) { orphanFiles.push(f); continue }
        if (!filesByVuln.has(vid)) filesByVuln.set(vid, [])
        filesByVuln.get(vid).push(f)
      }

      /* ── 结论行：只给结论，数字点一下就是筛选 ─────────────────────── */
      const concl = (key, label, value, active, onClick) => h('span', Object.assign({
        key: key, className: 'rt-concl-i' + (active ? ' on' : ''), title: '点击筛选 / 再点取消',
      }, clickable(onClick, { label: '按「' + label + '」筛选（' + (value || 0) + '）', expanded: active })),
        h('b', null, String(value || 0)), h('span', null, label))
      const conclusion = h('div', { className: 'rt-concl' },
        concl('conf', '已确认', (stats.byStatus.confirmed || 0), status === 'confirmed', () => setStatus((v) => (v === 'confirmed' ? '' : 'confirmed'))),
        concl('exp', '已利用', (stats.byStatus.exploited || 0), status === 'exploited', () => setStatus((v) => (v === 'exploited' ? '' : 'exploited'))),
        concl('crit', '严重', (stats.bySeverity.critical || 0), sev === 'critical', () => setSev((v) => (v === 'critical' ? '' : 'critical'))),
        concl('high', '高危', (stats.bySeverity.high || 0), sev === 'high', () => setSev((v) => (v === 'high' ? '' : 'high'))),
        concl('med', '中危', (stats.bySeverity.medium || 0), sev === 'medium', () => setSev((v) => (v === 'medium' ? '' : 'medium'))),
        concl('gain', '拿到权限', (stats.withGained || 0), false, () => {}),
        h('div', { className: 'rt-spacer' }),
        h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } },
          '默认按目标聚合 · 共 ' + (stats.targetGroups || 0) + ' 个目标'))

      const head = h('div', { className: 'rt-vrow head' },
        h('span', null, '等级'), h('span', null, '漏洞 / 编号'), h('span', null, '目标'),
        h('span', null, '拿到什么'), h('span', null, '状态'), h('span', null, '置信'))

      /* 单条漏洞（行 + 展开详情），聚合视图与平铺视图共用 */
      const vulnRows = (v, compact) => {
        const out = []
        const gainedList = String(v.gained || '').split(/[、,;，；]/).map((x) => x.trim()).filter(Boolean)
        const open = openId === v.id
        out.push(h('div', {
          key: 'v' + v.id, className: 'rt-vrow', role: 'button', tabIndex: 0,
          style: compact ? { cursor: 'pointer', gridTemplateColumns: '58px minmax(0,1fr) 104px 68px' } : { cursor: 'pointer' },
          onClick: () => setOpenId(open ? null : v.id),
          onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenId(open ? null : v.id) } },
        },
          h('span', null, h('span', { className: sevClass(v.severity) }, SEV_LABEL[v.severity] || v.severity)),
          h('span', { title: v.title || '' }, h('span', { className: 'rt-sec-caret' }, open ? '▾' : '▸'), (v.cve ? v.cve + ' ' : '') + (v.title || '')),
          compact ? null : h('span', { className: 'rt-mono', title: v.target || '' }, v.target || v.asset_ip || '—'),
          h('span', { title: v.gained || '' },
            gainedList.length
              ? h('span', { className: 'rt-gain', style: { maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' } }, gainedList[0] + (gainedList.length > 1 ? ' +' + (gainedList.length - 1) : ''))
              : h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } }, '—')),
          h('span', null, h('span', { className: 'rt-tag' }, STATUS_LABEL[v.status] || v.status)),
          compact ? null : h('span', null, v.confidence === null || v.confidence === undefined ? '—' : Math.round(v.confidence * 100) + '%')))
        if (openId !== v.id) return out
        out.push(h('div', {
          key: 'vd' + v.id, className: 'rt-vrow',
          style: { cursor: 'default', gridTemplateColumns: '1fr' },
        }, h('div', { className: 'rt-vdetail' },
          h('div', { className: 'rt-kv' }, h('b', null, '拿到什么'),
            gainedList.length
              ? h('span', null, gainedList.map((g, gi) => h('span', { key: 'g' + gi, className: 'rt-gain', style: { marginRight: 6 } }, g)))
              : h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } },
                  '未记录 —— 拿到权限/成果后请用 redteam_vuln_update 补 gained（例：服务器权限、内网隧道、后台管理员账号）')),
          h('div', { className: 'rt-kv' }, h('b', null, '目标'), h('span', { className: 'rt-mono', style: { wordBreak: 'break-all' } }, v.target || '—')),
          h('div', { className: 'rt-kv' }, h('b', null, '资产'), h('span', null, (v.asset_ip || '—') + ' · ' + (v.segment_cidr || ''))),
          h('div', { className: 'rt-kv' }, h('b', null, '来源'), h('span', null, (v.source || '—') + ' · ' + (v.found_by_agent || '—') + ' · ' + fmt(v.found_at))),
          detailEvidence(v),
          (() => {
            const mine = filesByVuln.get(Number(v.id)) || []
            return h('div', { className: 'rt-kv' }, h('b', null, '攻击文件'),
              mine.length
                ? h('span', null, mine.map((f, fi) => h('div', { key: 'af' + fi, style: { marginBottom: 3 } },
                    '· ' + (f.kind ? '[' + f.kind + '] ' : '') + (f.name || '(未命名)')
                    + (f.description ? ' — ' + f.description : ''),
                    h('div', { className: 'rt-mono', style: { fontSize: 11, marginLeft: 12, color: 'var(--dsw-alias-label-secondary)', overflowWrap: 'anywhere' } }, f.path || ''))))
                : h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } },
                    '（无）用 redteam_attack_file_add 把这条漏洞打通的脚本/马/EXP 归档，并带上 vuln_id'))
          })(),
          h('div', { className: 'rt-actions' },
            h('button', { className: 'rt-btn', onClick: (e) => { e.stopPropagation(); setVulnStatus(v.id, 'confirmed') } }, '确认'),
            h('button', { className: 'rt-btn', onClick: (e) => { e.stopPropagation(); setVulnStatus(v.id, 'exploited') } }, '已利用'),
            h('button', { className: 'rt-btn', onClick: (e) => { e.stopPropagation(); setVulnStatus(v.id, 'false-positive') } }, '误报'),
            h('button', { className: 'rt-btn', onClick: (e) => { e.stopPropagation(); setVulnStatus(v.id, 'fixed') } }, '已修复')))))
        return out
      }

      const rows = []
      if (grouped) {
        /* 按目标聚合成组：先看"哪台被打下什么"，再点进去看具体漏洞 */
        const groups = new Map()
        for (const v of state.items) {
          const key = targetKeyOf(v)
          if (!groups.has(key)) groups.set(key, [])
          groups.get(key).push(v)
        }
        const SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3, info: 4 }
        const list = Array.from(groups.entries()).map(([key, vs]) => ({
          key,
          vulns: vs,
          top: vs.slice().sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9))[0],
          gained: Array.from(new Set(vs.flatMap((v) => String(v.gained || '').split(/[、,;，；]/).map((x) => x.trim()).filter(Boolean)))),
          exploited: vs.filter((v) => v.status === 'exploited').length,
        })).sort((a, b) => (SEV_RANK[a.top.severity] ?? 9) - (SEV_RANK[b.top.severity] ?? 9) || b.vulns.length - a.vulns.length)
        for (const g of list) {
          const key = 'target:' + g.key
          const defOpen = false
          rows.push(h(Section, {
            key: 'sec:' + g.key, tone: 'target',
            title: g.key,
            count: g.vulns.length + ' 个漏洞',
            sub: [
              SEV_LABEL[g.top.severity] || g.top.severity,
              g.exploited ? '已利用 ' + g.exploited : null,
              g.top.asset_ip && g.top.asset_ip !== g.key ? '资产 ' + g.top.asset_ip : null,
            ].filter(Boolean).join(' · '),
            right: g.gained.length
              ? g.gained.slice(0, 2).join(' / ') + (g.gained.length > 2 ? ' +' + (g.gained.length - 2) : '')
              : '未记录权限',
            open: collapse.isOpen(key, defOpen),
            onToggle: collapse.toggle(key, defOpen),
          }, g.vulns.map((v) => vulnRows(v, true))))
        }
        if (!list.length && !state.loading && !state.error) {
          rows.push(h('div', { key: 'none', className: 'rt-empty' }, '暂无漏洞记录'))
        }
      } else {
        for (const v of state.items) rows.push(...vulnRows(v))
      }

      const toolbar = h('div', { className: 'rt-toolbar' },
        h('input', {
          className: 'rt-input', style: { flex: '1 1 140px' }, placeholder: '搜索标题 / CVE / 目标（回车）',
          value: q, onChange: (e) => setQ(e.target.value),
          onKeyDown: (e) => { if (e.key === 'Enter') setQApplied(q) },
        }),
        h('button', { className: 'rt-btn', onClick: () => setQApplied(q) }, '搜索'),
        h('select', { className: 'rt-input', value: sev, onChange: (e) => setSev(e.target.value) },
          h('option', { value: '' }, '全部等级'),
          h('option', { value: 'critical' }, '严重'),
          h('option', { value: 'high' }, '高危'),
          h('option', { value: 'medium' }, '中危'),
          h('option', { value: 'low' }, '低危'),
          h('option', { value: 'info' }, '信息')),
        h('select', { className: 'rt-input', value: status, onChange: (e) => setStatus(e.target.value) },
          h('option', { value: '' }, '全部状态'),
          h('option', { value: 'candidate' }, '待验证'),
          h('option', { value: 'confirmed' }, '已确认'),
          h('option', { value: 'exploited' }, '已利用'),
          h('option', { value: 'false-positive' }, '误报'),
          h('option', { value: 'fixed' }, '已修复')))

      const visibleSecret = (credential) => secrets.engagement === eng ? secrets.values?.[credential.id] : undefined
      const hasSecret = (credential) => credential.has_secret === true || Boolean(credential.secret_masked || credential.secret_value)
      const hideCredential = (credential) => setSecrets((previous) => {
        const values = Object.assign({}, previous.engagement === eng ? previous.values : {})
        delete values[credential.id]
        return { engagement: eng, values }
      })
      const credSection = h('div', null,
        h('div', { className: 'rt-section' }, '凭据 · ' + creds.length + (creds.length ? '（默认隐藏，按需显示或复制单条）' : '')),
        creds.length
          ? h('div', { style: { padding: '4px 10px 0' } }, creds.map((c) => h('div', { key: 'c' + c.id, className: 'rt-cred' },
              h('div', { className: 'rt-cred-head' },
                h('span', { className: 'rt-cred-host' }, c.host),
                c.username ? h('span', { className: 'rt-tag' }, c.username) : null,
                h('span', { className: 'rt-tag rt-tag-passive' }, c.secret_type || 'password'),
                c.privilege ? h('span', { className: 'rt-tag rt-tag-active' }, c.privilege) : null,
                h('div', { className: 'rt-spacer' }),
                h('button', {
                  className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 }, disabled: !hasSecret(c),
                  onClick: (e) => { e.stopPropagation(); visibleSecret(c) !== undefined ? hideCredential(c) : revealCredential(c, false) },
                }, visibleSecret(c) !== undefined ? '隐藏' : '显示'),
                h('button', {
                  className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 }, disabled: !hasSecret(c),
                  onClick: (e) => { e.stopPropagation(); revealCredential(c, true) },
                }, '复制')),
              visibleSecret(c) !== undefined
                ? h('div', { className: 'rt-secret', title: '仅在本页临时显示' }, visibleSecret(c))
                : h('div', { className: 'rt-secret-none' }, hasSecret(c) ? '••••••••' : '未保存凭据值'),
              h('div', { className: 'rt-cred-meta' },
                [c.source ? '来源 ' + c.source : null,
                  c.tool ? '工具 ' + c.tool : null,
                  c.secret_ref ? '证据 ' + c.secret_ref : null,
                  c.found_by_agent ? 'by ' + c.found_by_agent : null,
                  c.found_at ? fmt(c.found_at) : null].filter(Boolean).join(' · ')),
              c.note ? h('div', { className: 'rt-cred-meta' }, '备注：' + c.note) : null)))
          : h('div', { className: 'rt-empty' }, '暂无凭据（拿到口令/密钥/Hash 后用 redteam_credential_add 落库，秒级可复用）'))

      const accessSection = h('div', null,
        h('div', { className: 'rt-section' }, '已获得访问会话 · ' + accesses.length),
        accesses.length
          ? accesses.map((a) => h('div', { key: 'a' + a.id, className: 'rt-vrow', style: { cursor: 'default', gridTemplateColumns: '1fr 110px 80px 80px 1fr' } },
              h('span', { className: 'rt-mono' }, a.host),
              h('span', null, a.username || '—'),
              h('span', null, h('span', { className: 'rt-tag rt-tag-active' }, a.method || '—')),
              h('span', null, a.privilege || '—'),
              h('span', { className: 'rt-mono', title: a.session_ref || '' }, a.session_ref || '—')))
          : h('div', { className: 'rt-empty' }, '暂无'))

      const subTabBtn = (key, label, n) => h('span', Object.assign({
        className: 'rt-subtab' + (subTab === key ? ' on' : ''),
      }, clickable(() => setSubTab(key), { label: label + '（' + n + '）', expanded: subTab === key })),
      label + ' ' + n)

      const pagination = subTab === 'vulns' ? h('div', { className: 'rt-toolbar', 'aria-label': '漏洞分页' },
        h('button', { className: 'rt-btn', disabled: state.loading || offset === 0, onClick: () => setPage({ key: filterKey, offset: Math.max(0, offset - pageSize) }) }, '上一页'),
        h('span', { role: 'status' }, state.loading ? '加载中…' : '第 ' + (state.total ? offset + 1 : 0) + '–' + (offset + state.items.length) + ' 条，共 ' + state.total + ' 条'),
        h('button', { className: 'rt-btn', disabled: state.loading || offset + state.items.length >= state.total, onClick: () => setPage({ key: filterKey, offset: offset + pageSize }) }, '下一页'),
        h('button', { className: 'rt-btn', disabled: state.loading, onClick: load }, '刷新')) : null
      return h('div', { className: 'rt-main' }, toolbar, conclusion, pagination,
        h('div', { className: 'rt-subtabs' },
          subTabBtn('vulns', '漏洞', state.total || 0),
          subTabBtn('files', '攻击文件', allFiles.length),
          subTabBtn('creds', '凭据', creds.length),
          subTabBtn('access', '访问会话', accesses.length),
          h('div', { className: 'rt-spacer' }),
          grouped ? h('button', {
            className: 'rt-btn', title: '展开所有目标',
            onClick: () => collapse.setAll((state.items || []).map((v) => 'target:' + targetKeyOf(v)), true),
          }, '全部展开') : null,
          grouped ? h('button', {
            className: 'rt-btn', title: '收起所有目标',
            onClick: () => collapse.setAll((state.items || []).map((v) => 'target:' + targetKeyOf(v)), false),
          }, '全部收起') : null,
          h('button', {
            className: 'rt-btn' + (grouped ? ' rt-btn-primary' : ''),
            title: grouped ? '当前：按目标聚合（先看哪台被打下什么）' : '当前：平铺每条漏洞',
            onClick: () => setGrouped((g) => !g),
          }, grouped ? '按目标聚合' : '平铺列表')),
        msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        needRestart ? h('div', { className: 'rt-empty' }, '该模块的宿主代码已更新，需重启一次当前宿主（官方 exe / 社区版 / dsh web）后生效') : null,
        state.error && !needRestart ? h('div', { className: 'rt-err' }, state.error) : null,
        subTab === 'files'
          ? h('div', { className: 'rt-body', style: { overflow: 'auto' } },
              h('div', { className: 'rt-hint', style: { marginBottom: 8 } },
                '攻击文件按靶标目录组织（原「攻击文件」页签）；每条漏洞的关联文件也能在该漏洞详情里直接看到。'
                + (orphanFiles.length ? ' 目前有 ' + orphanFiles.length + ' 个文件没挂 vuln_id，建议补上以便与漏洞对应。' : '')),
              h(AttackFilesTab, { engagement: eng, refreshKey: refreshKey }))
          : subTab === 'creds'
          ? h('div', { className: 'rt-body', style: { overflow: 'auto' } }, credSection)
          : subTab === 'access'
            ? h('div', { className: 'rt-body', style: { overflow: 'auto' } }, accessSection)
            : h('div', { className: 'rt-table' }, grouped ? null : head, rows,
                !state.loading && !state.items.length && !state.error ? h('div', { className: 'rt-empty' }, '暂无漏洞记录') : null))
    }

    /* ---------------------------------------------------------- 攻击链 */
    const STAGE_LABEL = { recon: '信息收集', vuln: '漏洞发现', exploit: '漏洞利用', access: '获得权限', pivot: '内网突破', data: '敏感数据', other: '其他' }

    /* ---------------------------------------------------------- 攻击链（五阶段） */
    /**
     * 按攻击面位置串成一条链：
     * ① 信息收集 → ② 互联网资产权限 → ③ 边界突破 → ④ 内网资产权限 → ⑤ 靶标权限。
     * 每阶段只讲两件事：这一步拿到多少分（累计多少）、涉及的资产/隧道是哪些。
     * A = 竖向链（详细）；B = 横向链（一屏看完）。
     */
    function ChainTab(props) {
      const eng = props.engagement, refreshKey = props.refreshKey || 0
      const [snapshot, setData] = React.useState(null)
      const [error, setErr] = React.useState(null)
      const [loading, setLoading] = React.useState(false)
      const [view, setView] = React.useState('A')
      const [openId, setOpenId] = React.useState(null)
      const generation = React.useRef(0), reader = React.useRef(null), mounted = React.useRef(true)
      const owner = React.useRef({ eng, refreshKey })
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      const page = owner.current
      const data = snapshot?.page === page && snapshot.token === generation.current ? snapshot : null
      const err = error?.page === page ? error.text : null
      const load = () => {
        if (!eng || !mounted.current || owner.current !== page) return
        const next = ++generation.current, controller = new AbortController()
        reader.current?.abort(); reader.current = controller
        setLoading(true); setData(null); setErr(null); setOpenId(null)
        const owns = () => mounted.current && owner.current === page && generation.current === next
        api({ op: 'scoreChain', engagement: eng }, { signal: controller.signal }).then(r => {
          if (!owns()) return
          if (r?.ok !== true || !Array.isArray(r.stages) || !r.summary) { setErr({ page, text: '当前项目攻击链未确认，请刷新核对。' }); return }
          setData({ ...r, page, token: next })
        }, () => { if (owns()) setErr({ page, text: '当前项目攻击链未确认，请刷新核对。' }) })
          .finally(() => { if (owns()) setLoading(false) })
      }
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; reader.current?.abort() } }, [])
      React.useEffect(() => { load(); return () => { generation.current++; reader.current?.abort() } }, [eng, refreshKey])

      const stages = (data && data.stages) || []
      const summary = (data && data.summary) || null
      const toggle = (id) => setOpenId((cur) => (cur === id ? null : id))
      const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥']

      /* 单次得分的详情 */
      const hitDetail = (x) => h('div', { className: 'rt-flow-detail' },
        h('div', { className: 'rt-kv' }, h('b', null, '目标'), h('span', { className: 'rt-mono', style: { wordBreak: 'break-all' } }, x.target || '—')),
        x.asset_ip ? h('div', { className: 'rt-kv' }, h('b', null, '资产'), h('span', { className: 'rt-mono' }, x.asset_ip)) : null,
        x.vuln_title ? h('div', { className: 'rt-kv' }, h('b', null, '利用漏洞'), h('span', null, [x.vuln_cve, x.vuln_title].filter(Boolean).join(' '))) : null,
        h('div', { className: 'rt-kv' }, h('b', null, '次数'), h('span', null,
          '同类第 ' + x.nth_of_point + ' 次 · +' + (x.points || 0) + ' 分')),
        h('div', { className: 'rt-kv' }, h('b', null, '记录'), h('span', null, fmt(x.recorded_at) + (x.recorded_by ? ' · ' + x.recorded_by : ''))),
        x.evidence ? h(Clip, { label: '结果与证据', text: x.evidence }) : null)

      const hitRow = (x) => h('div', {
        key: 'h' + x.id,
        className: 'rt-ap-hit' + (openId === x.id ? ' open' : ''),
        role: 'button', tabIndex: 0,
        onClick: () => toggle(x.id),
        onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(x.id) } },
      },
        h('div', { className: 'rt-ap-hit-head' },
          h('span', { className: 'rt-ap-pts' + (x.counted ? '' : ' uncounted'), title: x.capped_reason || undefined },
            '+' + (x.counted ? (x.points || 0) : 0)),
          h('span', { className: 'rt-ap-hit-name' }, x.point_name),
          x.capped ? h('span', { className: 'rt-tag rt-tag-warn', title: x.capped_reason || '同一资产同一端口只算分值最高的一条' }, '服务已拿满 · 不计分') : null,
          x.nth_of_point > 1 ? h('span', { className: 'rt-ap-nth' }, '第 ' + x.nth_of_point + ' 次') : null,
          h('span', { className: 'rt-ap-hit-target' }, x.target || x.asset_ip || '—')),
        x.action
          ? h('div', { className: 'rt-ap-act' + (x.action_inferred ? ' inferred' : '') },
              '动作：' + (x.action.title || '（未命名步骤）') + (x.action_inferred ? '（推断）' : ''))
          : null,
        openId === x.id ? hitDetail(x) : null)

      /* 资产行（信息收集阶段 / 各阶段涉及资产） */
      const assetRow = (a) => h('div', { key: 'a' + a.id, className: 'rt-ap-asset' },
        h('span', { className: 'rt-scope rt-scope-' + (a.scope === 'internal' ? 'internal' : 'external') },
          a.scope === 'internal' ? '内' : '外'),
        h('span', { className: 'rt-mono', style: { fontWeight: 600 } }, a.ip),
        a.segment_cidr ? h('span', { className: 'rt-ap-nth' }, a.segment_cidr) : null,
        h('span', { className: 'rt-ap-nth' }, '端口 ' + (a.open_ports || 0)),
        a.vulns ? h('span', { className: 'rt-ap-nth' }, '漏洞 ' + a.vulns) : null,
        a.priority ? h('span', { className: 'rt-tag' }, '易打 ' + a.priority) : null,
        h('div', { className: 'rt-spacer' }),
        h('span', { className: 'rt-ap-pts' }, '+' + (a.points || 0) + ' 分'),
        h('span', { className: 'rt-ap-nth' }, (a.hits || 0) + ' 次'))

      /* 攻击链只讲"打到哪了、拿了多少分"：不展示打法要点与工具清单，
         那些是执行细节，混在链路里会淹没得分与资产信息。 */

      /* ── A：竖向攻击链 ─────────────────────────────────────────── */
      const stageA = (st, i) => {
        const isRecon = st.code === 'recon'
        const body = []
        if (isRecon) {
          body.push(h('div', { key: 'at', className: 'rt-ap-sub' }, '拿到分数的资产 · ' + st.assetCount + ' 台'))
          body.push(h('div', { key: 'al', className: 'rt-ap-assets' },
            st.assets.length ? st.assets.map(assetRow) : h('div', { className: 'rt-ap-none' }, '还没有产生得分的资产')))
        } else {
          body.push(h('div', { key: 'ht', className: 'rt-ap-sub' },
            '本阶段命中 ' + st.hits + ' 次' + (st.points ? ' · +' + st.points + ' 分' : '')))
          body.push(h('div', { key: 'hl', className: 'rt-ap-hits' },
            st.items.length ? st.items.map(hitRow) : h('div', { className: 'rt-ap-none' }, '本阶段还没有得分')))
          if (st.code === 'boundary') {
            const selfOnly = (st.tunnels_self_only || []).length
            body.push(h('div', { key: 'tt', className: 'rt-ap-sub' },
              '跨越靶标边界的通道 · ' + st.tunnels.length + ' 条' + (selfOnly ? '（另有 ' + selfOnly + ' 条只在自己 VPS/自建服务器上，不算突破）' : '')))
            if (selfOnly && st.tunnels.length === 0) {
              body.push(h('div', { key: 'tw', className: 'rt-ap-none' },
                '⚠️ 现有的通道都在自己的服务器上，没有碰到目标 —— 不计边界突破。需要目标侧发起的通道（反弹 shell 到我这 / 目标上跑 frp 客户端 / 经目标 WebShell 的 suo5）。'))
            }
            body.push(h('div', { key: 'tl', className: 'rt-ap-tunnels' },
              st.tunnels.length
                ? st.tunnels.map((t) => h('div', { key: 't' + t.id, className: 'rt-ap-tunnel' },
                    h('span', { className: 'rt-tag rt-tag-passive' }, t.kind || 'tunnel'),
                    h('span', { className: 'rt-mono', style: { fontWeight: 600 } }, t.listen || '—'),
                    h('span', {
                      className: 'rt-tag ' + (t.status === 'active' ? 'rt-tag-live' : ''),
                      style: t.status === 'active' ? {} : { opacity: .7 },
                    }, t.status === 'active' ? '可用' : (t.status || '未知')),
                    h('span', { className: 'rt-ap-nth', style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' } },
                      '可达 ' + (t.reach || '—'))))
                : h('div', { className: 'rt-ap-none' }, '还没有建立隧道（建好后用 redteam_tunnel_add 登记）')))
          }
          if (st.assets.length && st.code !== 'boundary') {
            body.push(h('div', { key: 'at', className: 'rt-ap-sub' }, '涉及资产 · ' + st.assetCount + ' 台'))
            body.push(h('div', { key: 'al', className: 'rt-ap-assets' }, st.assets.map(assetRow)))
          }
        }

        return h('div', { key: 'st' + st.code, className: 'rt-ap-stage' },
          h('div', { className: 'rt-ap-head', style: { borderLeftColor: st.color } },
            h('span', { className: 'rt-ap-no', style: { background: st.color } }, CIRCLED[i] || ('0' + (i + 1))),
            h('span', { className: 'rt-ap-name' }, st.name),
            st.subtitle ? h('span', { className: 'rt-ap-en' }, st.subtitle) : null,
            h('div', { className: 'rt-spacer' }),
            st.points > 0 ? h('span', { className: 'rt-ap-pts', style: { background: st.color + '22', color: st.color, borderColor: st.color + '66' } }, '+' + st.points) : null,
            h('span', { className: 'rt-ap-cum' }, '累计 ' + st.cumulative + ' 分')),
          h('div', { className: 'rt-ap-goal', style: { borderLeftColor: st.color } },
            h('span', { className: 'rt-ap-goal-tag', style: { color: st.color, borderColor: st.color + '66' } }, '阶段目标'),
            h('span', null, st.goal)),
          h('div', { className: 'rt-ap-result', style: { borderLeftColor: st.color } }, body),
          i < stages.length - 1
            ? h('div', { className: 'rt-ap-trans' },
                h('span', { className: 'rt-flow-arrow' }, '▼'),
                st.transition ? h('span', { className: 'rt-ap-trans-t' }, st.transition) : null,
                h('span', { className: 'rt-ap-trans-t', style: { marginLeft: 'auto' } }, '累计 ' + st.cumulative + ' 分'))
            : h('div', { className: 'rt-ap-trans' },
                h('span', { className: 'rt-flow-arrow' }, '▼'),
                h('span', { className: 'rt-ap-trans-t' }, '合计 ' + ((summary && summary.points) || 0) + ' 分')))
      }

      /* ── B：横向攻击链（一屏看完） ─────────────────────────────── */
      const stageB = (st, i) => h('div', { key: 'c' + st.code, className: 'rt-ap-col' },
        i > 0 ? h('span', { className: 'rt-ap-col-arrow' }, '▶') : null,
        h('div', { className: 'rt-hcol', style: { borderTopColor: st.color } },
          h('div', { className: 'rt-ap-head', style: { borderLeftColor: st.color, padding: '5px 8px' } },
            h('span', { className: 'rt-ap-no', style: { background: st.color, width: 16, height: 16, fontSize: 10 } }, String(i + 1)),
            h('span', { className: 'rt-ap-name', style: { fontSize: 12 } }, st.name),
            h('div', { className: 'rt-spacer' }),
            h('span', { className: 'rt-ap-cum', style: { fontWeight: 700 } }, st.cumulative)),
          h('div', { className: 'rt-hcol-goal', title: st.goal }, st.goal),
          h('div', { className: 'rt-hcol-body' },
            st.code === 'boundary'
              ? h('div', null,
                  h('div', { className: 'rt-hcol-hit' }, h('span', { className: 'rt-hcol-pts' }, '+' + st.points), h('span', { className: 'rt-hcol-name' }, '隧道 ' + st.tunnels.length + ' 条')),
                  st.tunnels.slice(0, 3).map((t) => h('div', { key: 't' + t.id, className: 'rt-hcol-sub' }, '▸ ' + (t.kind || '') + ' ' + (t.listen || ''))))
              : st.code === 'recon'
                ? h('div', null,
                    h('div', { className: 'rt-hcol-hit' }, h('span', { className: 'rt-hcol-pts' }, st.assetCount), h('span', { className: 'rt-hcol-name' }, '台资产拿到分')),
                    st.assets.slice(0, 6).map((a) => h('div', { key: 'a' + a.id, className: 'rt-hcol-sub', title: a.ip + '  +' + a.points + ' 分' },
                      (a.scope === 'internal' ? '内 ' : '外 ') + a.ip + '  +' + a.points)))
                : h('div', null,
                    h('div', { className: 'rt-hcol-hit' }, h('span', { className: 'rt-hcol-pts' }, '+' + st.points), h('span', { className: 'rt-hcol-name' }, st.hits + ' 次命中')),
                    st.items.slice(0, 6).map((x) => h('div', { key: 'c' + x.id, className: 'rt-hcol-sub', title: x.point_name + '  ' + (x.target || '') },
                      h('span', { className: 'rt-hcol-pts' }, '+' + x.points), h('span', { className: 'rt-hcol-name' }, x.point_name))),
                    st.items.length > 6 ? h('div', { className: 'rt-hcol-none' }, '…另有 ' + (st.items.length - 6) + ' 次') : null,
                    st.assetCount ? h('div', { className: 'rt-hcol-none' }, '涉及 ' + st.assetCount + ' 台资产') : null))))

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '攻击链'),
          h('span', { className: 'rt-tag', style: { fontSize: 10.5 } }, '信息收集 → 互联网资产权限 → 边界突破 → 内网资产权限 → 靶标权限'),
          summary ? h('span', { className: 'rt-tag rt-tag-live' }, '总分 ' + summary.points + ' 分') : null,
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn' + (view === 'A' ? ' rt-btn-primary' : ''), title: '竖向攻击链：逐阶段向下看细节', onClick: () => setView('A') }, '链路 A'),
          h('button', { className: 'rt-btn' + (view === 'B' ? ' rt-btn-primary' : ''), title: '横向攻击链：一屏看完五个阶段', onClick: () => setView('B') }, '链路 B'),
          h('button', { className: 'rt-btn', disabled: loading, onClick: load }, loading ? '加载中…' : '刷新')),
        !data ? h('div', { className: 'rt-note', role: 'status' }, loading ? '正在核对当前项目攻击链…' : '当前项目攻击链未确认，请刷新核对。') : null,
        err ? h('div', { className: 'rt-err' }, err) : null,
        !stages.length && !err && data !== null
          ? h('div', { className: 'rt-empty' }, '还没有得分记录。拿到成果后用 redteam_score_hit 记分，这条链才会长出来。')
          : view === 'A'
            ? h('div', { className: 'rt-ap' }, stages.map(stageA))
            : h('div', { className: 'rt-ap-h' }, stages.map(stageB)))
    }

    /* ---------------------------------------------------------- 得分复现报告 */
    /**
     * 报告分组兜底：host 只给平铺条目时，用 scoreChain 的阶段信息把条目按攻击链顺序分组。
     * 依据是两边共同的 score_hit id —— scoreChain 的每条 item 都带 stage_code，
     * scoreReport 的每条 item 带同样的 id。这样即使 host 侧版本较旧或阶段行缺失，
     * 报告页也能正常显示，而不是误报"还没有可交付的成果"。
     */
    function groupByStage(reportItems, chain) {
      const byId = new Map((reportItems || []).map((x) => [x.id, x]))
      const groups = []
      const stageList = (chain && chain.stages) || []
      stageList.forEach((st, si) => {
        const items = (st.items || []).map((x) => byId.get(x.id)).filter(Boolean)
        if (items.length === 0) return
        groups.push({ code: st.code, name: st.name, color: st.color || '#64748b',
          ordinal: st.ordinal || si + 1, points: st.points || 0, cumulative: st.cumulative || 0, items })
      })
      /* scoreChain 完全没有阶段信息时，至少把得分归到「其他」，不要让条目凭空消失 */
      const grouped = new Set(groups.reduce((acc, g) => acc.concat(g.items.map((x) => x.id)), []))
      const rest = (reportItems || []).filter((x) => !grouped.has(x.id))
      if (rest.length > 0) {
        groups.push({ code: 'other', name: '其他得分', color: '#64748b', ordinal: groups.length + 1,
          points: rest.reduce((n, x) => n + (x.counted ? x.points : 0), 0),
          cumulative: 0, items: rest })
      }
      return groups
    }

    function ReportTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [snapshot, setData] = React.useState(null)
      const [error, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [feedback, setMsg] = React.useState(null)
      const [pager, setPager] = React.useState(null)
      /* 报告按阶段折叠：默认全开，折叠状态按靶标记住（阶段多时便于逐段交付） */
      const collapse = useCollapse('report:' + eng)
      const generation = React.useRef(0)
      const requests = React.useRef(null)
      const mounted = React.useRef(true), owner = React.useRef({ eng, refreshKey })
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      const page = owner.current
      const owns = () => mounted.current && owner.current === page
      const data = snapshot?.page === page && snapshot.token === generation.current ? snapshot : null
      const err = error?.page === page ? error.text : null
      const msg = feedback?.page === page && feedback.token === generation.current ? feedback : null
      const record = x => !!x && typeof x === 'object' && !Array.isArray(x)
      const leaves = (x, fields) => fields.every(k => x[k] == null || typeof x[k] === 'string' || (typeof x[k] === 'number' && Number.isFinite(x[k])))
      const validItem = x => record(x) && Number.isSafeInteger(x.id) && x.id > 0
        && leaves(x, ['seq','points','nth_of_point','point_name','target','asset_ip','gained','evidence','note','how','recorded_at','recorded_by'])
        && (x.vuln == null || (record(x.vuln) && leaves(x.vuln, ['cve','title'])))
        && ['requests','steps','credentials','tunnels','webshells','gaps'].every(k => x[k] == null || (Array.isArray(x[k])
          && x[k].every(v => k === 'gaps' ? typeof v === 'string' : record(v)
            && leaves(v, ['request','response','method','url','status','title','detail','agent','stage_code','recorded_at','tool','host','username','secret_type','privilege','source','kind','listen','entry','reach','entry_kind','command','shell_type','pass_key']))))
      const validReport = r => record(r) && r.ok === true && Array.isArray(r.items) && r.items.every(validItem)
        && typeof r.markdown === 'string' && record(r.summary)
        && Number.isSafeInteger(r.summary.count) && r.summary.count >= 0
        && Number.isFinite(r.summary.points) && r.summary.points >= 0
        && (r.stages == null || (Array.isArray(r.stages) && r.stages.every(st => record(st)
          && typeof st.code === 'string' && typeof st.name === 'string' && leaves(st, ['ordinal','points','cumulative','color'])
          && Array.isArray(st.items) && st.items.every(validItem))))

      const load = () => {
        if (!eng || !owns()) return
        requests.current?.abort()
        const controller = new AbortController()
        requests.current = controller
        const my = ++generation.current
        const active = () => my === generation.current && owns()
        setBusy(true); setMsg(null); setErr(null); setData(null)
        const fail = () => { if (active()) { setBusy(false); setData(null); setErr({ page, text: '当前项目报告未确认，请重新生成核对。' }) } }
        const accept = r => { if (active()) { setBusy(false); setErr(null); setData({ ...r, page, token: my }) } }
        api({ op: 'scoreReport', engagement: eng }, { signal: controller.signal }).then((r) => {
          if (!active()) return
          if (!validReport(r)) { fail(); return }
          /* 老 host 只给平铺条目、不给阶段分组（或阶段行缺失）：自己按攻击链分组，
             否则报告页会误报"还没有可交付的成果"。分组数据取自 scoreChain。 */
          if ((!r.stages || r.stages.length === 0) && (r.items || []).length > 0) {
            api({ op: 'scoreChain', engagement: eng }, { signal: controller.signal }).then((c) => {
              if (!active()) return
              try {
                const next = { ...r, stages: groupByStage(r.items, c) }
                if (!validReport(next)) { fail(); return }
                accept(next)
              } catch { fail() }
            }, () => { if (active()) accept({ ...r, stages: groupByStage(r.items, null) }) })
            return
          }
          accept(r)
        }, (e) => { if (active()) { setBusy(false); setErr({ page, text: '当前项目报告未确认：' + String((e && e.message) || e) }) } })
        return () => {
          if (my === generation.current) generation.current++
          controller.abort()
        }
      }
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; requests.current?.abort() } }, [])
      React.useEffect(() => load(), [eng, refreshKey])

      const token = generation.current
      const actionCurrent = () => owns() && data !== null && data.token === generation.current && token === generation.current
      const publish = value => { if (actionCurrent()) setMsg({ ...value, page, token }) }

      /* 复制结果必须是真实的：clipboard API 失败时（非安全上下文/失焦/被拒）要如实提示，
         否则用户以为复制成功、粘到 Yakit 里是空的。 */
      const copy = (text, label) => {
        if (!actionCurrent()) return
        return copyWithFeedback(text, label, (okFlag, message) => publish(okFlag ? { ok: message } : { err: message }))
      }
      const download = (text, label) => {
        if (!actionCurrent()) return
        try {
          const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = 'report-' + String(label || 'score').replace(/[^\w.\-]/g, '_') + '.md'
          a.click()
          URL.revokeObjectURL(url)
          publish({ ok: '已发起下载：' + label })
        } catch (e) { publish({ err: '下载失败：' + ((e && e.message) || e) }) }
      }

      const items = (data && data.items) || []
      const stages = (data && data.stages) || []
      const summary = (data && data.summary) || null
      const mdText = (data && data.markdown) || ''
      const detailItems = stages.flatMap(st => st.items)
      const pageIndex = pager?.snapshot === data ? pager.index : 0
      const pageCount = Math.max(1, Math.ceil(detailItems.length / 25))
      const visibleIds = new Set(detailItems.slice(pageIndex * 25, (pageIndex + 1) * 25).map(x => x.id))
      const visibleStages = stages.map(st => ({ ...st, items: st.items.filter(x => visibleIds.has(x.id)) })).filter(st => st.items.length)
      const movePage = index => { if (actionCurrent() && Number.isInteger(index) && index >= 0 && index < pageCount) setPager({ snapshot: data, index }) }
      const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩', '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳']

      /* 每项一条，平铺不折叠：目标 → 拿到什么 → 复现请求（可直接粘进 Yakit）→ 响应 */
      const card = (x) => h('div', { key: 'r' + x.id, className: 'rt-rep' },
        h('div', { className: 'rt-rep-head' },
          h('span', { className: 'rt-rep-idx' }, String(x.seq)),
          h('span', { className: 'rt-rep-name' }, x.point_name),
          h('span', { className: 'rt-flow-pts' }, '+' + x.points + ' 分'),
          x.nth_of_point > 1 ? h('span', { className: 'rt-tag' }, '同类第 ' + x.nth_of_point + ' 次') : null,
          h('div', { className: 'rt-spacer' }),
          h('button', {
            className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
            onClick: () => copy((x.requests || []).map((v) => v.request || '').filter(Boolean).join('\n\n'), '第 ' + x.seq + ' 项请求'),
          }, '复制请求')),
        h('div', { className: 'rt-rep-meta' },
          h('span', null, h('b', null, '目标 ')), h('span', { className: 'rt-mono' }, x.target || x.asset_ip || '—')),
        x.gained ? h('div', { className: 'rt-rep-meta' }, h('b', null, '拿到 '), h('span', null, x.gained)) : null,
        x.vuln ? h('div', { className: 'rt-rep-meta' }, h('b', null, '利用漏洞 '),
          h('span', null, [x.vuln.cve, x.vuln.title].filter(Boolean).join(' '))) : null,
        x.evidence ? h('div', { className: 'rt-rep-meta' }, h('b', null, '结果 '),
          h('span', null, String(x.evidence).replace(/\n+/g, ' '))) : null,
        x.recorded_at ? h('div', { className: 'rt-rep-meta' }, h('b', null, '取得时间 '),
          h('span', null, fmt(x.recorded_at) + (x.recorded_by ? '（' + (ROLE_LABEL[x.recorded_by] || x.recorded_by) + '）' : ''))) : null,
        h(ShotStrip, { eng: eng, shots: x.shots, total: x.shot_total, title: '证据截图' }),
        /* ── 复现步骤：动作记录（含实际命令与回显）+ 凭据 + 隧道 + WebShell ─────
           报告的交付价值全在这块：账号密码怎么来的、隧道怎么搭的，用户照着就能复现。 */
        h('details', { className: 'rt-rep-trace', open: x.incomplete === true || (x.steps || []).length === 0 },
          h('summary', { className: 'rt-rep-trace-head', style: { cursor: 'pointer' } },
            h('span', { className: 'rt-rep-trace-title' }, '复现步骤（点击展开）'),
            (x.steps || []).length ? h('span', { className: 'rt-tag' }, (x.steps || []).length + ' 个动作') : null,
            (x.credentials || []).length ? h('span', { className: 'rt-tag' }, (x.credentials || []).length + ' 条凭据') : null,
            (x.tunnels || []).length ? h('span', { className: 'rt-tag' }, (x.tunnels || []).length + ' 条隧道') : null,
            x.incomplete ? h('span', { className: 'rt-tag rt-tag-warn' }, '复现材料待补') : h('span', { className: 'rt-tag rt-tag-live' }, '可复现')),
          h('div', { style: { paddingTop: 6 } },
          x.how ? h('div', { className: 'rt-rep-trace-how' }, x.how) : null,
          (x.steps || []).length === 0
            ? h('div', { className: 'rt-rep-missing' },
                '⚠️ 没有关联的攻击步骤：说不清这一步是怎么做的。请用 redteam_chain_add 补上动作（title / detail / tool / result），记分时也可以带 point_code + evidence 一次完成。')
            : (x.steps || []).map((s, si) => h('div', { key: 's' + s.id, className: 'rt-rep-step' },
                h('div', { className: 'rt-rep-step-head' },
                  h('span', { className: 'rt-rep-step-no' }, String(si + 1)),
                  h('span', { className: 'rt-rep-step-title' }, s.title || '(未命名动作)'),
                  s.agent ? h('span', { className: 'rt-tag' }, ROLE_LABEL[s.agent] || s.agent) : null,
                  s.stage_code ? h('span', { className: 'rt-tag' }, s.stage_code) : null,
                  s.inferred ? h('span', { className: 'rt-tag' }, '按同资产推断') : null,
                  h('div', { className: 'rt-spacer' }),
                  s.recorded_at ? h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } }, fmt(s.recorded_at)) : null),
                s.detail ? h('div', { className: 'rt-rep-step-detail' }, s.detail) : null,
                h('div', { className: 'rt-rep-step-cmd' },
                  h('b', null, '执行 '),
                  s.tool
                    ? h('span', { className: 'rt-mono' }, s.tool)
                    : h('span', { style: { color: 'var(--dsw-alias-state-warn-primary, #f59e0b)' } }, '未记录实际命令（redteam_chain_add 的 tool）')),
                s.tool ? h('div', { style: { marginTop: 3 } },
                  h('button', {
                    className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
                    onClick: () => copy(String(s.tool), '第 ' + (si + 1) + ' 步命令'),
                  }, '复制命令')) : null,
                s.result ? h('div', { className: 'rt-rep-step-result' }, h('b', null, '结果 '), String(s.result).replace(/\n+/g, ' ')) : null,
                s.evidence_ref ? h('div', { className: 'rt-rep-step-result' }, h('b', null, '证据 '), h('span', { className: 'rt-mono' }, s.evidence_ref)) : null)),
          /* 账号密码怎么来的：凭据的来源 + 取得方式 */
          (x.credentials || []).length
            ? h('div', { className: 'rt-rep-src' },
                h('div', { className: 'rt-rep-src-title' }, '拿到的凭据（来源可追溯）'),
                (x.credentials || []).map((c) => h('div', { key: 'c' + c.id, className: 'rt-kv' },
                  h('b', { className: 'rt-mono', style: { minWidth: 120 } }, c.host || '—'),
                  h('span', null, (c.username || '(无用户名)') + ' / ' + (c.secret_type || 'password')
                    + (c.privilege ? ' · 权限 ' + c.privilege : '')
                    + ' · 来源 ' + (c.source || '未标注')
                    + (c.tool ? ' · 取得方式 ' + String(c.tool).replace(/\n+/g, ' ').slice(0, 160) : '')))))
            : null,
          /* 隧道怎么搭的 */
          (x.tunnels || []).length
            ? h('div', { className: 'rt-rep-src' },
                h('div', { className: 'rt-rep-src-title' }, '用到的隧道 / 通道'),
                (x.tunnels || []).map((t) => h('div', { key: 't' + t.id, className: 'rt-kv' },
                  h('b', { className: 'rt-mono', style: { minWidth: 120 } }, (t.kind || 'socks5') + ' ' + (t.listen || '')),
                  h('span', null, '入口 ' + (t.entry || '未登记')
                    + (t.reach ? ' · 可达 ' + t.reach : '')
                    + ' · 目标侧 ' + (t.entry_kind || '未声明')
                    + (t.legit === false ? ' · ⚠️ 不算跨越靶标边界' : '')
                    + (t.status ? ' · ' + t.status : '')
                    + (t.command ? ' · 命令 ' + String(t.command).replace(/\n+/g, ' ').slice(0, 160) : '')))))
            : null,
          (x.webshells || []).length
            ? h('div', { className: 'rt-rep-src' },
                h('div', { className: 'rt-rep-src-title' }, '用到的 WebShell'),
                (x.webshells || []).map((w) => h('div', { key: 'w' + w.id, className: 'rt-kv' },
                  h('b', { className: 'rt-mono', style: { minWidth: 120 } }, w.shell_type || 'shell'),
                  h('span', null, (w.url || '') + (w.pass_key ? ' · 口令/密钥 [已隐藏]' : '')
                    + (w.privilege ? ' · 权限 ' + w.privilege : '') + (w.status ? ' · ' + w.status : '')))))
            : null,
          (x.gaps || []).length ? h('div', { className: 'rt-rep-missing' }, '⚠️ 复现缺口：' + x.gaps.join('；')) : null),
        (x.requests || []).length === 0
          ? h('div', { className: 'rt-rep-missing' }, '⚠️ 这一项没有原始请求记录，无法直接复现 —— 请用 redteam_http_evidence_add 补上')
          : (x.requests || []).map((r, ri) => h('div', { key: 'q' + ri, className: 'rt-rep-req' },
              h('div', { className: 'rt-rep-req-head' },
                h('span', null, '复现请求 ' + (ri + 1) + (r.source === 'auto' ? '（按目标路径自动匹配，请核对）' : '')),
                h('span', { className: 'rt-tag' }, (r.method || 'GET') + ' ' + (r.status === null || r.status === undefined ? '' : r.status)),
                h('div', { className: 'rt-spacer' }),
                h('button', {
                  className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
                  onClick: () => copy(String(r.request || ''), '请求 ' + (ri + 1)),
                }, '复制到 Yakit')),
              h('pre', { className: 'rt-rep-http' }, r.request || ((r.method || 'GET') + ' ' + (r.url || '') + ' HTTP/1.1')),
              r.response ? h('div', null,
                h('div', { className: 'rt-rep-req-head' }, h('span', null, '响应摘要')),
                h('pre', { className: 'rt-rep-http', style: { maxHeight: 160 } }, String(r.response).slice(0, 1600))) : null)),
        x.note ? h('div', { className: 'rt-rep-meta' }, h('b', null, '备注 '), h('span', null, x.note)) : null))

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '攻击得分链路复现报告'),
          summary ? h('span', { className: 'rt-tag rt-tag-live' }, '合计 ' + summary.points + ' 分') : null,
          summary ? h('span', { className: 'rt-tag' }, summary.count + ' 项得分') : null,
          summary ? h('span', { className: 'rt-tag' + (summary.missingRequests ? '' : ' rt-tag-live') },
            summary.withRequests + '/' + summary.count + ' 项带原始请求') : null,
          summary ? h('span', {
            className: 'rt-tag' + (summary.incomplete ? ' rt-tag-warn' : ' rt-tag-live'),
            title: '复现链是否完整：有攻击步骤、写了实际命令、关联了漏洞/凭据/隧道',
          }, '可复现 ' + (summary.count - (summary.incomplete || 0)) + '/' + summary.count) : null,
          summary && summary.serviceCappedExcluded
            ? h('span', {
                className: 'rt-tag rt-tag-warn',
                title: (summary.serviceCapped || []).map((x) => (x.service || '') + '｜' + (x.point_name || '')).join('\n')
                  || '同一资产同一端口的重复账号/数据库权限命中：服务已拿满，不计分、不进报告',
              }, '同服务已拿满不计分 ' + summary.serviceCappedExcluded)
            : null,
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn', disabled: busy || !mdText, onClick: () => copy(mdText, '整份报告') }, '复制全文'),
          h('button', { className: 'rt-btn', disabled: busy || !mdText, onClick: () => download(mdText, (data && data.target) || eng) }, '下载 .md'),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, busy ? '生成中…' : '重新生成')),
        msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        err ? h('div', { className: 'rt-err' }, err) : null,
        data && detailItems.length ? h('div', { className: 'rt-toolbar' },
          h('span', null, '明细 ' + (pageIndex * 25 + 1) + '–' + Math.min((pageIndex + 1) * 25, detailItems.length) + ' / ' + detailItems.length + ' 条；总分与导出包含全部成果。'),
          h('button', { className: 'rt-btn', disabled: pageIndex === 0, onClick: () => movePage(pageIndex - 1) }, '上一页'),
          h('button', { className: 'rt-btn', disabled: pageIndex + 1 >= pageCount, onClick: () => movePage(pageIndex + 1) }, '下一页')) : null,
        h('div', { className: 'rt-body', style: { overflow: 'auto' } },
          stages.length
            ? h('div', { className: 'rt-rep-list' },
                h('div', { className: 'rt-rep-tools' },
                  h('button', { className: 'rt-btn', onClick: () => collapse.setAll(stages.map((s) => 'st:' + s.code), true) }, '全部展开'),
                  h('button', { className: 'rt-btn', onClick: () => collapse.setAll(stages.map((s) => 'st:' + s.code), false) }, '全部折叠')),
                visibleStages.map((st) => {
                  const open = collapse.isOpen('st:' + st.code, true)
                  const toggle = collapse.toggle('st:' + st.code, true)
                  return h('div', { key: 'g' + st.code, className: 'rt-rep-group' },
                    h('div', {
                      className: 'rt-rep-stage', role: 'button', tabIndex: 0,
                      style: { borderLeftColor: st.color },
                      'aria-expanded': open ? 'true' : 'false',
                      onClick: toggle,
                      onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(e) } },
                    },
                      h('span', { className: 'rt-sec-caret' }, open ? '▾' : '▸'),
                      h('span', { className: 'rt-rep-no', style: { background: st.color } }, CIRCLED[st.ordinal - 1] || st.ordinal),
                      h('span', { className: 'rt-rep-stage-name' }, st.name),
                      h('span', { className: 'rt-rep-stage-n' }, st.items.length + ' 项'),
                      h('div', { className: 'rt-spacer' }),
                      h('span', { className: 'rt-rep-pts', style: { background: st.color + '22', color: st.color, borderColor: st.color + '66' } },
                        '+' + st.points + ' 分'),
                      h('span', { className: 'rt-ap-cum' }, '累计 ' + st.cumulative + ' 分')),
                    open ? h('div', { className: 'rt-rep-body' }, st.items.map(card)) : null)
                }))
            : (data === null ? (!err ? h('div', { className: 'rt-empty' }, busy ? '加载中…' : '暂无报告') : null)
                : h('div', { className: 'rt-empty' },
                    h('div', null, '还没有可交付的成果。'),
                    h('div', { style: { marginTop: 6, fontSize: 12 } },
                      '本报告只收录"拿到了分"的成果；没有得分的漏洞不进报告。拿到成果后用 redteam_score_hit 记分（目标资产 + 拿到的东西），并补 redteam_http_evidence_add 以便复现。')))),
        h('div', { className: 'rt-foot' },
          h('span', null, '口径：只收录得分成果，每条附带可粘进 Yakit Repeater 的原始请求')))
    }

    /* ---------------------------------------------------------- 攻击文件 */
    const FILE_KIND = { poc: 'POC', exp: 'EXP', script: '脚本', wordlist: '字典', other: '其他' }

    function AttackFilesTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [folders, setFolders] = React.useState([])
      const [err, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const collapse = useCollapse('files:' + eng)
      const [detail, setDetail] = React.useState(null)

      const load = () => {
        if (!eng) return
        setBusy(true)
        api({ op: 'attackFiles', engagement: eng }).then((r) => {
          setBusy(false)
          if (!r || r.ok === false) { setErr((r && r.error) || '读取失败'); return }
          setErr(null)
          setFolders(r.items || [])
        }, (e) => { setBusy(false); setErr(String((e && e.message) || e)) })
      }
      React.useEffect(load, [eng, refreshKey])

      const openFile = (f) => {
        if (detail && detail.id === f.id) { setDetail(null); return }
        setDetail(null)
        api({ op: 'readAttackFile', engagement: eng, id: f.id }).then((r) => {
          if (r && r.ok) setDetail(r)
          else setErr((r && r.error) || '读取失败')
        }, (e) => setErr(String((e && e.message) || e)))
      }

      const rows = []
      for (const folder of folders) {
        const fKey = 'folder:' + folder.folder
        const fileNodes = []
        for (const f of folder.files) {
          fileNodes.push(h('div', {
            key: 'a' + f.id, className: 'rt-vrow', style: { gridTemplateColumns: '18px 1.2fr 60px 1.6fr', cursor: 'pointer' },
            role: 'button', tabIndex: 0,
            onClick: () => openFile(f),
            onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFile(f) } },
          },
            h('span', { className: 'rt-sec-caret' }, detail && detail.id === f.id ? '▾' : '▸'),
            h('span', { className: 'rt-mono' }, f.name),
            h('span', null, h('span', { className: 'rt-tag rt-tag-active' }, FILE_KIND[f.kind] || f.kind || '—')),
            h('span', { style: { fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }, title: f.description || '' }, f.description || '—')))
          if (!detail || detail.id !== f.id) continue
          fileNodes.push(h('div', {
            key: 'ad' + f.id, className: 'rt-vrow', style: { cursor: 'default', gridTemplateColumns: '1fr' },
          }, h('div', { className: 'rt-vdetail' },
            h('div', { className: 'rt-kv' }, h('b', null, '效果'), h('span', null, detail.evidence || '—')),
            h('div', { className: 'rt-kv' }, h('b', null, '路径'), h('span', { className: 'rt-mono', style: { wordBreak: 'break-all' } }, detail.path)),
            h('div', { className: 'rt-kv' }, h('b', null, '记录'), h('span', null, fmt(detail.created_at) + (detail.created_by ? ' · ' + detail.created_by : ''))),
            h('pre', { className: 'rt-md', style: { border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 6, maxHeight: '40vh', padding: '10px 12px' } }, detail.content || '（空）'))))
        }
        rows.push(h(Section, {
          key: 'sec:' + folder.folder, tone: 'folder', title: folder.folder + '/',
          count: folder.count + ' 个文件',
          open: collapse.isOpen(fKey, true), onToggle: collapse.toggle(fKey, true),
        }, fileNodes.length ? fileNodes : h('div', { className: 'rt-atest-meta' }, '（空）')))
      }

      const total = folders.reduce((n, f) => n + f.count, 0)
      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '攻击文件'),
          h('span', { className: 'rt-tag' }, folders.length + ' 个目标 / ' + total + ' 个文件'),
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, busy ? '刷新中…' : '刷新')),
        err ? h('div', { className: 'rt-err' }, err) : null,
        h('div', { className: 'rt-table' },
          rows,
          !folders.length ? h('div', { className: 'rt-empty' }, '暂无攻击文件（打通的脚本/POC/EXP 会按目标文件夹出现在这里）') : null),
        h('div', { className: 'rt-foot' }, h('span', null, '目录：attack-files/<IP|URL主机|C段>/ ｜ 只收录实际生效的文件')))
    }

    /* ---------------------------------------------------------- 知识库（POC/EXP，全局共享） */
    /**
     * 知识库页：打 Nday/1day 之前先在这里搜。检索框支持 CVE / 组件 / 关键字 / 正文关键词；
     * 命中就展开拿全文（可直接复制去用），没有就说明要去互联网找或自己搓，验证后回填。
     * 这里是**全局**的：不随靶标切换，一个靶标沉淀的通用 POC 后面所有靶标都能用。
     */
    const POC_KIND_LABEL = { poc: 'POC', exp: 'EXP', script: '脚本', template: '模板', payload: '载荷' }
    const POC_SOURCE_LABEL = { web: '互联网', self: '手搓', manual: '人工', 'nuclei-template': 'nuclei 模板', kb: '知识库' }

    function KnowledgeTab(props) {
      const refreshKey = props.refreshKey || 0
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [msg, setMsg] = React.useState(null)
      const [q, setQ] = React.useState('')
      const [kind, setKind] = React.useState('')
      const [category, setCategory] = React.useState('')
      const [engagement, setEngagement] = React.useState('')
      const [assetTarget, setAssetTarget] = React.useState('')
      const [grouped, setGrouped] = React.useState(true)
      const [verifiedOnly, setVerifiedOnly] = React.useState(false)
      const [openId, setOpenId] = React.useState(null)
      const [detail, setDetail] = React.useState(null)
      const [detailBusy, setDetailBusy] = React.useState(false)
      const [tplOffset, setTplOffset] = React.useState(0)
      const tplPageSize = 40

      const query = (over) => {
        const extra = over || {}
        const offset = Object.prototype.hasOwnProperty.call(extra, 'templateOffset') ? extra.templateOffset : 0
        setTplOffset(offset)
        const params = Object.assign({
          q: q.trim() || undefined,
          kind: kind || undefined,
          category: category || undefined,
          engagement: engagement || undefined,
          asset_target: assetTarget.trim() || undefined,
          verified: verifiedOnly || undefined,
          templateOffset: offset || 0,
          templateLimit: tplPageSize,
        }, extra)
        setBusy(true); setMsg(null)
        api(Object.assign({ op: 'pocSearch' }, params)).then((r) => {
          setBusy(false)
          if (!r || r.ok === false) { setErr((r && r.error) || '读取失败'); return }
          setErr(null); setData(r)
        }, (e) => { setBusy(false); setErr(String((e && e.message) || e)) })
      }
      /* 首次进入与刷新键变化时拉全量（检索是显式动作，避免边打字边打接口） */
      React.useEffect(() => { query({ q: undefined, kind: undefined, category: undefined, engagement: undefined, asset_target: undefined, verified: undefined }) }, [refreshKey])

      const open = (id) => {
        if (openId === id) { setOpenId(null); setDetail(null); return }
        setOpenId(id); setDetail(null); setDetailBusy(true)
        api({ op: 'pocGet', id: id }).then((r) => {
          setDetailBusy(false)
          if (!r || r.ok === false) { setMsg({ err: (r && r.error) || '读取失败' }); return }
          setDetail(r)
        }, (e) => { setDetailBusy(false); setMsg({ err: String((e && e.message) || e) }) })
      }

      /* 同报告页：await 真实结果再提示 */
      const copy = (text, label) => copyWithFeedback(text, label, (okFlag, message) => {
        setMsg(okFlag ? { ok: message } : { err: message })
      })
      const useIt = (row) => {
        api({ op: 'pocUse', id: row.id, used_on: '控制台手动标记' }).then(() => {
          setMsg({ ok: '已记一次复用：' + row.title })
          query()
        }, (e) => setMsg({ err: String((e && e.message) || e) }))
      }

      const stats = (data && data.stats) || { total: 0, verified: 0, reused: 0, byKind: [], bySource: [] }
      const items = (data && data.items) || []
      const tpl = (data && data.templates) || { dir: null, total: 0, matched: 0, offset: 0, items: [], byCategory: [] }
      const tplByCat = new Map((tpl.byCategory || []).map((c) => [c.code, c.n || 0]))
      const catShown = (c) => (c.n || 0) + (tplByCat.get(c.code) || 0)
      const tplItems = tpl.items || []
      const tplMatched = tpl.matched != null ? tpl.matched : tpl.total
      const tplStart = Number(tpl.offset) || 0
      const turnTpl = (next) => {
        const offset = Math.max(0, next)
        setTplOffset(offset)
        query({ templateOffset: offset })
      }

      const card = (x) => {
        const isOpen = openId === x.id
        const d = isOpen && detail && detail.id === x.id ? detail : null
        return h('div', { key: 'p' + x.id, className: 'rt-kb' + (isOpen ? ' open' : '') },
          h('div', {
            className: 'rt-kb-head', role: 'button', tabIndex: 0, 'aria-expanded': isOpen ? 'true' : 'false',
            onClick: () => open(x.id),
            onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(x.id) } },
          },
            h('span', { className: 'rt-sec-caret' }, isOpen ? '▾' : '▸'),
            h('span', { className: 'rt-kb-kind k-' + (x.kind || 'poc') }, POC_KIND_LABEL[x.kind] || x.kind || 'POC'),
            h('span', { className: 'rt-kb-title' }, x.title),
            x.cve ? h('span', { className: 'rt-tag rt-tag-passive' }, x.cve) : null,
            x.component ? h('span', { className: 'rt-tag' }, x.component) : null,
            x.verified === 1
              ? h('span', { className: 'rt-tag rt-tag-live' }, '已验证')
              : h('span', { className: 'rt-tag rt-tag-warn' }, '未验证'),
            h('div', { className: 'rt-spacer' }),
            h('span', { className: 'rt-tag' }, POC_SOURCE_LABEL[x.source] || x.source || '—'),
            x.hit_count ? h('span', { className: 'rt-tag' }, '复用 ' + x.hit_count) : null),
          /* 来源行：归类 · 影响版本 · 建立时间 · 来源靶标 · 发现资产 —— 一条知识"什么时候、
             在哪个单位的哪台资产上发现的"一眼可见 */
          h('div', { className: 'rt-kb-sub' },
            [x.category ? '归类 ' + (POC_CAT_NAME[x.category] || x.category) : null,
              x.versions ? '影响版本 ' + x.versions : null,
              x.language || null,
              x.tags || null,
              '建立时间 ' + fmt(x.created_at),
              (x.engagement_name || x.engagement_id) ? '来源靶标 ' + (x.engagement_name || x.engagement_id) : null,
              x.asset_target ? '发现资产 ' + x.asset_target : null,
              x.found_by_agent ? '发现角色 ' + (ROLE_LABEL[x.found_by_agent] || x.found_by_agent) : null,
              x.source_url ? '来源 ' + x.source_url : null].filter(Boolean).join(' · ')),
          isOpen
            ? h('div', { className: 'rt-kb-body' },
                detailBusy && !d ? h('div', { className: 'rt-empty' }, '读取中…') : null,
                d ? h('div', null,
                  d.usage ? h('div', { className: 'rt-kv' }, h('b', null, '用法'), h('span', { className: 'rt-mono' }, d.usage)) : null,
                  d.description ? h('div', { className: 'rt-kv' }, h('b', null, '说明'), h('span', null, d.description)) : null,
                  d.verified_note ? h('div', { className: 'rt-kv' }, h('b', null, '验证证据'), h('span', null, d.verified_note)) : null,
                  d.used_on ? h('div', { className: 'rt-kv' }, h('b', null, '最近使用'), h('span', null, d.used_on)) : null,
                  d.path ? h('div', { className: 'rt-kv' }, h('b', null, '落盘'), h('span', { className: 'rt-mono' }, d.path)) : null,
                  h('div', { className: 'rt-kb-actions' },
                    h('button', { className: 'rt-btn', disabled: !d.content, onClick: () => copy(d.content || '', 'POC 正文') }, '复制正文'),
                    h('button', { className: 'rt-btn', onClick: () => useIt(x) }, '记一次复用'),
                    d.source_url ? h('button', { className: 'rt-btn', onClick: () => copy(d.source_url, '来源链接') }, '复制来源') : null),
                  d.content
                    ? h('pre', { className: 'rt-rep-http' }, d.content.length > 12000 ? d.content.slice(0, 12000) + '\n…（已截断，完整内容见落盘文件）' : d.content)
                    : h('div', { className: 'rt-empty' }, '这条只有元数据，没有正文 —— 拿到正文后用 redteam_poc_update 补上'))
                : null)
            : null)
      }

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '知识库 · POC / EXP'),
          h('span', { className: 'rt-tag' }, stats.total + ' 条'),
          h('span', { className: 'rt-tag rt-tag-live' }, '已验证 ' + stats.verified),
          h('span', { className: 'rt-tag' }, '累计复用 ' + (stats.reused || 0)),
          (stats.uncategorized || 0) > 0 && (stats.uncategorized || 0) !== stats.total
            ? h('span', { className: 'rt-tag rt-tag-warn', title: '这些条目还没归类：智能体回填时用 redteam_poc_add 的 category 参数标一下' }, '未归类 ' + stats.uncategorized)
            : null,
          tpl.total ? h('span', { className: 'rt-tag rt-tag-passive' }, '本机模板 ' + tpl.total) : null,
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn' + (grouped ? ' rt-btn-primary' : ''), title: '按归类分组显示 / 平铺显示', onClick: () => setGrouped(!grouped) }, grouped ? '按归类分组' : '平铺显示'),
          h('button', { className: 'rt-btn', disabled: busy, onClick: () => query() }, busy ? '检索中…' : '刷新')),
        /* 归类总览：点一下就是按该类筛选，一眼看清"哪类武器攒了多少、哪类还是空的" */
        h('div', { className: 'rt-kb-cats' },
          (stats.byCategory || []).filter((c) => catShown(c) > 0 || POC_CAT_ORDER.includes(c.code)).map((c) => h('span', {
            key: c.code,
            className: 'rt-concl-i' + (category === c.code ? ' on' : ''),
            title: (c.hint || POC_CAT_NAME[c.code] || c.code)
              + ' · 本机模板 ' + (tplByCat.get(c.code) || 0)
              + ' · 知识库 ' + (c.n || 0)
              + (c.verified ? '（已验证 ' + c.verified + '）' : ''),
            onClick: () => {
              const next = category === c.code ? '' : c.code
              setCategory(next)
              query({ category: next || undefined })
            },
          },
            h('b', null, String(catShown(c))),
            h('span', null, (POC_CAT_NAME[c.code] || c.code) + (c.verified ? '（已验证 ' + c.verified + '）' : ''))))),
        h('div', { className: 'rt-kb-filter' },
          h('input', {
            className: 'rt-input', style: { flex: 1, minWidth: 140 }, placeholder: '搜 CVE / 组件 / 关键字（正文也会搜）',
            value: q, onChange: (e) => setQ(e.target.value),
            onKeyDown: (e) => { if (e.key === 'Enter') query() },
          }),
          h('select', { className: 'rt-input', style: { maxWidth: 120 }, value: category, onChange: (e) => { setCategory(e.target.value); query({ category: e.target.value || undefined }) } },
            h('option', { value: '' }, '全部归类'),
            POC_CAT_ORDER.map((k) => h('option', { key: k, value: k }, POC_CAT_NAME[k]))),
          h('select', { className: 'rt-input', style: { maxWidth: 120 }, value: engagement, onChange: (e) => { setEngagement(e.target.value); query({ engagement: e.target.value || undefined }) } },
            h('option', { value: '' }, '全部来源靶标'),
            (stats.byEngagement || []).map((e) => h('option', { key: e.engagement, value: e.engagement }, e.engagement + '（' + e.n + '）'))),
          h('input', {
            className: 'rt-input', style: { width: 120 }, placeholder: '发现资产筛选',
            value: assetTarget, onChange: (e) => setAssetTarget(e.target.value),
            onKeyDown: (e) => { if (e.key === 'Enter') query() },
          }),
          h('select', { className: 'rt-input', style: { maxWidth: 110 }, value: kind, onChange: (e) => { setKind(e.target.value); query({ kind: e.target.value || undefined }) } },
            h('option', { value: '' }, '全部类型'),
            Object.keys(POC_KIND_LABEL).map((k) => h('option', { key: k, value: k }, POC_KIND_LABEL[k]))),
          h('label', { className: 'rt-kb-check' },
            h('input', { type: 'checkbox', checked: verifiedOnly, onChange: (e) => { setVerifiedOnly(e.target.checked); query({ verified: e.target.checked || undefined }) } }),
            '只看已验证'),
          h('button', { className: 'rt-btn rt-btn-primary', onClick: () => query() }, '检索')),
        msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        err ? h('div', { className: 'rt-err' },
          /engagement required|unknown op/i.test(err)
            /* 老 host 还没有知识库接口：讲清怎么恢复，别让人对着 "engagement required" 发懵 */
            ? '知识库接口由 host 侧提供，当前宿主还是旧进程 —— 请完全退出后重新打开（官方 exe / 社区版 / dsh web 任一），再刷新页面。'
            : err) : null,
        !err && data && data.dbPath
          ? h('div', { className: 'rt-foot', style: { marginBottom: 6, fontSize: 11 } },
              '知识库：' + data.dbPath
              + (data.root ? '（根目录 ' + data.root + '）' : ''))
          : null,
        h('div', { className: 'rt-table' },
          (() => {
            if (!grouped) return items.map(card)
            /* 分组渲染：按内置归类顺序，未知归类挂到末尾的「其它」 */
            const buckets = new Map()
            for (const x of items) {
              const code = POC_CAT_NAME[x.category] ? x.category : 'other'
              if (!buckets.has(code)) buckets.set(code, [])
              buckets.get(code).push(x)
            }
            const order = POC_CAT_ORDER.filter((c) => buckets.has(c))
            for (const code of buckets.keys()) if (!order.includes(code)) order.push(code)
            const out = []
            for (const code of order) {
              const list = buckets.get(code)
              out.push(h('div', { key: 'g' + code, className: 'rt-kb-cat' },
                h('span', { className: 'rt-kb-cat-name' }, POC_CAT_NAME[code] || code),
                h('span', { className: 'rt-tag' }, list.length + ' 条'),
                h('span', { className: 'rt-tag rt-tag-live' }, '已验证 ' + list.filter((x) => x.verified === 1).length),
                h('span', { className: 'rt-spacer' }),
                h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } },
                  '最近建立 ' + fmt(list.map((x) => x.created_at).filter(Boolean).sort().pop()))))
              for (const x of list) out.push(card(x))
            }
            return out
          })(),
          tplItems.length
            ? h('div', { className: 'rt-kb-tpl' },
                h('div', { className: 'rt-ap-sub' },
                  '本机 nuclei 模板 · ' + (tplStart + 1) + '–' + (tplStart + tplItems.length) + ' / ' + tplMatched
                  + '（直接 `nuclei -t <模板路径>`）'),
                tplItems.map((t, i) => h('div', { key: 't' + tplStart + '-' + i, className: 'rt-kb-tpl-row' },
                  h('span', { className: 'rt-tag' }, t.severity || '—'),
                  t.category ? h('span', { className: 'rt-tag' }, POC_CAT_NAME[t.category] || t.category) : null,
                  h('span', { className: 'rt-mono rt-kb-tpl-path', title: t.path }, t.path),
                  h('span', { className: 'rt-kb-tpl-name', title: t.name }, t.name || ''),
                  h('button', {
                    className: 'rt-btn', style: { padding: '0 6px', fontSize: 10.5 },
                    onClick: () => copy('nuclei -t ' + t.path + ' -u <目标>', '模板命令'),
                  }, '复制命令'))),
                h('div', { className: 'rt-kb-actions' },
                  h('button', {
                    className: 'rt-btn', disabled: busy || tplStart <= 0,
                    onClick: () => turnTpl(tplStart - tplPageSize),
                  }, '上一页'),
                  h('button', {
                    className: 'rt-btn', disabled: busy || tplStart + tplItems.length >= tplMatched,
                    onClick: () => turnTpl(tplStart + tplPageSize),
                  }, '下一页')),
                tpl.dir ? h('div', { className: 'rt-foot' }, h('span', null, '模板目录：' + tpl.dir)) : null)
            : null,
          data === null ? h('div', { className: 'rt-empty' }, '加载中…') : null,
          data !== null && !items.length && !tplItems.length
            ? h('div', { className: 'rt-empty' },
                h('div', null,
                  q || kind || verifiedOnly
                    ? '没有命中：换个关键字再试，或去互联网找 / 自己手搓后回填。'
                    : (tpl.total
                      ? ('POC/EXP 库还是空的；本机已有 ' + tpl.total + ' 个 nuclei 模板，但这一页没有列出来。请完全退出后重新打开客户端。')
                      : (tpl.dir
                        ? '知识库还是空的（本机模板目录存在但没有 yaml，请跑 nuclei -update-templates）。'
                        : '知识库还是空的。本机也还没有 nuclei 模板库 —— 在演练机上跑 setup.sh 或 `nuclei -update-templates`，装好后这里会出现「本机模板 N」。'))),
                h('div', { style: { marginTop: 6, fontSize: 12 } },
                  '打 Nday/1day 的标准顺序：① redteam_poc_search 先查这里（顺带搜本机 nuclei 模板库）→ ② 都没有就互联网搜索（web_search / GitHub / ExploitDB / 厂商公告）或自己手搓 → ③ 在真实目标上验证有效后 redteam_poc_add 回填，后面的靶标直接就能用。'),
                data.dbPath ? h('div', { style: { marginTop: 6, fontSize: 11 }, className: 'rt-mono' }, '知识库文件：' + data.dbPath) : null,
                tpl.dir ? h('div', { style: { marginTop: 6, fontSize: 11 }, className: 'rt-mono' }, '模板目录：' + tpl.dir) : null)
            : null),
        h('div', { className: 'rt-foot' },
          h('span', null, '全局共享（跨靶标）｜ 落盘：pocs/<code>/ ｜ 只收录通用可复用的 POC/EXP，靶标专用脚本走「攻击文件」')))
    }

    /* ---------------------------------------------------------- 环境适配（Windows / 非 Kali） */
    /**
     * 借鉴 Z3r0 的「系统配置」思路：路径与密钥进集中配置，不靠 bash/ps1。
     * 落盘 $DSH_HOME/redteam/config.json —— 用户填工具绝对路径或整包搜索目录。
     */
    function EnvTab(props) {
      const refreshKey = props.refreshKey || 0
      const [data, setData] = React.useState(null)
      const [draft, setDraftState] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [msg, setMsg] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [dirty, setDirty] = React.useState(false)
      const editor = React.useRef(null), touched = React.useRef(new Map()), revision = React.useRef(0)
      const mounted = React.useRef(true), generation = React.useRef(0), reader = React.useRef(null)
      const writing = React.useRef(null), reading = React.useRef(false), confirmed = React.useRef(false)
      const latest = React.useRef(null), refreshAfter = React.useRef(false)
      const folderPath = draft?.assignDirectory || ''
      const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
      const validConfig = r => r?.ok === true && record(r.config) && !r.config.error && r.config.readState !== 'error'
        && (r.config.binDirs == null || Array.isArray(r.config.binDirs))
        && (r.tools == null || (record(r.tools) && Array.isArray(r.tools.items)))
      const matchesSave = (r, wanted, id) => {
        const receipt = r.writeReceipt, c = r.config
        const has = (o, key) => Object.prototype.hasOwnProperty.call(o, key)
        return receipt?.operationId === id && receipt.op === 'platformConfigSave' && receipt.state === 'committed'
          && (c.executionTarget || 'local') === (wanted.executionTarget || 'local')
          && c.platform === wanted.platform && c.notes === wanted.notes
          && ['toolkitDir', 'nucleiTemplatesDir'].every(key => typeof c[key] === 'string' && c[key].trim() === String(wanted[key] || '').trim())
          && Array.isArray(c.binDirs) && JSON.stringify(c.binDirs) === JSON.stringify((wanted.binDirs || []).map(x => String(x || '').trim()).filter(Boolean))
          && record(c.tools) && Object.entries(wanted.tools || {}).every(([key, value]) => has(c.tools, key) && typeof c.tools[key] === 'string' && c.tools[key].trim() === String(value ?? '').trim())
          && record(c.env) && Object.entries(wanted.env || {}).every(([key, value]) => has(c.env, key) && c.env[key] === value)
          && c.envAdaptConfigured === !!wanted.envAdaptConfigured && c.envAdaptSkip === !!wanted.envAdaptSkip
      }
      const makeDraft = r => {
        const c = r.config
        return {
          executionTarget: c.executionTarget || 'local',
          platform: c.platform || 'auto', toolkitDir: c.toolkitDir || '', nucleiTemplatesDir: c.nucleiTemplatesDir || '',
          binDirsText: (c.binDirs || []).join('\n'), tools: { ...(c.tools || {}) },
          env: { FOFA_KEY: '', REDTEAM_VPS_HOST: '', REDTEAM_VPS_KEY: '', ...(c.env || {}) }, notes: c.notes || '',
          assignDirectory: c.toolkitDir || '',
        }
      }
      const replaceDraft = value => { editor.current = value; setDraftState(value); setDirty(touched.current.size > 0) }
      const edit = (key, value, member) => {
        if (!mounted.current || !editor.current) return
        const path = member === undefined ? key : key + ':' + member
        touched.current.set(path, ++revision.current)
        replaceDraft({ ...editor.current, [key]: member === undefined ? value : { ...editor.current[key], [member]: value } })
      }
      const setFolderPath = value => edit('assignDirectory', value)
      const setTool = (id, value) => edit('tools', value, id)
      const setEnv = (key, value) => edit('env', value, key)
      const accept = (r, mode = 'read', stamp) => {
        setData(r); latest.current = r; confirmed.current = true; setErr(null)
        const next = makeDraft(r), previous = editor.current
        for (const [path, changedAt] of touched.current) {
          const [key, member] = path.split(':')
          const submitted = changedAt <= stamp
          const committed = (mode === 'platformConfigSave' && key !== 'assignDirectory' && submitted)
            || (mode === 'platformAssignToolkit' && key === 'assignDirectory' && submitted)
            || (key === 'assignDirectory' && previous[key] === next[key])
          if (committed) { touched.current.delete(path); continue }
          if (member === undefined) next[key] = previous[key]
          else next[key] = { ...next[key], [member]: previous[key]?.[member] }
        }
        replaceDraft(next)
      }
      const load = () => {
        if (!mounted.current) return
        if (writing.current) { refreshAfter.current = true; return }
        const next = ++generation.current, controller = new AbortController()
        reader.current?.abort(); reader.current = controller
        reading.current = true; confirmed.current = false; setBusy(true); setErr(null)
        const owns = () => mounted.current && generation.current === next
        api({ op: 'platformConfigGet' }, { signal: controller.signal }).then(r => {
          if (!owns()) return
          if (!validConfig(r)) { setErr('当前环境配置读取未确认，请刷新核对。'); return }
          accept(r)
        }, () => { if (owns()) setErr('当前环境配置读取未确认，请刷新核对。') })
          .finally(() => { if (owns()) { reading.current = false; setBusy(false) } })
      }
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; reader.current?.abort() } }, [])
      React.useEffect(() => { load() }, [refreshKey])
      const adopt = () => {
        if (!mounted.current || writing.current || reading.current || !confirmed.current || !latest.current) return
        revision.current++; touched.current.clear(); replaceDraft(makeDraft(latest.current))
      }
      const mutate = (op, payload) => {
        if (!mounted.current || writing.current || reading.current || !confirmed.current || !editor.current) return
        const operation = {}, stamp = revision.current
        const operationId = op === 'platformConfigSave' ? 'env-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2) : undefined
        writing.current = operation; generation.current++; reader.current?.abort()
        setBusy(true); setMsg(null)
        const settle = r => {
          if (!mounted.current || writing.current !== operation) return
          writing.current = null; setBusy(false)
          const acknowledged = validConfig(r) && (op !== 'platformConfigSave' || matchesSave(r, payload.config, operationId))
          if (acknowledged) {
            accept(r, op, stamp)
            setMsg({ ok: op === 'platformConfigSave' ? '已保存配置；请求期间新增的输入会保留。'
              : '已从文件夹分配 ' + (r.assignedCount || 0) + ' 个工具；其他未保存输入会保留。' })
          } else {
            confirmed.current = false
            setMsg({ err: '配置修改结果未确认，已只读核对；未重发写入。' })
          }
          const recheck = refreshAfter.current || !acknowledged
          refreshAfter.current = false
          if (recheck) load()
        }
        api({ op, ...payload, ...(operationId ? { operationId } : {}) }).then(settle, () => settle(null))
      }
      const save = () => {
        const d = editor.current
        if (!d) return
        mutate('platformConfigSave', { config: {
          executionTarget: d.executionTarget || 'local',
          platform: d.platform, toolkitDir: d.toolkitDir, nucleiTemplatesDir: d.nucleiTemplatesDir,
          binDirs: String(d.binDirsText || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
          tools: d.tools, env: d.env, notes: d.notes, envAdaptConfigured: true, envAdaptSkip: false,
        } })
      }
      const assignFolder = () => {
        if (!mounted.current || writing.current || reading.current || !confirmed.current) return
        const dir = String(editor.current?.assignDirectory || editor.current?.toolkitDir || '').trim()
        if (!dir) { setMsg({ err: '请先填写工具所在文件夹路径' }); return }
        mutate('platformAssignToolkit', { dir })
      }

      const runtime = (data && data.runtime) || {}
      const adapt = (data && data.adapt) || {}
      const tools = (data && data.tools && data.tools.items) || []
      const found = tools.filter((t) => t.path).length
      const defaultToolkit = (data && data.toolkitDir) || '$DSH_HOME/redteam/toolkit'
      const defaultNuclei = (data && data.nucleiTemplatesDir) || (defaultToolkit + '/nuclei-templates')

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '环境适配'),
          h('span', { className: 'rt-tag' }, runtime.executionTarget === 'kali' ? '远程 Kali' : (runtime.effective === 'windows' ? 'Windows' : '本机 Linux')),
          adapt.kali ? h('span', { className: 'rt-tag rt-tag-live' }, 'Kali') : null,
          h('span', { className: 'rt-tag' + (adapt.ready ? ' rt-tag-live' : ' rt-tag-warn') },
            adapt.ready ? ('就绪 · ' + (adapt.reason || '')) : '待配置'),
          h('span', { className: 'rt-tag' + (found ? ' rt-tag-live' : ' rt-tag-warn') }, '工具 ' + found + '/' + tools.length),
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, busy ? '读取中…' : '刷新'),
          h('button', { className: 'rt-btn rt-btn-primary', disabled: busy || !draft || !!err, onClick: save }, '保存')),
        h('div', { className: 'rt-pane', style: { minHeight: 0 } },
        err ? h('div', { className: 'rt-err' }, err) : null,
        dirty ? h('div', { className: 'rt-note', role: 'status' }, '有未保存修改；刷新会保留输入。',
          h('button', { className: 'rt-btn', disabled: busy || !!err, onClick: adopt }, '使用当前配置')) : null,
        msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        h('div', { className: 'rt-card', style: { margin: '0 0 8px', fontSize: 12, lineHeight: 1.6 } },
          adapt.message
            || '均可选填：留空则用默认路径/自动查找。填了的覆盖默认。密钥类只在需要测绘/反弹时才填。'),
        h('div', { className: 'rt-card', style: { margin: '0 0 8px', fontSize: 12, lineHeight: 1.6 } },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '工具执行位置'),
          h('label', null, '选择本机或已配置的独立 Kali VM',
            h('select', { className: 'rt-input', 'aria-label': '工具执行位置', disabled: busy || !draft || !!err,
              value: draft?.executionTarget || 'local', onChange: e => edit('executionTarget', e.target.value),
              style: { display: 'block', width: '100%', marginTop: 6 } },
              h('option', { value: 'local' }, 'Harness 本机'), h('option', { value: 'kali' }, '远程 Kali · 专用 SSH'))),
          h('div', { role: 'status', style: { marginTop: 8 } },
            data?.kali?.state === 'connected' ? 'Kali 连接已确认 · ' + data.kali.hostname + ' · ' + data.kali.version + ' · UID ' + data.kali.uid
              : 'Kali 连接未确认（' + (data?.kali?.state || 'not-checked') + '）。先启动 Kali，再点刷新；不会自动启动或提权。'),
          h('div', { style: { marginTop: 6, opacity: 0.85 } }, '选择后点保存。远程工具通过专用 SSH 执行，缺失工具不会回退到本机。本机路径保留；以下目录、密钥与 VPS 配置不会复制到 Kali；输入、输出和模板参数都应使用 Kali 内路径。')),
        h('div', { className: 'rt-card', style: { margin: '0 0 8px', fontSize: 12, lineHeight: 1.6 } },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '整包文件夹 → 自动分配工具'),
          h('div', { style: { marginBottom: 8, opacity: 0.9 } },
            '工具都在同一个文件夹（含子目录）时，填路径后点「自动分配」：会写入 toolkitDir，并按文件名匹配 nmap / nuclei / fscan 等填到下方。'),
          h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
            h('input', {
              className: 'rt-input', style: { flex: 1 },
              placeholder: '例如 D:\\pentest-tools 或 /opt/toolkit',
              value: folderPath,
              onChange: (e) => setFolderPath(e.target.value),
              onKeyDown: (e) => { if (e.key === 'Enter') assignFolder() },
            }),
            h('button', {
              className: 'rt-btn rt-btn-primary', disabled: busy || !draft || !!err,
              onClick: assignFolder,
            }, busy ? '扫描中…' : '自动分配'))),
        data && data.hint ? h('div', { className: 'rt-card', style: { margin: '0 0 8px', fontSize: 12, lineHeight: 1.6 } }, data.hint) : null,
        data && data.egress ? h('div', { className: 'rt-card', style: { margin: '0 0 8px', fontSize: 12, lineHeight: 1.55 } },
          h('div', { style: { fontWeight: 600, marginBottom: 6 } }, '出网状态（借鉴 Z3r0 egress，只读）'),
          h('div', { className: 'rt-mono', style: { fontSize: 11 } }, 'HTTP_PROXY=' + (data.egress.http_proxy || '(空)')),
          h('div', { className: 'rt-mono', style: { fontSize: 11 } }, 'HTTPS_PROXY=' + (data.egress.https_proxy || '(空)')),
          h('div', { className: 'rt-mono', style: { fontSize: 11 } }, 'ALL_PROXY=' + (data.egress.all_proxy || '(空)')),
          h('div', { className: 'rt-mono', style: { fontSize: 11 } }, 'NO_PROXY=' + (data.egress.no_proxy || '(空)')),
          h('div', { style: { marginTop: 6, opacity: 0.85 } }, data.egress.note || '')) : null,
        !draft ? h('div', { className: 'rt-empty' }, '加载中…') : h('div', null,
          h('div', { className: 'rt-card' },
            h('h4', null, '平台与目录'),
            h('div', { style: { display: 'grid', gap: 8 } },
              h('label', { style: { fontSize: 12 } }, '平台模式',
                h('select', {
                  className: 'rt-input', style: { display: 'block', width: '100%', marginTop: 4 },
                  value: draft.platform,
                  onChange: (e) => edit('platform', e.target.value),
                },
                  h('option', { value: 'auto' }, 'auto（跟随本机，默认）'),
                  h('option', { value: 'windows' }, 'windows'),
                  h('option', { value: 'linux' }, 'linux'))),
              h('label', { style: { fontSize: 12 } }, '工具箱目录 toolkitDir（留空＝默认）',
                h('input', {
                  className: 'rt-input', style: { display: 'block', width: '100%', marginTop: 4 },
                  placeholder: '默认：' + defaultToolkit,
                  value: draft.toolkitDir,
                  onChange: (e) => edit('toolkitDir', e.target.value),
                })),
              h('label', { style: { fontSize: 12 } }, 'nuclei 模板目录（留空＝自动：toolkit/nuclei-templates）',
                h('input', {
                  className: 'rt-input', style: { display: 'block', width: '100%', marginTop: 4 },
                  placeholder: '默认：' + defaultNuclei,
                  value: draft.nucleiTemplatesDir,
                  onChange: (e) => edit('nucleiTemplatesDir', e.target.value),
                })),
              h('label', { style: { fontSize: 12 } }, '工具搜索目录 binDirs（留空＝只搜 toolkit + PATH；每行一个）',
                h('textarea', {
                  className: 'rt-input', rows: 4, style: { display: 'block', width: '100%', marginTop: 4, fontFamily: 'var(--dsw-font-mono, monospace)' },
                  placeholder: '可选。例如：' + String.fromCharCode(10) + 'D:\\tools' + String.fromCharCode(10) + 'D:\\pentest-bin',
                  value: draft.binDirsText,
                  onChange: (e) => edit('binDirsText', e.target.value),
                })))),
          h('div', { className: 'rt-card' },
            h('h4', null, '密钥与 VPS（留空＝不覆盖；进程环境变量优先）'),
            h('div', { style: { display: 'grid', gap: 8 } },
              ['FOFA_KEY', 'REDTEAM_VPS_HOST', 'REDTEAM_VPS_KEY'].map((k) => h('label', { key: k, style: { fontSize: 12 } }, k + '（可选）',
                h('input', {
                  className: 'rt-input', style: { display: 'block', width: '100%', marginTop: 4 },
                  type: k === 'FOFA_KEY' ? 'password' : 'text',
                  placeholder: k === 'REDTEAM_VPS_KEY' ? '留空；需要时填私钥绝对路径' : (k === 'REDTEAM_VPS_HOST' ? '留空；需要时填 user@host' : '留空；测绘时再填'),
                  value: (draft.env && draft.env[k]) || '',
                  onChange: (e) => setEnv(k, e.target.value),
                }))))),
          h('div', { className: 'rt-card' },
            h('h4', null, '工具可执行文件（留空＝自动查找）'),
            h('div', { style: { fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 8 } },
              runtime.executionTarget === 'kali' ? '当前展示专用 SSH 工具入口。下方输入仍保存本机路径，切回本机后生效；远程缺失工具不会用本机替代。' : '解析顺序：本表绝对路径 → toolkitDir → binDirs → PATH。留空即走默认查找。'),
            tools.map((t) => h('div', { key: t.id, style: { marginBottom: 8 } },
              h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 } },
                h('span', { style: { fontWeight: 600, minWidth: 88 } }, t.label || t.id),
                t.path
                  ? h('span', { className: 'rt-tag rt-tag-live', title: t.path }, (t.source === 'kali' ? '远程 Kali' : t.source) + ' · 已找到')
                  : h('span', { className: 'rt-tag rt-tag-warn' }, '未找到（可留空等装好）')),
              h('input', {
                className: 'rt-input', style: { width: '100%' },
                placeholder: '留空自动找：' + (t.names || []).slice(0, 3).join(' / '),
                value: (draft.tools && draft.tools[t.id]) || '',
                onChange: (e) => setTool(t.id, e.target.value),
              }),
              t.path ? h('div', { className: 'rt-mono', style: { fontSize: 10.5, marginTop: 2, opacity: 0.8 } }, t.path + (t.remotePath ? ' → Kali ' + t.remotePath : '')) : null))),
          h('div', { className: 'rt-card' },
            h('h4', null, '备注'),
            h('textarea', {
              className: 'rt-input', rows: 3, style: { width: '100%' },
              placeholder: '可选。例如：工具来自某某绿色包',
              value: draft.notes,
              onChange: (e) => edit('notes', e.target.value),
            })),
          h('div', { className: 'rt-foot' },
            h('span', null,
              '配置文件：' + ((data && data.config && data.config.path) || '$DSH_HOME/redteam/config.json')
              + ' | 留空字段全部走默认')))))
    }

    /* ---------------------------------------------------------- 得分目标 */
    function ScoreTab(props) {
      const eng = props.engagement, refreshKey = props.refreshKey || 0
      const [snapshot, setData] = React.useState(null)
      const [error, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [opened, setOpened] = React.useState(null)
      const [editor, setEditor] = React.useState(null)
      const [message, setMessage] = React.useState(null)
      const [unconfirmed, setUnconfirmed] = React.useState(() => new Map())
      const noticeSequence = React.useRef(0)
      const [settled, setSettled] = React.useState(0)
      const generation = React.useRef(0), reader = React.useRef(null)
      const mounted = React.useRef(true), writing = React.useRef(new Map())
      const owner = React.useRef({ eng, refreshKey })
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      const view = owner.current
      const data = snapshot?.view === view && snapshot.token === generation.current ? snapshot : null
      const token = data?.token
      const valid = () => mounted.current && owner.current === view && token === generation.current
      const ready = !!data && !busy
      const form = data && editor?.view === view && editor.token === token ? editor.point : null
      const openId = data && opened?.view === view && opened.token === token ? opened.id : null
      const msg = message?.view === view ? message : null
      const unresolved = unconfirmed.get(eng)
      const dismissUnconfirmed = () => {
        if (!mounted.current || owner.current !== view || !unresolved) return
        setUnconfirmed(current => {
          if (current.get(eng)?.id !== unresolved.id) return current
          const next = new Map(current); next.delete(eng); return next
        })
      }
      const err = error?.view === view ? error.text : null
      const setMsg = value => { if (valid()) setMessage(value ? { ...value, view } : null) }
      const setForm = point => { if (ready && valid() && !writing.current.has(eng)) setEditor(point ? { point, view, token } : null) }
      const setOpenId = id => { if (ready && valid() && !writing.current.has(eng)) setOpened({ id, view, token }) }
      const load = () => {
        if (!eng || !mounted.current || owner.current !== view || writing.current.has(eng)) return
        const next = ++generation.current, controller = new AbortController()
        reader.current?.abort(); reader.current = controller
        setBusy(true); setData(null); setErr(null); setEditor(null); setOpened(null)
        const owns = () => mounted.current && owner.current === view && generation.current === next
        api({ op: 'scores', engagement: eng }, { signal: controller.signal }).then(r => {
          if (!owns()) return
          if (r?.ok !== true || !Array.isArray(r.items) || !r.summary || !r.items.every(p => p && Number.isSafeInteger(p.id) && p.id > 0 && Array.isArray(p.hits))) {
            setErr({ view, text: '当前项目得分记录未确认，请刷新核对。' }); return
          }
          setData({ ...r, view, token: next })
        }, () => { if (owns()) setErr({ view, text: '当前项目得分记录未确认，请刷新核对。' }) })
          .finally(() => { if (owns()) setBusy(false) })
      }
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; reader.current?.abort() } }, [])
      React.useEffect(() => {
        setBusy(writing.current.has(eng)); load()
        return () => { generation.current++; reader.current?.abort() }
      }, [eng, refreshKey, settled])

      React.useEffect(() => { setMessage(null) }, [eng, refreshKey])

      const startEdit = p => setForm({
        id: p.id, name: p.name, category: p.category || '', points: p.points,
        description: p.description || '', enabled: p.enabled, builtin: p.builtin === true,
        src: p.src, cap: p.cap, rule: p.rule,
      })
      const startNew = () => { setForm({ name: '', category: '', points: 10, description: '', enabled: true, builtin: false }); setMsg(null) }
      const setField = (k, v) => { if (form) setForm({ ...form, [k]: v }) }
      const mutate = remove => {
        if (!ready || !valid() || writing.current.has(eng) || !form) return
        if (remove && !form.id) return
        if (!remove && !form.name) { setMsg({ err: '名称不能为空' }); return }
        const operation = {}
        writing.current.set(eng, operation); setBusy(true); setMsg(null)
        const request = remove ? { op: 'deleteScorePoint', engagement: eng, id: form.id } : { op: 'saveScorePoint', engagement: eng, point: form }
        const settle = r => {
          if (writing.current.get(eng) !== operation) return
          writing.current.delete(eng)
          if (!mounted.current) return
          if (r?.ok !== true) {
            const id = ++noticeSequence.current
            setUnconfirmed(current => {
              const next = new Map(current); next.set(eng, { id, count: (current.get(eng)?.count || 0) + 1 }); return next
            })
          }
          if (owner.current.eng !== eng) return
          setBusy(false); setEditor(null); setOpened(null)
          const receipt = r?.ok !== true
            ? { err: '得分修改结果未确认，已只读刷新；未重发修改。' }
            : !remove && r.overridden === false
              ? { err: '已保存「启用/停用」。分值未改动：内置得分点由规则锁定；自定义分值请使用「+ 新增得分点」。' }
              : { ok: remove ? '已删除' : r.note || '已保存' }
          setMessage(r?.ok === true ? { ...receipt, view: owner.current } : null)
          setSettled(value => value + 1)
        }
        api(request).then(settle, () => settle(null))
      }
      const save = () => mutate(false)
      const remove = () => mutate(true)

      const summary = (data && data.summary) || { achievedPoints: 0, pointCount: 0, hitPointCount: 0, hitCount: 0, selfCreatedHits: 0, serviceCappedHits: 0 }
      const items = (data && data.items) || []

      /* 按合并版的 8 个类别分组渲染（后端 ruleGroups 已排好序、组内按分值升序）。
         兼容：后端没给 ruleGroups（老 host）时退回平铺。 */
      const groups = (data && data.ruleGroups && data.ruleGroups.length)
        ? data.ruleGroups
        : [{ key: 'all', name: '', capSum: 0, points: 0, counted: 0, tiers: items }]
      const rows = []
      for (const g of groups) {
        if (g.name) {
          rows.push(h('div', { key: 'g-' + g.key, className: 'rt-score-group' },
            h('span', null, g.name),
            h('span', { className: 'rt-sg-sub' },
              g.tiers.length + ' 项'
              + (g.capSum > 0 ? ' · 各项上限合计 ' + g.capSum + ' 分（各项独立，不跨项累加）' : '')),
            h('div', { className: 'rt-spacer' }),
            g.points > 0
              ? h('span', { className: 'rt-tag rt-tag-active' }, '+' + g.points + ' 分')
              : null))
        }
        for (const p of g.tiers) {
        const achieved = p.hits.length > 0
        const open = openId === p.id
        rows.push(h('div', {
          key: 'sp' + p.id, className: 'rt-score-row', role: 'button', tabIndex: 0,
          onClick: () => setOpenId(open ? null : p.id),
          onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenId(open ? null : p.id) } },
        },
          h('span', { className: 'rt-sec-caret' }, open ? '▾' : '▸'),
          h('span', null, h('span', {
            className: achieved ? 'rt-pri rt-pri-high' : 'rt-pri rt-pri-low',
            style: achieved ? {} : { background: 'var(--dsw-alias-bg-layer-2)', color: 'var(--dsw-alias-label-secondary)' },
          }, p.points + '分')),
          h('span', { title: p.description || '' },
            p.name,
            p.tier ? h('span', { className: 'rt-scope' }, '　' + p.tier) : null),
          /* 命中与上限：这一条计入几次、上限用了多少（G3 各项上限独立，到顶就不再累计） */
          h('span', { title: p.capped > 0
            ? '已计入 ' + p.counted + ' 次，另有 ' + p.capped + ' 条因「' + (p.scope_label || '计分口径') + '」或已达上限不计分'
            : (p.scope_label || '') },
            h('span', { className: 'rt-sec-count' }, p.hits.length > 0 ? p.counted + ' 次命中' : '未命中'),
            p.cap > 0
              ? h('span', { className: 'rt-scope' }, '　上限 ' + (p.cap_used === null ? 0 : p.cap_used) + '/' + p.cap)
              : null),
          h('span', { style: { textAlign: 'right' } }, p.earned > 0
            ? h('span', { className: 'rt-tag rt-tag-active' }, '+' + p.earned + ' 分')
            : h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } }, '—'))))
        if (!open) continue
        /* 命中记录：一行一条 —— 第一行给"序号 + 资产 + 时间 + 复制"，内容另起一行自适应换行 */
        const hitNodes = p.hits.map((hh, hi) => h('div', {
          key: 'h' + hh.id,
          className: 'rt-hit-row' + (hh.self_created ? ' self-created' : '') + (hh.capped ? ' service-capped' : ''),
        },
          h('span', { className: 'rt-hit-idx' }, String(hi + 1)),
          h('span', { className: 'rt-hit-asset', title: hh.target || hh.asset_ip || '' },
            hh.asset_ip || hh.target || '未指定资产'),
          hh.self_created ? h('span', { className: 'rt-tag rt-tag-warn', title: '自己注册/自建的账号不算得分权限，只作过程记录' }, '自建 · 不计分') : null,
          hh.capped ? h('span', {
            className: 'rt-tag rt-tag-warn',
            title: hh.capped_reason || '同一资产同一端口只算分值最高的一条，这条不计分',
          }, '服务已拿满 · 不计分' + (hh.service ? '（' + hh.service + '）' : '')) : null,
          hh.shot_count ? h('span', { className: 'rt-tag', title: '这条命中有证据截图（展开得分点即可看到代表图）' },
            '图 ' + hh.shot_count) : null,
          h('span', { className: 'rt-hit-time' }, fmt(hh.recorded_at)),
          h('button', {
            className: 'rt-btn', style: { padding: '0 5px', fontSize: 10.5 },
            title: '复制这一条',
            onClick: (e) => {
              e.stopPropagation()
              copyText((hh.asset_ip || hh.target || '') + '  ' + (hh.evidence || ''))
            },
          }, '复制'),
          hh.evidence
            ? h('span', { className: 'rt-hit-txt', title: hh.evidence }, String(hh.evidence).replace(/\n+/g, ' '))
            : h('span', { className: 'rt-hit-txt none' }, '未填账号密码/结果')))
        rows.push(h('div', {
          key: 'spd' + p.id, className: 'rt-score-row',
          style: { cursor: 'default', gridTemplateColumns: '1fr' },
        }, h('div', { className: 'rt-score-detail' },
          p.description ? h('div', { className: 'rt-kv' }, h('b', null, '得分条件'), h('span', null, p.description)) : null,
          h('div', { className: 'rt-kv' }, h('b', null, '状态'),
            h('span', null, (p.enabled ? '启用' : '停用') + ' · ' + p.points + ' 分/次 · 命中 ' + p.hits.length +
              ' 次 = ' + p.earned + ' 分' + (p.self_created ? '（另有 ' + p.self_created + ' 次自建不计分）' : '') +
              (p.capped ? '（另有 ' + p.capped + ' 次同服务重复命中不计分）' : ''))),
          p.capped
            ? h('div', { className: 'rt-kv' }, h('b', null, '服务封顶'),
                h('span', null, p.service_summary + '；账号权限与数据库权限按「同资产同端口」只算一次，拿到最高权限账号即该服务拿满'))
            : null,
          p.hits.length
            ? h('div', null,
                h(ShotStrip, { eng: eng, shots: p.shots, total: p.shot_total,
                  title: '证据截图 · ' + (p.shot_total || (p.shots || []).length) + ' 张' }),
                h('div', { className: 'rt-section', style: { padding: '6px 0 0' } },
                  '命中记录 · ' + p.hits.length + '（只记资产与账号密码，详细复现见报告）'),
                h('div', { className: 'rt-hits' }, hitNodes))
            : h('div', { className: 'rt-kv' }, h('b', null, '命中记录'),
                h('span', { style: { color: 'var(--dsw-alias-label-secondary)' } },
                  '还没有 —— 拿下成果后用 redteam_score_hit 记分：写明目标资产 + 拿到的账号密码/权限')),
          h('div', { className: 'rt-actions' },
            h('button', { className: 'rt-btn', onClick: (e) => { e.stopPropagation(); startEdit(p) } }, '编辑')))))
        }
      }

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '得分目标'),
          /* 只显示已拿下的总分，不显示目标分数、不显示进度条 */
          h('span', { style: { fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginLeft: 4 } }, '总分'),
          h('span', { className: 'rt-total' }, data ? String(summary.achievedPoints) : '?'),
          h('span', { style: { fontSize: 13, color: 'var(--dsw-alias-label-secondary)' } }, '分'),
          h('span', { className: 'rt-tag' }, data ? summary.pointCount + ' 个得分点' : '得分点待核对'),
          h('span', { className: 'rt-tag' }, data ? '命中 ' + summary.countedHits + ' 次' : '命中待核对'),
          summary.selfCreatedHits
            ? h('span', {
                className: 'rt-tag rt-tag-warn',
                title: '自己注册/自己创建的账号不算得分权限，只作过程记录（不计分、不占上限、不进报告）',
              }, '自建不计分 ' + summary.selfCreatedHits)
            : null,
          summary.serviceCappedHits
            ? h('span', {
                className: 'rt-tag rt-tag-warn',
                title: '账号权限与数据库权限按「同资产同端口」只算一次：该服务已拿满，这些重复命中不计分（只作留痕）',
              }, '服务已拿满不计分 ' + summary.serviceCappedHits)
            : null,
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn', disabled: !ready, onClick: startNew }, '+ 新增得分点'),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, busy ? '刷新中…' : '刷新')),
        !data ? h('div', { className: 'rt-note', role: 'status' }, busy ? '正在核对当前项目得分记录…' : '当前项目得分记录未确认，请刷新核对。') : null,
        unresolved ? h('div', { className: 'rt-err', role: 'status' },
          '有 ' + unresolved.count + ' 笔得分修改结果未确认；只读刷新不会补造成功回执，也未重发修改。请核对记录。关闭仅隐藏提示，不代表修改成功。',
          h('button', { className: 'rt-btn', onClick: dismissUnconfirmed }, '关闭未确认提示')) : null,
        msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        err ? h('div', { className: 'rt-err' }, err) : null,
        form ? h('div', { className: 'rt-pane', style: { flex: 'none', borderBottom: '1px solid var(--dsw-alias-border-l1)' } },
          /* 内置得分点（builtin）：分值 / 名称 / 分类由《得分规则》锁定，输入框置灰。
             可改的只有「启用 / 停用」。这样界面上就不会再出现「改完提示已保存、刷新变回去」的困惑。 */
          form.builtin
            ? h('div', { className: 'rt-hint', style: { marginBottom: 8 } },
                h('b', null, '内置得分点（来自《突破入侵类得分规则（合并版）》）'),
                h('div', { style: { marginTop: 3 } },
                  '分值、上限、计分口径与名称由规则锁定 —— 同一条规则的上限按组内所有得分点累计，'
                  + '单独改分值会让一条命中吃掉整组上限。这里可以改「启用 / 停用」；'
                  + '要自定义分值时请返回上一屏点「+ 新增得分点」。'),
                form.src !== null && form.src !== undefined
                  ? h('div', { style: { marginTop: 3, color: 'var(--dsw-alias-label-secondary)' } },
                      '规则原文序号 ' + form.src + (form.rule ? '　·　上限分组 rule=' + form.rule : '')
                      + (form.cap > 0 ? '　·　上限 ' + form.cap + ' 分' : '　·　不设上限'))
                  : null)
            : null,
          h('div', { className: 'rt-score-form' },
            h('input', {
              className: 'rt-input', placeholder: '名称（必填）', value: form.name,
              readOnly: form.builtin === true,
              title: form.builtin ? '内置得分点的名称由规则锁定' : '',
              onChange: (e) => setField('name', e.target.value),
            }),
            h('input', {
              className: 'rt-input', placeholder: '分类，如 账号权限', value: form.category,
              readOnly: form.builtin === true,
              title: form.builtin ? '内置得分点的分类由规则锁定（决定它属于面板哪一组）' : '',
              onChange: (e) => setField('category', e.target.value),
            }),
            h('input', {
              className: 'rt-input', type: 'number', placeholder: '单次分值',
              readOnly: form.builtin === true,
              title: form.builtin
                ? '内置得分点的分值由《得分规则》锁定，不能在这里改'
                : '这一类的单次分值；每命中一次就按这个分值累加（受该条规则上限约束）',
              value: form.points, onChange: (e) => setField('points', Number(e.target.value)),
            }),
            h('select', { className: 'rt-input', value: form.enabled ? '1' : '0', onChange: (e) => setField('enabled', e.target.value === '1') },
              h('option', { value: '1' }, '启用'),
              h('option', { value: '0' }, '停用'))),
          h('input', {
            className: 'rt-input', style: { width: '100%', marginBottom: 6, boxSizing: 'border-box' },
            placeholder: '得分条件说明', value: form.description,
            readOnly: form.builtin === true,
            title: form.builtin ? '内置得分点的条款正文由规则锁定' : '',
            onChange: (e) => setField('description', e.target.value),
          }),
          h('div', { className: 'rt-actions' },
            h('button', { className: 'rt-btn rt-btn-primary', disabled: busy, onClick: save }, '保存'),
          form.id
            ? (form.builtin
                ? h('button', {
                    className: 'rt-btn', disabled: true,
                    title: '内置得分点不能删除：删掉会让面板缺一条规则、报告少一类成果（下次启动还会自动补回来）。要让它不参与计分请改用「停用」。',
                  }, '删除（内置项不可删）')
                : h('button', { className: 'rt-btn', disabled: busy, onClick: remove }, '删除'))
            : null,
            h('button', { className: 'rt-btn', onClick: () => setForm(null) }, '取消'))) : null,
        h('div', { className: 'rt-table' },
          h('div', { className: 'rt-score-row head' },
            h('span', null, ''), h('span', null, '分值'), h('span', null, '得分点（按分值从低到高）'),
            h('span', null, '命中 / 上限'), h('span', { style: { textAlign: 'right' } }, '已得分')),
          rows,
          data && !items.length ? h('div', { className: 'rt-empty' }, '暂无得分点，点右上角「新增得分点」') : null))
    }

    /* ---------------------------------------------------------- 折叠底座 */
    /**
     * 折叠状态按「页签 + 靶标」持久化到 localStorage，切页签/刷新后保持不变。
     * 只记录用户显式点过的键；没点过的用调用方给的默认值。
     */
    const COLLAPSE_KEY = 'rt-collapse:'
    const collapseLoad = (prefix) => {
      try {
        const raw = window.localStorage.getItem(COLLAPSE_KEY + prefix)
        const parsed = raw ? JSON.parse(raw) : null
        return parsed && typeof parsed === 'object' ? parsed : {}
      } catch (e) { return {} }
    }
    const collapseSave = (prefix, value) => {
      try { window.localStorage.setItem(COLLAPSE_KEY + prefix, JSON.stringify(value)) } catch (e) { /* 隐私模式等 */ }
    }

    /** 一个页签一个 hook：isOpen(key, defaultOpen) / toggle(key, defaultOpen) / setAll(keys, open) */
    function useCollapse(prefix) {
      const [state, setState] = React.useState(() => collapseLoad(prefix))
      React.useEffect(() => { setState(collapseLoad(prefix)) }, [prefix])
      const write = (next) => { collapseSave(prefix, next); setState(next) }
      const isOpen = (key, defaultOpen) => {
        const v = state[key]
        return v === undefined ? defaultOpen !== false : v === true
      }
      const toggle = (key, defaultOpen) => (e) => {
        if (e && e.stopPropagation) e.stopPropagation()
        write(Object.assign({}, state, { [key]: !isOpen(key, defaultOpen) }))
      }
      const setAll = (keys, open) => {
        const next = Object.assign({}, state)
        for (const k of keys) next[k] = open
        write(next)
      }
      return { isOpen: isOpen, toggle: toggle, setAll: setAll }
    }

    /**
     * 统一折叠头（L1）：▾ 固定在最左、标题加粗、计数紧跟、右侧放时间或操作，
     * 内容缩进 12px 并带一条竖引导线。always=true 表示"常显"（不可折叠）。
     */
    function Section(props) {
      const always = props.always === true
      const open = always || props.open === true
      const head = h('div', {
        className: 'rt-sec t-' + (props.tone || 'target') + (always ? ' flat' : ''),
        role: always ? undefined : 'button',
        tabIndex: always ? undefined : 0,
        'aria-expanded': always ? undefined : (open ? 'true' : 'false'),
        onClick: always ? undefined : props.onToggle,
        onKeyDown: always ? undefined : (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (props.onToggle) props.onToggle(e) }
        },
      },
        h('span', { className: 'rt-sec-caret' }, always ? '▍' : (open ? '▾' : '▸')),
        props.title ? h('span', { className: 'rt-sec-title' }, props.title) : null,
        props.count !== undefined && props.count !== null ? h('span', { className: 'rt-sec-count' }, String(props.count)) : null,
        props.sub ? h('span', { className: 'rt-sec-sub' }, props.sub) : null,
        props.right ? h('span', { className: 'rt-sec-right' }, props.right) : null)
      return h('div', { className: 'rt-sec-wrap' }, head,
        open && props.children ? h('div', { className: 'rt-sec-body' }, props.children) : null)
    }

    /** 长文本折叠（L3）：固定预览高度 + 渐隐 + 展开/复制。 */
    function Clip(props) {
      const [open, setOpen] = React.useState(false)
      const text = String(props.text === undefined || props.text === null ? '' : props.text)
      if (text.trim() === '') return null
      return h('div', { className: 'rt-clip' + (open ? ' open' : '') },
        h('div', { className: 'rt-clip-head' },
          props.label ? h('span', { className: 'rt-clip-label' }, props.label) : null,
          h('div', { className: 'rt-spacer' }),
          h('button', {
            className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
            onClick: (e) => { e.stopPropagation(); copyText(text) },
          }, '复制'),
          h('button', {
            className: 'rt-btn', style: { padding: '0 6px', fontSize: 11 },
            onClick: (e) => { e.stopPropagation(); setOpen((v) => !v) },
          }, open ? '收起' : '展开')),
        h('div', { className: 'rt-clip-body' }, text))
    }

    /* ---------------------------------------------------------- 当前测试（实时） */
    const TEST_STATUS_LABEL = {
      untested: '未测试', testing: '测试中', tested: '已测试',
      blocked: '被封禁', abandoned: '已放弃', no_surface: '无攻击面',
    }

    /**
     * 当前测试页：agent 正在打哪台、打到哪一步、还有什么在排队。
     * 5 秒轮询自动刷新；三个区块可折叠，其中「正在测」始终完整展开。
     */
    function TestingTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [at, setAt] = React.useState(null)
      const [auto, setAuto] = React.useState(true)
      /* 折叠状态按「页签 + 靶标」记忆；正在测永远常显，不参与折叠 */
      const collapse = useCollapse('testing:' + eng)

      /* 5 秒轮询要有在途守卫：网络慢或后端卡住时，请求会越堆越多、
         而且旧响应回来会覆盖新状态（界面上表现为数字来回跳）。 */
      const inflight = React.useRef(null)
      const seq = React.useRef(0)
      const load = () => {
        if (!eng || inflight.current) return
        const controller = new AbortController()
        inflight.current = controller
        const my = ++seq.current
        api({ op: 'activeTests', engagement: eng, limit: 20 }, { signal: controller.signal }).then((r) => {
          if (my !== seq.current) return          /* 切了靶标：这条已经过期，丢掉 */
          if (!r || r.ok === false) { setErr((r && r.error) || '读取失败'); return }
          setErr(null); setData(r); setAt(new Date())
        }, (e) => { if (my === seq.current) setErr(String((e && e.message) || e)) })
          .finally(() => { if (inflight.current === controller) inflight.current = null })
      }
      React.useEffect(() => {
        seq.current += 1
        setData(null); setErr(null); setAt(null)
        load()
        return () => {
          seq.current += 1
          const controller = inflight.current
          inflight.current = null
          controller?.abort()
        }
      }, [eng, refreshKey])
      React.useEffect(() => {
        if (!eng || !auto) return undefined
        const timer = setInterval(load, 5000)
        return () => clearInterval(timer)
      }, [eng, auto, refreshKey])

      const testing = (data && data.testing) || []
      const recent = (data && data.recent) || []
      const queue = (data && data.queue) || []
      const stats = (data && data.stats) || {}

      /* 一台资产一张卡：一眼看清"打的是谁、打到哪、拿到什么" */
      const card = (a, past) => {
        const chips = []
        chips.push(h('span', { key: 'sc', className: 'rt-scope rt-scope-' + (a.scope === 'internal' ? 'internal' : 'external') },
          a.scope === 'internal' ? '内网' : '外网'))
        if (a.segment_cidr) chips.push(h('span', { key: 'seg', className: 'rt-tag' }, a.segment_cidr))
        if (a.open_ports) chips.push(h('span', { key: 'p', className: 'rt-tag rt-tag-active' }, '开放 ' + a.open_ports + ' 端口'))
        if (a.vulns) chips.push(h('span', { key: 'v', className: 'rt-tag rt-tag-live' }, '已确认漏洞 ' + a.vulns))
        if (a.webshells) chips.push(h('span', { key: 'w', className: 'rt-tag rt-tag-passive' }, 'WebShell ' + a.webshells))
        if (a.tunnels) chips.push(h('span', { key: 't', className: 'rt-tag rt-tag-passive' }, '隧道 ' + a.tunnels))
        if (a.priority) chips.push(h('span', { key: 'pr', className: 'rt-tag' }, '易打 ' + a.priority))
        if (a.blocked_count) chips.push(h('span', { key: 'b', className: 'rt-tag', style: { color: '#ef4444', borderColor: '#ef444455' } }, '被封 ' + a.blocked_count + ' 次'))
        const noteLines = a.test_notes
          ? String(a.test_notes).split('\n').slice(-3).map((l) => (l.length > 240 ? l.slice(0, 240) + ' …' : l))
          : []
        return h('div', { key: 'at' + a.id, className: 'rt-atest' + (past ? ' past' : '') },
          h('div', { className: 'rt-atest-head' },
            past ? null : h('span', { className: 'rt-live-dot' }),
            h('span', { className: 'rt-atest-ip' }, a.ip),
            h('span', { className: 'rt-tag ' + (a.test_status === 'testing' ? 'rt-tag-live' : '') }, TEST_STATUS_LABEL[a.test_status] || a.test_status),
            h('div', { className: 'rt-spacer' }),
            h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } },
              fmt(a.test_updated_at) + (a.test_updated_by ? ' · ' + a.test_updated_by : ''))),
          chips.length ? h('div', null, chips) : null,
          a.test_surface ? h('div', { className: 'rt-atest-meta' }, '测试面：' + a.test_surface) : null,
          a.potential ? h('div', { className: 'rt-atest-meta' }, '预期得分：' + a.potential) : null,
          noteLines.length ? h(Clip, { label: '测试记录', text: noteLines.join('\n') }) : null)
      }


      const concl = (label, value, tone) => h('span', { key: label, className: 'rt-concl-i', style: { cursor: 'default' } },
        h('b', null, String(value || 0)), h('span', null, label))
      const conclusion = h('div', { className: 'rt-concl' },
        concl('测试中', stats.testing, 'live'),
        concl('待测', stats.untested, ''),
        concl('已测', stats.tested, ''),
        concl('放弃', (stats.abandoned || 0) + (stats.blocked || 0), ''),
        concl('无攻击面', stats.no_surface, ''),
        h('div', { className: 'rt-spacer' }),
        at ? h('span', { style: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)' } },
          '更新于 ' + at.toLocaleTimeString('zh-CN', { hour12: false })) : null,
        h('button', {
          className: 'rt-btn', style: { padding: '0 7px', fontSize: 11 }, title: '展开最近动过与待测队列',
          onClick: () => collapse.setAll(['testing:' + eng, 'recent:' + eng, 'queue:' + eng], true),
        }, '全部展开'),
        h('button', {
          className: 'rt-btn', style: { padding: '0 7px', fontSize: 11 }, title: '只留正在测',
          onClick: () => collapse.setAll(['testing:' + eng, 'recent:' + eng, 'queue:' + eng], false),
        }, '全部收起'),
        h('button', {
          className: 'rt-btn' + (auto ? ' rt-btn-primary' : ''), style: { padding: '0 7px', fontSize: 11 },
          title: '每 5 秒自动刷新', onClick: () => setAuto((x) => !x),
        }, auto ? '实时 · 5s' : '已暂停'),
        h('button', { className: 'rt-btn', style: { padding: '0 7px', fontSize: 11 }, onClick: load }, '刷新'))

      const body = []
      /* 正在测：常显，完整展开（不可折叠） */
      body.push(h(Section, {
        key: 'testing', tone: 'test', title: '正在测',
        count: testing.length + ' 台',
        sub: testing.length ? 'agent 正在打这些资产' : 'agent 开始测某台资产后会实时出现在这里',
        open: collapse.isOpen('testing:' + eng, true),
        onToggle: collapse.toggle('testing:' + eng, true),
      }, testing.length
        ? testing.map((a) => card(a, false))
        : h('div', { className: 'rt-atest-meta', style: { paddingBottom: 4 } }, '当前没有资产处于「测试中」')))

      /* 最近动过（默认折叠，可记忆） */
      body.push(h(Section, {
        key: 'recent', tone: 'past', title: '最近动过', count: recent.length + ' 台',
        sub: '已测过的资产',
        open: collapse.isOpen('recent:' + eng, false),
        onToggle: collapse.toggle('recent:' + eng, false),
      }, recent.length ? recent.map((a) => card(a, true)) : h('div', { className: 'rt-atest-meta' }, '暂无')))

      /* 待测队列（默认折叠，可记忆） */
      body.push(h(Section, {
        key: 'queue', tone: 'queue', title: '待测队列',
        count: (data ? (data.untested || 0) : 0) + ' 台',
        sub: '按易打性与端口数排出先打哪几台',
        open: collapse.isOpen('queue:' + eng, false),
        onToggle: collapse.toggle('queue:' + eng, false),
      }, queue.length
        ? queue.map((a) => card(a, true)).concat([
            h('div', { key: 'queueHint', className: 'rt-atest-meta', style: { paddingTop: 4 } },
              '完整清单（含筛选与排序）见「资产测绘」页')])
        : h('div', { className: 'rt-atest-meta' }, '没有待测资产')))

      return h('div', { className: 'rt-main' },
        conclusion,
        err ? h('div', { className: 'rt-err' }, err) : null,
        data === null && !err ? h('div', { className: 'rt-empty' }, '加载中…') : null,
        h('div', { className: 'rt-body', style: { overflow: 'auto' } },
          h('div', { style: { padding: '6px 12px 14px' } }, body)))
    }

    /* ---------------------------------------------------------- 会话与入口（WebShell / 隧道） */
    /**
     * 打内网最容易出的问题：拿到 WebShell 或隧道之后忘了登记，过一会儿就"忘了还有入口可用"。
     * 这个页签把事实库里的 WebShell 与隧道集中展示，带连通状态，并可一键让 host 侧实测。
     */
    // Accept a whole snapshot before exposing any records or actions. Missing data is unknown.
    function validSessionSnapshot(value) {
      const record = v => v !== null && typeof v === 'object' && !Array.isArray(v)
      const count = v => Number.isSafeInteger(v) && v >= 0
      if (!record(value) || value.ok !== true || !Array.isArray(value.webshells) || !Array.isArray(value.tunnels) || !record(value.totals)) return false
      const fields = ['url', 'shell_type', 'privilege', 'asset_ip', 'secret_ref', 'check_note', 'note', 'pass_key', 'status', 'listen', 'kind', 'entry_kind_label', 'entry_kind', 'reach', 'entry', 'command']
      const rowsValid = rows => {
        const ids = new Set()
        return rows.every(row => {
          if (!record(row) || !Number.isSafeInteger(row.id) || row.id <= 0 || ids.has(row.id)) return false
          ids.add(row.id)
          return fields.every(key => row[key] == null || typeof row[key] === 'string')
            && (row.legit == null || typeof row.legit === 'boolean')
            && (row.last_check == null || typeof row.last_check === 'string' || (typeof row.last_check === 'number' && Number.isFinite(row.last_check)))
            && (row.latency_ms == null || (typeof row.latency_ms === 'number' && Number.isFinite(row.latency_ms) && row.latency_ms >= 0))
        })
      }
      if (!rowsValid(value.webshells) || !rowsValid(value.tunnels)) return false
      const t = value.totals, shells = value.webshells, tunnels = value.tunnels
      return ['webshells', 'webshellsOnline', 'tunnels', 'tunnelsActive', 'tunnelsLegit', 'tunnelsSelfOnly', 'credentials', 'access'].every(key => count(t[key]))
        && t.webshells === shells.length && t.webshellsOnline === shells.filter(row => row.status === 'online').length
        && t.tunnels === tunnels.length && t.tunnelsActive === tunnels.filter(row => row.status === 'active').length
        && t.tunnelsLegit === tunnels.filter(row => row.legit === true).length
        && t.tunnelsSelfOnly === tunnels.filter(row => row.legit === false).length
    }

    function SessionTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [data, setData] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [msg, setMsg] = React.useState(null)
      const [copied, setCopied] = React.useState(null)
      const [loading, setLoading] = React.useState(true)
      const generation = React.useRef(0), reader = React.useRef(null)
      const mounted = React.useRef(true), writing = React.useRef(false)
      const owner = React.useRef({ eng, refreshKey })
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      const view = owner.current
      const current = data?.view === view && data.token === generation.current ? data : null
      const token = current?.token
      const valid = () => mounted.current && owner.current === view && token === generation.current
      const ready = !!current && !loading && !busy
      const load = () => {
        if (!eng || owner.current !== view || !mounted.current || writing.current) return
        const next = ++generation.current, controller = new AbortController()
        reader.current?.abort(); reader.current = controller
        setData(null); setErr(null); setLoading(true); setCopied(null)
        const ownsRead = () => mounted.current && owner.current === view && generation.current === next
        api({ op: 'sessions', engagement: eng }, { signal: controller.signal }).then(r => {
          if (!ownsRead()) return
          if (!validSessionSnapshot(r)) { setErr({ view, text: '当前项目记录读取未确认，请刷新核对。' }); return }
          setData({ ...r, view, token: next })
        }, () => { if (ownsRead()) setErr({ view, text: '当前项目记录读取未确认，请刷新核对。' }) })
          .finally(() => { if (ownsRead()) setLoading(false) })
      }
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; reader.current?.abort() } }, [])
      React.useEffect(() => {
        writing.current = false; setBusy(false); setMsg(null); load()
        return () => { generation.current++; reader.current?.abort() }
      }, [eng, refreshKey])

      /* 只有真的写进剪贴板才把按钮点亮成「已复制」；失败时如实报错 */
      const copy = (key, value) => {
        if (!ready || !valid() || writing.current) return
        copyWithFeedback(value, value, (okFlag, message) => {
          if (!valid()) return
          if (!okFlag) { setMsg({ err: message, view }); return }
          setCopied(key)
          setTimeout(() => { if (valid()) setCopied(c => c === key ? null : c) }, 1500)
        })
      }
      const mark = (op, row, status) => {
        if (!ready || !valid() || writing.current) return
        writing.current = true; setBusy(true); setMsg(null)
        const settle = failed => {
          if (!valid()) return
          writing.current = false; setBusy(false)
          setMsg({ err: failed ? '标记结果未确认，已只读刷新；未重发修改。' : null, view })
          load()
        }
        api({ op, engagement: eng, id: row.id, patch: { status, check_note: '界面手动标记' } })
          .then(r => settle(r?.ok !== true), () => settle(true))
      }
      const markTunnel = (row, status) => mark('updateTunnel', row, status)
      const markShell = (row, status) => mark('updateWebshell', row, status)

      const sessCollapse = useCollapse('sessions:' + eng)
      const totals = current?.totals || {}
      const shells = current?.webshells || []
      const tunnels = current?.tunnels || []
      const statusDot = (s) => h('span', { className: s === 'online' || s === 'active' ? 'rt-dot-on' : (s === 'unknown' || !s ? 'rt-dot-unk' : 'rt-dot-off') })
      /* 卡片里统一用「标签 + 值」两列，长文本自动换行 —— 比一行点分隔好扫读 */
      const fact = (label, value) => h('div', { className: 'rt-sess-fact' }, h('b', null, label), h('span', null, value))
      /* 交付要求：马必须是冰蝎/哥斯拉加密马（用户才连得上），内网必须走 suo5 隧道 */
      const isEncryptedShell = (t) => /behinder|godzilla|冰蝎|哥斯拉/i.test(String(t || ''))
      const isSuo5 = (t) => /suo5/i.test(String(t || ''))
      /* 提示条：只留一句结论 + 可展开的做法（原来是把三段长解释平铺，正文全被淹掉） */
      const hint = (key, title, detail) => h('div', { key, className: 'rt-hint' },
        h('b', null, title),
        h('details', { className: 'rt-sess-fold', style: { marginTop: 3 } },
          h('summary', null, '怎么做（点击展开）'),
          h('div', { style: { marginTop: 4 } }, detail)))
      const hints = []
      const badShells = shells.filter((w) => !isEncryptedShell(w.shell_type))
      const legitTunnels = tunnels.filter((t) => t.legit === true)
      if (badShells.length > 0) {
        hints.push(hint('h1', '有 ' + badShells.length + ' 个入口不是冰蝎马/哥斯拉马（用户连不上，不算可交付入口）',
          '用技能 webshell-toolkit 重新上传冰蝎马（behinder）或哥斯拉马（godzilla），'
          + '并把 shell_type + pass_key 写进 redteam_webshell_add。只作临时中转的可在备注里写明。'))
      }
      if (tunnels.length > 0 && legitTunnels.length === 0) {
        hints.push(hint('h3', '现有 ' + tunnels.length + ' 条通道都不算"跨越靶标边界"（不算边界/内网突破）',
          '自己的 VPS / 自建服务器上开的 socks5、frp、代理不算隧道。必须是目标侧发起的通道：'
          + '目标反弹 shell 到我方、目标上跑 frp/Stowaway 客户端、或经目标 WebShell 建的 suo5/HTTP 隧道；登记时用 entry_kind 说明。'))
      }
      const activeSuo5 = tunnels.filter((t) => isSuo5(t.kind) && t.status === 'active')
      if (shells.length > 0 && activeSuo5.length === 0) {
        hints.push(hint('h2', '还没有可用的 suo5 隧道（打进内网的标准通道）',
          '用技能 suo5-tunnel 通过上面的 WebShell 建 socks5 隧道，再 redteam_tunnel_add'
          + '（kind=suo5、listen=127.0.0.1:1080、entry=WebShell URL、reach=可达网段）登记，'
          + '需要核实状态时，请在会话中说明目标和范围，使用已授权工具检测后再更新记录。'))
      }

      const shellCards = shells.map((w) => h('div', { key: 'w' + w.id, className: 'rt-sess' },
        h('div', { className: 'rt-sess-head' },
          statusDot(w.status),
          h('span', { className: 'rt-sess-title' }, w.url),
          h('span', { className: 'rt-tag rt-tag-active' }, w.shell_type || 'webshell'),
          isEncryptedShell(w.shell_type) ? null : h('span', { className: 'rt-tag rt-tag-warn' }, '用户连不上'),
          w.privilege ? h('span', { className: 'rt-tag' }, w.privilege) : null,
          h('div', { className: 'rt-spacer' }),
          copied === 'cmd' + w.id
            ? h('span', { className: 'rt-tag', style: { color: '#10b981' } }, '已复制')
            : h('button', {
                className: 'rt-btn', disabled: busy || !ready, style: { padding: '0 6px', fontSize: 11 },
                onClick: () => copy('cmd' + w.id, w.url || ''),
              }, '复制 URL'),
          h('button', {
            className: 'rt-btn', disabled: busy || !ready, style: { padding: '0 6px', fontSize: 11 },
            onClick: () => markShell(w, 'offline'),
          }, '标记失效')),
        h('div', { className: 'rt-sess-facts' },
          fact('类型', (isEncryptedShell(w.shell_type) ? '加密马（冰蝎/哥斯拉，用户可直连）' : '非加密马 —— 用户连不上，仅可作临时中转')),
          w.pass_key ? fact('连接口令', h('span', { className: 'rt-mono' }, '[已隐藏]')) : null,
          w.asset_ip ? fact('所在资产', w.asset_ip) : null,
          w.privilege ? fact('权限', w.privilege) : null,
          w.secret_ref ? fact('凭据引用', h('span', { className: 'rt-mono' }, w.secret_ref)) : null,
          fact('最后检测', (w.last_check ? fmt(w.last_check) : '未检测')
            + (w.latency_ms !== null && w.latency_ms !== undefined ? '（' + w.latency_ms + 'ms）' : '')),
          w.check_note ? fact('检测说明', w.check_note) : null,
          w.note ? fact('备注', w.note) : null)))

      const tunnelCards = tunnels.map((t) => {
        const proxy = t.listen ? 'socks5://' + t.listen : ''
        const gogoCmd = t.listen ? './gogo -i <内网CIDR> -m ss --ping -p top2,win,db --proxy ' + proxy : ''
        const fscanCmd = t.listen ? './fscan -h <内网CIDR> -np -nobr -nopoc -socks5 ' + t.listen + ' -o intranet.txt' : ''
        return h('div', { key: 't' + t.id, className: 'rt-sess' },
          h('div', { className: 'rt-sess-head' },
            statusDot(t.status),
            h('span', { className: 'rt-sess-title' }, t.listen || '(未填监听地址)'),
            h('span', { className: 'rt-tag rt-tag-passive' }, t.kind || 'tunnel'),
            isSuo5(t.kind) ? null : h('span', { className: 'rt-tag rt-tag-warn' }, '非 suo5 标准通道'),
            /* 只有跨越靶标边界的通道才算突破凭证（自己 VPS/自建服务器上开的不算） */
            t.legit === true
              ? h('span', { className: 'rt-tag rt-tag-live', title: t.entry_kind_label || '' }, '目标侧通道')
              : (t.legit === false
                  ? h('span', { className: 'rt-tag rt-tag-warn', title: '只在自己 VPS/自建服务器上开的通道，没有碰到目标 —— 不算边界突破/内网突破' }, '不算突破')
                  : h('span', { className: 'rt-tag', title: '未声明 entry_kind：请说明目标侧的那一端是什么（target-outbound / target-http / target-agent）' }, '待确认')),
            t.reach ? h('span', { className: 'rt-tag' }, '可达 ' + t.reach) : null,
            h('div', { className: 'rt-spacer' }),
            h('button', {
              className: 'rt-btn', disabled: busy || !ready, style: { padding: '0 6px', fontSize: 11 },
              onClick: () => copy('sock' + t.id, t.listen || ''),
            }, copied === 'sock' + t.id ? '已复制' : '复制地址'),
            t.status === 'active'
              ? h('button', { className: 'rt-btn', disabled: busy || !ready, style: { padding: '0 6px', fontSize: 11 }, onClick: () => markTunnel(t, 'down') }, '标记失效')
              : h('button', { className: 'rt-btn', disabled: busy || !ready, style: { padding: '0 6px', fontSize: 11 }, onClick: () => markTunnel(t, 'active') }, '标记可用')),
          h('div', { className: 'rt-sess-facts' },
            fact('目标侧入口', t.entry || '未登记'),
            fact('跨越边界', t.legit === true
              ? h('span', { className: 'rt-tag rt-tag-live' }, t.entry_kind_label || t.entry_kind || '已确认目标侧')
              : (t.legit === false
                  ? h('span', { className: 'rt-tag rt-tag-warn' }, '不算突破（只在自己 VPS 上开代理）')
                  : h('span', { className: 'rt-tag' }, '未声明 entry_kind，待确认'))),
            t.reach ? fact('可达网段', t.reach) : null,
            t.asset_ip ? fact('所在资产', t.asset_ip) : null,
            fact('最后检测', (t.last_check ? fmt(t.last_check) : '未检测')
              + (t.latency_ms !== null && t.latency_ms !== undefined ? '（' + t.latency_ms + 'ms）' : '')),
            t.check_note ? fact('检测说明', t.check_note) : null,
            t.note ? fact('备注', t.note) : null),
          /* 命令默认折叠：卡片首要信息是"这条通道能不能用、通向哪"，命令按需展开 */
          t.command ? h('details', { className: 'rt-sess-fold' },
            h('summary', null, '建立命令（点击展开 / 复制）'),
            h('div', Object.assign({ className: 'rt-code', title: '点击复制' }, clickable(() => copy('c' + t.id, t.command), { label: '复制命令' })),
              copied === 'c' + t.id ? '已复制' : t.command)) : null,
          t.status === 'active' && t.listen
            ? h('details', { className: 'rt-sess-fold' },
                h('summary', null, '走这条隧道扫描（gogo / fscan 命令）'),
                h('div', { className: 'rt-sess-cmd' },
                  h('div', Object.assign({ className: 'rt-code', title: '点击复制' }, clickable(() => copy('g' + t.id, gogoCmd), { label: '复制 gogo 命令' })),
                    copied === 'g' + t.id ? '已复制' : gogoCmd),
                  h('div', Object.assign({ className: 'rt-code', style: { display: 'block', marginTop: 3 }, title: '点击复制' }, clickable(() => copy('f' + t.id, fscanCmd), { label: '复制 fscan 命令' })),
                    copied === 'f' + t.id ? '已复制' : fscanCmd)))
            : null)
      })

      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '会话与入口'),
          h('span', { className: 'rt-tag' }, 'WebShell ' + (current ? (totals.webshellsOnline || 0) + '/' + (totals.webshells || 0) : '待核对') + ' 在线'),
          h('span', { className: 'rt-tag' }, '隧道 ' + (current ? (totals.tunnelsActive || 0) + '/' + (totals.tunnels || 0) : '待核对') + ' 可用'),
          h('span', { className: 'rt-tag' }, '凭据 ' + (current ? totals.credentials || 0 : '?')),
          h('span', { className: 'rt-tag' }, '访问会话 ' + (current ? totals.access || 0 : '?')),
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn rt-btn-primary', disabled: true, title: '当前面板不发起主动检测；请在会话中说明目标和范围后使用已授权工具。' }, '检测连通性'),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, '刷新')),
        h('div', { className: 'rt-note' }, '当前面板不发起主动检测；请在会话中说明目标和范围后使用已授权工具。'),
        !current ? h('div', { className: 'rt-note', role: 'status' }, loading ? '正在核对当前项目记录…' : '当前项目记录未确认，请刷新核对。') : null,
        msg?.view === view && (msg.err || msg.ok) ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
        err?.view === view ? h('div', { className: 'rt-err' }, err.text) : null,
        h('div', { className: 'rt-body', style: { overflow: 'auto' } },
          current && !shells.length && !tunnels.length
            ? h('div', { className: 'rt-empty' },
                h('div', null, '还没有登记任何 WebShell 或隧道。'),
                h('div', { style: { marginTop: 6, fontSize: 12 } },
                  '拿到 WebShell 用 redteam_webshell_add；建好隧道用 redteam_tunnel_add（suo5 / socks5 / ssh -R）；之后智能体用 redteam_sessions 就能看到。'))
            : null,
          hints.length ? h('div', { style: { padding: '8px 10px 0' } }, hints) : null,
          h(Section, {
            key: 'webshells', tone: 'queue', title: 'WebShell',
            count: current ? totals.webshellsOnline + '/' + totals.webshells + ' 在线' : '待核对',
            sub: '已上线的可控入口',
            open: sessCollapse.isOpen('shells', true), onToggle: sessCollapse.toggle('shells', true),
          }, !current ? h('div', { className: 'rt-atest-meta' }, '记录未确认') : shells.length
            ? h('div', { className: 'rt-sess-grid', style: { padding: 0 } }, shellCards)
            : h('div', { className: 'rt-atest-meta' }, '暂无（拿到 WebShell 后用 redteam_webshell_add 登记）')),
          h(Section, {
            key: 'tunnels', tone: 'test', title: '内网隧道',
            count: current ? totals.tunnelsActive + '/' + totals.tunnels + ' 可用' : '待核对',
            sub: '可直接给扫描器当代理用',
            open: sessCollapse.isOpen('tunnels', true), onToggle: sessCollapse.toggle('tunnels', true),
          }, !current ? h('div', { className: 'rt-atest-meta' }, '记录未确认') : tunnels.length
            ? h('div', { className: 'rt-sess-grid', style: { padding: 0 } }, tunnelCards)
            : h('div', { className: 'rt-atest-meta' }, '暂无（建好隧道后用 redteam_tunnel_add 登记）'))))

    }

    /* ---------------------------------------------------------- 错误边界 */
    /**
     * 单个页签渲染出错时只降级该页签，不拖垮整个面板：面板与侧栏按钮保持可用，
     * 用户可一键回到资产测绘。（此前面板整块消失、按钮点不开就是缺了这层保护。）
     */
    class RtBoundary extends React.Component {
      constructor(props) {
        super(props)
        this.state = { error: null }
      }
      static getDerivedStateFromError(error) {
        return { error: error }
      }
      componentDidCatch(error) {
        try { console.error('[redteam-ui] 页面渲染出错:', error) } catch (e) { /* ignore */ }
      }
      render() {
        if (this.state.error) {
          const msg = this.state.error && this.state.error.message ? this.state.error.message : String(this.state.error)
          return h('div', { className: 'rt-pane' },
            h('div', { className: 'rt-err' }, '该页面渲染出错：' + msg),
            h('button', {
              className: 'rt-btn',
              onClick: () => { this.setState({ error: null }); setUI({ tab: 'assets' }) },
            }, '回到资产测绘'))
        }
        return this.props.children
      }
    }

    /**
     * 智能体页签：并发名额（最多 3 个）+ 六个角色与它们的提示词。
     * 主会话派活前先看这里的名额，用户也能一眼看到"现在还能拉起几个智能体"。
     */
    const quotaUpdatedEvent = 'dsh-purge:quota-settings-updated'
    const quotaUnknownMessage = '有一笔全局设置保存结果未确认；已请求只读核对当前值。读回值不是原保存回执，未重发保存。'
    function AgentsTab(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [concurrency, setConcurrency] = React.useState(null)
      const [quotaError, setQuotaError] = React.useState(null)
      const [quotaCheck, setQuotaCheck] = React.useState(null)
      const [saveNotice, setSaveNotice] = React.useState(null)
      const quotaGeneration = React.useRef(0), request = React.useRef(null), inflight = React.useRef(false)
      const owner = React.useRef({ eng, refreshKey })
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      const view = owner.current
      const [busy, setBusy] = React.useState(false)
      const moment = () => ({ wall: Date.now(), mono: typeof performance === 'undefined' ? Date.now() : performance.now() })
      const [clock, setClock] = React.useState(moment)
      const load = () => {
        if (owner.current !== view) return
        const generation = ++quotaGeneration.current, controller = new AbortController()
        request.current?.abort(); request.current = controller; inflight.current = true
        setBusy(true); setConcurrency(null); setQuotaError(null); setQuotaCheck(null)
        api({ op: 'agentsStatus', engagement: eng }, { signal: controller.signal }).then(r => {
          if (generation !== quotaGeneration.current || owner.current !== view) return
          if (r?.engagement === eng && r.quota_check) setQuotaCheck({ ...r.quota_check, view })
          const checked = moment()
          if (r?.ok && r.engagement === eng) { setConcurrency({ ...r, checked }); setClock(checked) }
          else setQuotaError(r?.error || '当前项目名额暂时无法核实')
        }, e => { if (generation === quotaGeneration.current && owner.current === view) setQuotaError(String(e?.message || e)) })
          .finally(() => { if (generation === quotaGeneration.current && owner.current === view) { inflight.current = false; setBusy(false) } })
      }
      React.useEffect(() => {
        load()
        const timer = setInterval(() => setClock(moment()), 1000)
        let focusedAt
        const focus = () => {
          const time = Date.now()
          if (document.visibilityState === 'hidden' || inflight.current) return
          if (focusedAt !== undefined && time >= focusedAt && time - focusedAt < 5000) return
          focusedAt = time; load()
        }
        window.addEventListener('focus', focus); document.addEventListener('visibilitychange', focus)
        const settingsChanged = event => {
          if (owner.current !== view) return
          load()
          if (event?.detail?.outcome === 'unknown') setSaveNotice({ outcome: 'unknown' })
        }
        window.addEventListener(quotaUpdatedEvent, settingsChanged)
        return () => {
          quotaGeneration.current++; request.current?.abort(); inflight.current = false
          clearInterval(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', focus)
          window.removeEventListener(quotaUpdatedEvent, settingsChanged)
        }
      }, [eng, refreshKey])
      const checked = concurrency?.checked
      const invalidated = React.useRef(null)
      if (checked && (clock.wall < checked.wall || clock.mono < checked.mono
        || Math.max(clock.wall - checked.wall, clock.mono - checked.mono) >= 60000)) invalidated.current = checked
      const fresh = !!checked && concurrency.engagement === eng && invalidated.current !== checked
      const check = quotaCheck?.view === view ? quotaCheck : null
      const categories = { complete: '已完成', 'incomplete-branch': '分支不完整', 'registry-error': '会话查询失败',
        timeout: '核查超时', 'registry-unavailable': '注册表不可用', 'bindings-unavailable': '绑定不可用', 'settings-unavailable': '设置不可用' }
      const used = fresh ? concurrency.used : null
      const max = fresh ? concurrency.max : null
      return h('div', { className: 'rt-main' },
        h('div', { className: 'rt-toolbar' },
          h('span', { style: { fontWeight: 600 } }, '作战智能体'),
          used === null
            ? h('span', { className: 'rt-tag' }, checked ? '名额待核对' : '占用未知')
            : h('span', { className: 'rt-tag' + (used >= max ? ' rt-tag-warn' : ' rt-tag-live') }, '占用 ' + used + ' / 剩余 ' + Math.max(max - used, 0)),
          checked ? h('small', { className: 'rt-muted' }, '上次核对 ' + new Date(checked.wall).toLocaleTimeString()) : null,
          h('div', { className: 'rt-spacer' }),
          h('button', { className: 'rt-btn', disabled: busy, onClick: load }, busy ? '读取中…' : '刷新')),
        h('div', { className: 'rt-pane' },
          quotaError ? h('div', { className: 'rt-err' }, quotaError) : null,
          check ? h('div', { className: 'rt-note', style: { overflowWrap: 'anywhere' } },
            h('div', { role: 'status' }, '核查记录：' + (Number.isInteger(check.completed) ? check.completed : '?') + ' / '
              + (Number.isInteger(check.total) ? check.total : '总数待确认') + ' 根会话 · ' + (categories[check.kind] || '待核对')),
            h('small', null, '核查时间：' + fmt(check.observedAt)),
            (Array.isArray(check.failed) ? check.failed : []).slice(0, 8).map((item, index) => h('div', { key: index },
              '失败会话：' + String(item.rootSession || '') + '（' + (categories[item.kind] || '待核对') + '）')),
            Array.isArray(check.pendingRoots) && check.pendingRoots.length ? h('div', null,
              '查询中的会话（最多8条）：' + check.pendingRoots.slice(0, 8).map(String).join('、')) : null,
            check.kind !== 'complete' ? h('button', { className: 'rt-btn', disabled: busy, onClick: load }, '重新核查名额') : null) : null,
          h('div', { className: 'rt-card' },
            h('h4', null, '项目并发名额'),
            h('div', { style: { fontSize: 12, lineHeight: 1.7 } },
              '· 同一项目的会话共享名额；派活前调用 redteam_agent_slot 核对并占位，满额或状态未知时拒绝新增占位。',
              h('br'),
              '· **默认一个一个派、按顺序推进**；只有确实互不依赖的活才并行。',
              h('br'),
              '· 每个会话有**自己的靶标绑定**：多会话并行不会把报告写串（子智能体继承父会话的靶标）。')),
          h('div', { className: 'rt-card' },
            h('h4', null, '六个角色'),
            h('div', { style: { fontSize: 12, lineHeight: 1.8 } },
              '① 信息收集 `recon` —— 只收集资产，把单位资产收集完整（含边缘与未备案资产）', h('br'),
              '② 资产梳理 `assess` —— 一条一条过，评易打性并全部落库', h('br'),
              '③ 漏洞发现 `vuln-scan` —— 先查库去重 → Nday/1day 优先 → 接口未授权探测', h('br'),
              '④ 漏洞利用 `exploit` —— 先拿服务器权限（冰蝎/哥斯拉马）+ 建 suo5 隧道，再打其它得分项', h('br'),
              '⑤ 内网渗透 `internal` —— 走隧道，依次拉起 ①②③④ 做内网', h('br'),
              '⑥ 主会话 `plan` —— 只做计划、派活、汇总、汇报，不动手')),
          h(ConcurrencyCard, { engagement: eng, refreshKey, concurrency: fresh ? concurrency : null, saveNotice,
            onSaved: result => window.dispatchEvent(new CustomEvent(quotaUpdatedEvent, { detail: result })) }),
          h(BindingHistoryCard, { engagement: eng, refreshKey }),
          h('div', { className: 'rt-card' },
            h('h4', null, '角色提示词（按靶标存，可在这里编辑）'),
            h('div', { style: { fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 6 } },
              '「智能体提示词」已并入本页；下面是完整编辑器（改完点保存，只影响当前靶标）。'),
            h(PromptsTab, { engagement: eng, refreshKey: refreshKey }))))
    }

    function BindingHistoryCard(props) {
      const eng = props.engagement
      const refreshKey = props.refreshKey || 0
      const [open, setOpen] = React.useState(false)
      const [onlyUnarchived, setOnlyUnarchived] = React.useState(false)
      const [cursor, setCursor] = React.useState({ eng, after: '' })
      const [reloadKey, setReloadKey] = React.useState(0)
      const [data, setData] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [message, setMessage] = React.useState(null)
      const generation = React.useRef(0), inflight = React.useRef(false)
      const after = cursor.eng === eng ? cursor.after : ''
      const owner = React.useRef({ eng, open, after, onlyUnarchived, reloadKey, refreshKey })
      const previous = owner.current
      if (previous.eng !== eng || previous.open !== open || previous.after !== after
        || previous.onlyUnarchived !== onlyUnarchived || previous.reloadKey !== reloadKey || previous.refreshKey !== refreshKey) owner.current = { eng, open, after, onlyUnarchived, reloadKey, refreshKey }
      const view = owner.current, ready = data?.view === view
      React.useEffect(() => {
        const token = ++generation.current, controller = new AbortController()
        setData(null); setMessage(null); setBusy(false); inflight.current = false
        if (open && eng) {
          setBusy(true); inflight.current = true
          api({ op: 'bindingHistory', engagement: eng, after, onlyUnarchived }, { signal: controller.signal }).then(r => {
            if (generation.current !== token || owner.current !== view) return
            if (!r?.ok || r.engagement !== eng || !Array.isArray(r.items)) throw new Error(r?.error || '绑定记录未确认')
            setData({ ...r, view })
          }).catch(e => { if (generation.current === token && owner.current === view) setMessage(String(e?.message || e)) })
            .finally(() => { if (generation.current === token && owner.current === view) { setBusy(false); inflight.current = false } })
        }
        return () => { generation.current++; controller.abort() }
      }, [eng, open, after, onlyUnarchived, reloadKey, refreshKey])
      const archive = row => {
        if (owner.current !== view || !ready || inflight.current) return
        const token = generation.current, archived = !row.archived
        const valid = () => token === generation.current && owner.current === view
        setBusy(true); inflight.current = true; setMessage(null)
        api({ op: 'setBindingArchived', engagement: eng, rootSession: row.rootSession, archived }).then(r => {
          if (!valid()) return
          if (!r?.ok || r.engagement !== eng || r.rootSession !== row.rootSession || r.archived !== archived) throw new Error(r?.error || '归档结果未确认')
          setData(current => ({ ...current, items: current.items.map(item => item.rootSession === row.rootSession ? { ...item, archived } : item)
            .filter(item => !onlyUnarchived || !item.archived) }))
          setMessage(archived ? '已归档，可随时恢复记录。' : '记录已恢复显示。')
        }).catch(e => { if (valid()) setMessage('操作未确认，请刷新记录核对：' + String(e?.message || e)) })
          .finally(() => { if (valid()) { setBusy(false); inflight.current = false } })
      }
      return h('div', { className: 'rt-card' },
        h('h4', null, '会话绑定记录'),
        h('button', { className: 'rt-btn', disabled: !eng, 'aria-expanded': open, onClick: () => setOpen(value => !value) }, open ? '收起会话绑定' : '查看会话绑定'),
        open ? h('div', null,
          h('p', { className: 'rt-note' }, '归档只整理列表，保留会话与绑定，名额仍完整核查。'),
          h('div', { className: 'rt-toolbar' },
            h('button', { className: 'rt-btn', disabled: busy, 'aria-pressed': onlyUnarchived,
              onClick: () => { if (owner.current === view) { setOnlyUnarchived(value => !value); setCursor({ eng, after: '' }) } } }, onlyUnarchived ? '查看全部记录' : '只看未归档'),
            h('button', { className: 'rt-btn', disabled: busy, onClick: () => { if (owner.current === view) setReloadKey(value => value + 1) } }, '刷新记录')),
          message ? h('div', { className: 'rt-note', role: 'status' }, message) : null,
          busy ? h('div', { role: 'status' }, '正在核对绑定记录…') : null,
          ready ? h('div', null,
            h('small', { className: 'rt-muted' }, '记录读取：' + fmt(data.observedAt)),
            data.items.length === 0 ? h('p', null, '本页没有绑定记录。') : null,
            data.items.map(row => h('div', { key: row.rootSession, style: { padding: '8px 0', borderBottom: '1px solid var(--dsw-alias-border-l1)' } },
              h('div', { className: 'rt-mono', style: { overflowWrap: 'anywhere' } }, row.rootSession),
              h('small', { className: 'rt-muted' }, row.bindingCount + ' 条绑定 · ' + (row.archived ? '已归档' : '未归档')),
              h('button', { className: 'rt-btn', disabled: busy, style: { marginLeft: 8 }, onClick: () => archive(row) }, row.archived ? '恢复记录' : '归档记录'))),
            h('div', { className: 'rt-toolbar' },
              h('button', { className: 'rt-btn', disabled: busy || !after, onClick: () => { if (owner.current === view) setCursor({ eng, after: '' }) } }, '回到首页'),
              h('button', { className: 'rt-btn', disabled: busy || !data.next, onClick: () => { if (owner.current === view && data.next) setCursor({ eng, after: data.next }) } }, '下一页'))) : null) : null)
    }

    function ConcurrencyCard(props) {
      const info = props.concurrency || {}
      const eng = props.engagement, refreshKey = props.refreshKey || 0
      const [editor, setEditor] = React.useState({ eng, text: '', dirty: false })
      const [busy, setBusy] = React.useState(false)
      const [msg, setMsg] = React.useState(null)
      const owner = React.useRef({ eng, refreshKey }), editorOwner = React.useRef({ eng })
      const onSaved = React.useRef(props.onSaved), mounted = React.useRef(true), writing = React.useRef(false)
      if (owner.current.eng !== eng || owner.current.refreshKey !== refreshKey) owner.current = { eng, refreshKey }
      if (editorOwner.current.eng !== eng) editorOwner.current = { eng }
      const view = owner.current, editView = editorOwner.current
      const draft = editor.eng === eng ? editor.text : ''
      const dirty = editor.eng === eng && editor.dirty
      const message = msg?.view === editView ? msg : null
      onSaved.current = props.onSaved
      React.useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
      React.useEffect(() => { setMsg(null) }, [eng])
      React.useEffect(() => {
        setEditor(current => current.eng !== eng ? { eng, text: info.max ? String(info.max) : '', dirty: false }
          : info.max && !current.dirty ? { ...current, text: String(info.max) } : current)
      }, [eng, info.max])
      React.useEffect(() => {
        if (props.saveNotice?.outcome === 'unknown') setMsg({ err: quotaUnknownMessage, view: editorOwner.current })
      }, [props.saveNotice])

      const limit = info.limit || 10
      const used = typeof info.used === 'number' ? info.used : null
      const source = info.source === 'settings' ? '面板中设置'
        : info.source === 'env' ? '环境变量 REDTEAM_MAX_AGENTS' : info.source === 'default' ? '默认值' : '待核对'
      const n = Number(draft)
      const invalid = !Number.isFinite(n) || Math.floor(n) !== n || n < 1 || n > limit
      const save = () => {
        if (invalid || !info.max || editor.eng !== eng || owner.current !== view || writing.current || !mounted.current) return
        const feedback = value => { if (mounted.current && editorOwner.current === editView) setMsg({ ...value, view: editView }) }
        const unknown = () => {
          onSaved.current?.({ outcome: 'unknown' })
          feedback({ err: quotaUnknownMessage })
        }
        writing.current = true; setBusy(true); setMsg(null)
        api({ op: 'setAgentsMax', max: n }).then(r => {
          if (r?.ok === false && r.outcome === 'rejected') { feedback({ err: '保存被拒绝：' + (r.error || '输入未通过校验') }); return }
          if (r?.ok !== true || r.max !== n || !Number.isInteger(r.max) || (r.outcome !== undefined && r.outcome !== 'confirmed')) { unknown(); return }
          if (mounted.current) setEditor(current => current.eng === eng && current.text === draft ? { ...current, dirty: false } : current)
          // Confirmed and uncertain writes notify current readers; neither is replayed.
          onSaved.current?.({ outcome: 'confirmed' })
          feedback({ ok: '已保存：所有项目共用上限 ' + r.max + '，名额按项目分别计算。' })
        }, unknown).finally(() => { writing.current = false; if (mounted.current) setBusy(false) })
      }
      return h('div', { className: 'rt-card' },
        h('h4', null, '并发数量（全局设置）'),
        h('div', { style: { fontSize: 12, lineHeight: 1.8, marginBottom: 8 } },
          '所有项目共用此上限设置，名额按项目分别计算。当前上限：' + (info.max || '?')
          + (used === null ? '' : '（在跑 ' + used + '，剩余 ' + Math.max((info.max || 0) - used, 0) + '）')
          + '，来源：' + source + '。保存会影响所有项目，立即生效，无需重启。'),
        h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
          h('input', {
            className: 'rt-input', style: { width: 90 }, type: 'number', min: 1, max: limit,
            value: draft, disabled: busy, onChange: e => {
              if (owner.current === view && !writing.current) setEditor({ eng, text: e.target.value, dirty: true })
            },
          }),
          h('span', { style: { fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' } }, '范围 1 – ' + limit),
          h('button', { className: 'rt-btn rt-btn-primary', disabled: busy || invalid || !info.max, onClick: save }, busy ? '保存中…' : '保存'),
          dirty ? h('button', { className: 'rt-btn', disabled: busy || !info.max, onClick: () => {
            if (owner.current === view && !writing.current && info.max) setEditor({ eng, text: String(info.max), dirty: false })
          } }, '使用当前核对值') : null),
        dirty ? h('div', { className: 'rt-note', role: 'status' }, '输入已修改，已保留你的输入；后台核对不会覆盖。') : null,
        message ? h('div', { className: message.err ? 'rt-err' : 'rt-note', role: 'status' }, message.err || message.ok,
          h('button', { className: 'rt-btn', style: { marginLeft: 8 }, onClick: () => { if (editorOwner.current === editView) setMsg(null) } }, '关闭保存提示')) : null,
        h('div', { className: 'rt-note', style: { marginTop: 8 } },
          '⚠️ 调大不等于更快：**同一个模型 API Key 的并发/速率上限是共享的**，同时派太多会互相挤占，'
          + '表现为排队等待、超时、返回被截断甚至限流报错 —— 反而让测试结果不稳定（漏测、半途而废）。'
          + '建议从 2–3 开始，只有在确认 Key 的额度足够、任务之间确实互不依赖时才调大。'))
    }

    /**
     * 版本显示 + 自动更新按钮。
     *
     * 行为：挂载时静默查一次最新版本（npm registry），有新版本就把按钮点亮成
     * 「有新版本 vX」；点击弹出确认框（当前版本 / 最新版本 / 安装位置 / 阻塞项），
     * 确认后由 host 侧执行 安装 → 重启 dsh web（页面会断开，重启后刷新即可）。
     */
    function VersionBar(props) {
      const [info, setInfo] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [busy, setBusy] = React.useState(false)
      const [open, setOpen] = React.useState(false)
      const [msg, setMsg] = React.useState(null)
      const [countdown, setCountdown] = React.useState(0)

      const check = (silent) => {
        if (!silent) setBusy(true)
        api({ op: 'updateCheck' }).then((r) => {
          setBusy(false)
          if (!r || r.ok === false) {
            /* 开发态或查不到 registry：只显示当前版本，不报错打扰用户 */
            if (!silent) setErr((r && r.error) || '检查更新失败')
            api({ op: 'version' }).then((v) => { if (v && v.ok !== false) setInfo(v) }, () => {})
            return
          }
          setErr(null)
          setInfo(r)
        }, (e) => {
          setBusy(false)
          if (!silent) setErr(String((e && e.message) || e))
          api({ op: 'version' }).then((v) => { if (v && v.ok !== false) setInfo(v) }, () => {})
        })
      }
      React.useEffect(() => { check(true) }, [])

      const apply = () => {
        setBusy(true)
        setMsg(null)
        api({ op: 'updateApply', target: (info && info.latest) || undefined }).then((r) => {
          setBusy(false)
          if (!r || r.ok === false) { setMsg({ err: (r && r.error) || '更新失败' }); return }
          setMsg({ ok: '已安装 ' + (r.installed || '') + '，正在重启当前宿主…' })
          /* 重启会断开这个页面：倒计时提示用户稍后刷新 */
          setCountdown(6)
          const t = setInterval(() => {
            setCountdown((n) => {
              if (n <= 1) { clearInterval(t); window.location.reload(); return 0 }
              return n - 1
            })
          }, 1000)
        }, (e) => { setBusy(false); setMsg({ err: String((e && e.message) || e) }) })
      }

      const current = info && info.current ? info.current : (info && info.plugin ? info.plugin.version : null)
      const latest = info && info.latest ? info.latest : null
      const hasNew = !!(info && info.updateAvailable)
      const blockers = (info && info.blockers) || []
      const notes = (info && info.notes) || []
      const mode = info && info.install ? info.install.mode : null

      return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6 } },
        h('span', {
          className: 'rt-tag' + (hasNew ? ' rt-tag-warn' : ''),
          title: ('当前版本 ' + (current || '未知') + (latest ? '\n最新版本 ' + latest : '')
            + (mode === 'dev' ? '\n安装方式：开发态（源码软链）' : mode === 'package' ? '\n安装方式：包安装' : '')
            + (info && info.check_error ? '\n检查失败：' + info.check_error : '')),
        }, 'v' + (current || '?')),
        hasNew
          ? h('button', {
              className: 'rt-btn rt-btn-primary', disabled: busy,
              onClick: () => { setOpen(true); setMsg(null) },
              title: '发现新版本 ' + latest + '：点击查看并一键更新（会重启当前宿主）',
            }, busy ? '检查中…' : '有新版本 v' + latest)
          : h('button', {
              className: 'rt-btn', disabled: busy, onClick: () => check(false),
              title: '重新检查 npm 上的最新版本',
            }, busy ? '检查中…' : '检查更新'),
        open
          ? h('div', { className: 'rt-modal', 'aria-hidden': 'true', onClick: () => setOpen(false) },
              h('div', { className: 'rt-modal-box', onClick: (e) => e.stopPropagation() },
                h('h4', { style: { marginTop: 0 } }, '更新 RedTeam 模式'),
                h('div', { className: 'rt-kv' }, h('b', null, '当前版本'), h('span', null, current || '未知')),
                h('div', { className: 'rt-kv' }, h('b', null, '最新版本'), h('span', null, latest || '未知')),
                h('div', { className: 'rt-kv' }, h('b', null, '安装方式'),
                  h('span', null, mode === 'dev' ? '开发态（源码软链）' : mode === 'package' ? '包安装（' + ((info.install && info.install.packageManager) || 'npm') + '）' : '未知')),
                info && info.install && info.install.dir
                  ? h('div', { className: 'rt-kv' }, h('b', null, '安装位置'), h('span', { className: 'rt-mono' }, info.install.dir))
                  : null,
                blockers.length
                  ? h('div', { className: 'rt-hint' },
                      h('div', { style: { fontWeight: 600, marginBottom: 4 } }, '现在不能更新：'),
                      blockers.map((b, i) => h('div', { key: 'b' + i }, '· ' + b)))
                  : null,
                notes.length
                  ? h('div', { className: 'rt-foot', style: { padding: '4px 0' } }, notes.map((n, i) => h('div', { key: 'n' + i }, n)))
                  : null,
                h('div', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)', margin: '8px 0' } },
                  '更新过程：安装新版本 → 自动重启当前宿主（官方 exe / 社区版 / dsh web；当前页面会断开，约 5–10 秒后自动刷新）。'
                  + '重启前会检查有没有智能体在跑，有就拦住不动。'),
                msg ? h('div', { className: msg.err ? 'rt-err' : 'rt-foot' }, msg.err || msg.ok) : null,
                countdown > 0
                  ? h('div', { className: 'rt-foot' }, '宿主正在重启，' + countdown + ' 秒后自动刷新页面…')
                  : null,
                h('div', { style: { display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 } },
                  h('button', { className: 'rt-btn', onClick: () => setOpen(false) }, '关闭'),
                  h('button', {
                    className: 'rt-btn rt-btn-primary',
                    disabled: busy || blockers.length > 0 || mode === 'dev',
                    title: mode === 'dev' ? '开发态安装请用仓库流程升级' : blockers.length ? '先解决上面的阻塞项' : '安装并重启',
                    onClick: apply,
                  }, busy ? '更新中…' : '一键更新并重启'))))
          : null)
    }

    /* ---------------------------------------------------------- 常驻面板主体 */
    /**
     * 「未读」状态：按靶标记在 localStorage 里，每 25 秒问一次 host 的 consoleDigest
     * （每个页签的条数 + 最近更新时间）。比本地记住的快照新 → 该页签点红点；
     * 用户点开那个页签就把当前值记成已读，红点消失。
     */
    const UNREAD_KEY = 'rt-unread:'
    const loadUnread = (eng) => {
      try {
        const raw = window.localStorage.getItem(UNREAD_KEY + eng)
        const parsed = raw ? JSON.parse(raw) : null
        return parsed && typeof parsed === 'object' ? parsed : null
      } catch (e) { return null }
    }
    const saveUnread = (eng, value) => {
      try { window.localStorage.setItem(UNREAD_KEY + eng, JSON.stringify(value)) } catch (e) { /* 隐私模式等：不持久化也能用 */ }
    }
    /** 这个页签相对上次查看有没有新内容（条数变多，或最新一条比上次查看还新）。 */
    const digestHasNew = (prev, cur) => {
      if (!cur) return false
      if (!prev) return true
      const pc = Number(prev.count || 0)
      const cc = Number(cur.count || 0)
      if (cc > pc) return true
      const pa = prev.at || ''
      const ca = cur.at || ''
      return ca !== '' && ca !== pa && ca > pa
    }

    const RT_GEOM_KEY = 'rt-dock-geom-v1'
    function clampRtGeom(g) {
      const vw = (typeof window !== 'undefined' && window.innerWidth) || 1280
      const vh = (typeof window !== 'undefined' && window.innerHeight) || 800
      const w = Math.min(Math.max(320, Number(g && g.w) || 620), Math.max(320, vw))
      const h = Math.min(Math.max(240, Number(g && g.h) || 520), Math.max(240, vh))
      const x = Math.min(Math.max(0, Number(g && g.x) || 0), Math.max(0, vw - w))
      const y = Math.min(Math.max(0, Number(g && g.y) || 0), Math.max(0, vh - h))
      return { x: x, y: y, w: w, h: h }
    }
    function defaultRtGeom() {
      const vw = (typeof window !== 'undefined' && window.innerWidth) || 1280
      const vh = (typeof window !== 'undefined' && window.innerHeight) || 800
      let w = 620
      try {
        const saved = Number(window.localStorage.getItem('rt-dock-width'))
        if (Number.isFinite(saved) && saved >= 320 && saved <= 1200) w = saved
      } catch (e) { /* 隐私模式 */ }
      const h = Math.max(240, Math.min(640, vh - 24))
      return clampRtGeom({ x: Math.max(0, vw - w - 12), y: 12, w: w, h: h })
    }
    function loadRtGeom() {
      try {
        const raw = JSON.parse(window.localStorage.getItem(RT_GEOM_KEY) || 'null')
        if (raw && typeof raw === 'object') return clampRtGeom(raw)
      } catch (e) { /* 隐私模式或坏数据 */ }
      return defaultRtGeom()
    }

    function SessionBindingBanner(props) {
      const [status, setStatus] = React.useState({ state: 'checking' })
      const monitor = React.useRef(null)
      React.useEffect(() => {
        const reader = createBindingMonitor({ getSessionId: props.getSessionId,
          read: (sessionId, signal) => api({ op: 'sessionBinding', sessionId }, { signal }), publish: setStatus })
        monitor.current = reader; reader.check()
        const tick = setInterval(() => { if (document.visibilityState !== 'hidden') reader.check() }, 1000)
        const focus = () => reader.check(true)
        window.addEventListener('focus', focus)
        return () => { clearInterval(tick); window.removeEventListener('focus', focus); reader.dispose(); monitor.current = null }
      }, [props.getSessionId, props.refreshKey])
      const projectName = id => props.engagements.find(project => project.id === id)?.name || id
      const label = status.state === 'bound' ? '聊天绑定：' + projectName(status.engagement)
        : status.state === 'stale' ? '聊天绑定待核对' + (status.engagement ? '（上次：' + projectName(status.engagement) + '）' : '')
        : status.state === 'no-session' ? '新会话 · 尚未绑定项目'
        : status.state === 'unbound' ? '当前聊天尚未绑定项目'
        : status.state === 'checking' ? '正在核对聊天绑定…' : '聊天绑定暂不可用'
      return h('div', { className: 'rt-binding', role: 'status', 'aria-live': 'polite' },
        h('div', null, h('strong', null, label),
          h('span', { className: 'rt-muted', style: { marginLeft: 10 } }, '面板浏览：' + (projectName(props.browsed) || '未选择')),
          status.checkedAt ? h('small', { className: 'rt-muted', style: { marginLeft: 10 } }, '上次核对 ' + new Date(status.checkedAt).toLocaleTimeString()) : null,
          status.error ? h('div', { className: 'rt-err' }, status.error) : null),
        h('button', { className: 'rt-btn', type: 'button', disabled: status.state === 'checking', onClick: () => monitor.current?.check(true) }, '核对绑定'))
    }

    function Panel(props) {
      /* embedded：嵌在 dsh-purge 外层 dock 里时，不再自带收起/全面浏览/拖拽条，避免与外层按钮重叠 */
      const embedded = !!(props && props.embedded)
      const st = useUI()
      const [engagements, setEngagements] = React.useState([])
      const [eng, setEng] = React.useState(null)
      const [snapshot, setSnapshot] = React.useState(null)
      const [err, setErr] = React.useState(null)
      const [newName, setNewName] = React.useState('')
      const [geom, setGeom] = React.useState(loadRtGeom)
      const [creating, setCreating] = React.useState(false)
      const [refreshKey, setRefreshKey] = React.useState(0)
      const [digest, setDigest] = React.useState(null)
      const [seen, setSeen] = React.useState(null)

      React.useEffect(() => {
        if (embedded) return undefined
        try { window.localStorage.setItem(RT_GEOM_KEY, JSON.stringify(geom)) } catch (e) { /* 隐私模式 */ }
      }, [geom, embedded])
      React.useEffect(() => {
        if (embedded) return undefined
        const onResize = () => setGeom((g) => clampRtGeom(g))
        window.addEventListener('resize', onResize)
        return () => window.removeEventListener('resize', onResize)
      }, [embedded])

      const loadSnapshot = (id) => {
        if (!id) { setSnapshot(null); return }
        api({ op: 'snapshot', engagement: id }).then((r) => {
          if (!r || r.ok === false) { setErr((r && r.error) || '加载失败'); return }
          setErr(null)
          setSnapshot(r)
        }, (e) => setErr(String((e && e.message) || e)))
      }

      const refreshList = (selectId) => {
        api({ op: 'bootstrap' }).then((b) => {
          setEngagements((b && b.engagements) || [])
          if (selectId) { setEng(selectId); loadSnapshot(selectId) }
        }, () => {})
      }

      React.useEffect(() => {
        api({ op: 'bootstrap' }).then((r) => {
          if (!r || r.ok === false) { setErr((r && r.error) || '无法连接资产库'); return }
          setEngagements(r.engagements || [])
          const id = r.current || (r.engagements && r.engagements[0] && r.engagements[0].id) || null
          if (id) { setEng(id); loadSnapshot(id) }
        }, (e) => setErr(String((e && e.message) || e)))
      }, [])

      const openEngagement = (nameArg) => {
        const name = String(nameArg || newName).trim()
        if (!name) return
        setCreating(true)
        api({ op: 'openEngagement', name: name }).then((r) => {
          setCreating(false)
          if (!r || r.ok === false) { setErr((r && r.error) || '创建失败'); return }
          setNewName('')
          refreshList(r.engagement && r.engagement.id)
        }, (e) => { setCreating(false); setErr(String((e && e.message) || e)) })
      }

      /** 刷新：重新拉取名册/快照，并让当前页签重新取数。 */
      const refreshAll = () => {
        setRefreshKey((k) => k + 1)
        api({ op: 'bootstrap' }).then((b) => {
          setEngagements((b && b.engagements) || [])
          if (eng) loadSnapshot(eng)
        }, () => { if (eng) loadSnapshot(eng) })
      }

      const trackPointer = (e, move) => {
        if (e.button !== 0) return
        e.preventDefault()
        e.stopPropagation()
        const up = () => {
          window.removeEventListener('mousemove', move)
          window.removeEventListener('mouseup', up)
        }
        window.addEventListener('mousemove', move)
        window.addEventListener('mouseup', up)
      }
      const startDrag = (e) => {
        if (e.target && e.target.closest && e.target.closest('button,a,input,select,textarea,label')) return
        const sx = e.clientX
        const sy = e.clientY
        const ox = geom.x
        const oy = geom.y
        trackPointer(e, (ev) => setGeom((g) => clampRtGeom({ x: ox + (ev.clientX - sx), y: oy + (ev.clientY - sy), w: g.w, h: g.h })))
      }
      const startResizeLeft = (e) => {
        const sx = e.clientX
        const ox = geom.x
        const ow = geom.w
        trackPointer(e, (ev) => {
          const dx = ev.clientX - sx
          setGeom((g) => clampRtGeom({ x: ox + dx, y: g.y, w: ow - dx, h: g.h }))
        })
      }
      const startResizeRight = (e) => {
        const sx = e.clientX
        const ow = geom.w
        trackPointer(e, (ev) => setGeom((g) => clampRtGeom({ x: g.x, y: g.y, w: ow + (ev.clientX - sx), h: g.h })))
      }
      const startResizeBottom = (e) => {
        const sy = e.clientY
        const oh = geom.h
        trackPointer(e, (ev) => setGeom((g) => clampRtGeom({ x: g.x, y: g.y, w: g.w, h: oh + (ev.clientY - sy) })))
      }
      const startResizeCorner = (e) => {
        const sx = e.clientX
        const sy = e.clientY
        const ow = geom.w
        const oh = geom.h
        trackPointer(e, (ev) => setGeom((g) => clampRtGeom({ x: g.x, y: g.y, w: ow + (ev.clientX - sx), h: oh + (ev.clientY - sy) })))
      }

      /* 切靶标：重新读该靶标的未读快照，并立刻取一次摘要 */
      React.useEffect(() => {
        if (!eng) { setDigest(null); setSeen(null); return undefined }
        setSeen(loadUnread(eng))
        let alive = true
        let digestInflight = false
        const tick = () => {
          if (digestInflight) return        /* 上一轮还没回来，跳过这一轮，别把请求堆起来 */
          digestInflight = true
          api({ op: 'consoleDigest', engagement: eng }).then((r) => {
            if (alive && r && r.ok !== false && r.sections) setDigest(r.sections)
          }, () => { /* 网络异常：不打断，等下一轮 */ })
            .finally(() => { digestInflight = false })
        }
        tick()
        const timer = window.setInterval(tick, 25000)
        return () => { alive = false; window.clearInterval(timer) }
      }, [eng, refreshKey])

      /**
       * 打开某个页签 = 看过这个页签的内容：把当前摘要记成已读。
       * 没读过（第一次打开面板）不算新内容 —— 否则一进来满屏红点，反而看不出"哪里有新东西"。
       */
      const markTabSeen = React.useCallback((tab) => {
        if (!eng) return
        setSeen((prev) => {
          const base = prev || (() => {
            const fresh = {}
            for (const [k, v] of Object.entries((digest || {}))) fresh[k] = { count: Number(v.count || 0), at: v.at || null }
            return fresh
          })()
          const next = Object.assign({}, base)
          const cur = digest && digest[tab]
          if (cur) next[tab] = { count: Number(cur.count || 0), at: cur.at || null }
          saveUnread(eng, next)
          return next
        })
      }, [eng, digest])

      const unreadOf = (tab) => {
        if (!eng || !digest) return false
        if (!seen) return false
        return digestHasNew(seen[tab], digest[tab])
      }

      const stats = (snapshot && snapshot.stats) || {}
      const tabs = [
        ['assets', '资产测绘'], ['env', '环境适配'], ['agents', '智能体'], ['sessions', '会话隧道'],
        ['security', '安全审计'], ['findings', '漏洞战果'],
        ['chain', '攻击链'], ['scores', '得分目标'], ['report', '报告'],
      ]
      const full = isFullWindow()
      const openFull = () => {
        try { window.open(window.location.href.split('#')[0] + '#redteam-full', '_blank', 'noopener') } catch (e) { setErr('无法打开新窗口：' + ((e && e.message) || e)) }
      }
      const exitFull = () => {
        /* 优先关掉脚本打开的窗口；关不掉就退回带侧栏的普通界面 */
        try { window.close() } catch (e) { /* 非脚本打开的窗口无法关闭 */ }
        try {
          if (window.location.hash) {
            window.location.hash = ''
            window.location.reload()
          }
        } catch (e) { /* ignore */ }
      }
      React.useEffect(() => {
        if (!full) return undefined
        const onKey = (e) => { if (e.key === 'Escape') exitFull() }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [full])

      let body
      if (err) body = h('div', { className: 'rt-err' }, err)
      /* 全局页：没有靶标也能看（环境适配 / 智能体概览）。开源版下架知识库和技能库。 */
      else if (st.tab === 'env' || st.tab === 'knowledge' || st.tab === 'skills') body = h(EnvTab, { refreshKey: refreshKey })
      else if (st.tab === 'agents' || st.tab === 'prompts') body = h(AgentsTab, { engagement: eng, refreshKey: refreshKey })
      else if (!eng) {
        body = h('div', { className: 'rt-pane' },
          h('div', { className: 'rt-card' },
            h('h4', null, '还没有靶标'),
            h('div', { style: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)', marginBottom: 8 } },
              '输入攻防演练靶标单位名称，创建演练并开始资产测绘。'),
            h('div', { style: { display: 'flex', gap: 8 } },
              h('input', {
                className: 'rt-input', style: { flex: 1 }, placeholder: '例如：示例科技有限公司',
                value: newName, onChange: (e) => setNewName(e.target.value),
                onKeyDown: (e) => { if (e.key === 'Enter') openEngagement() },
              }),
              h('button', { className: 'rt-btn rt-btn-primary', disabled: creating, onClick: () => openEngagement() },
                creating ? '创建中…' : '创建靶标'))))
      } else if (st.tab === 'assets') body = h(AssetsTab, { engagement: eng, snapshot: snapshot, refreshKey: refreshKey, onRefresh: refreshAll, onData: () => loadSnapshot(eng) })
      else if (st.tab === 'testing') body = h(AssetsTab, { engagement: eng, snapshot: snapshot, refreshKey: refreshKey, onRefresh: refreshAll, onData: () => loadSnapshot(eng) })
      else if (st.tab === 'sessions') body = h(SessionTab, { engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'security') body = h(SecurityTab, { key: eng, engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'findings') body = h(FindingsTab, { engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'chain') body = h(ChainTab, { engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'report') body = h(ReportTab, { engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'attackfiles') body = h(FindingsTab, { engagement: eng, refreshKey: refreshKey })
      else if (st.tab === 'scores') body = h(ScoreTab, { engagement: eng, refreshKey: refreshKey })
      else body = h('div', { className: 'rt-empty' }, '未知页签')

      const shellProps = full
        ? { className: 'rt-full', style: { display: 'flex' } }
        : embedded
          ? { className: 'rt-dock rt-embedded', 'data-open': '1', style: { width: '100%', display: 'flex' } }
          : {
              className: 'rt-dock',
              'data-open': st.open ? '1' : '0',
              style: {
                left: geom.x + 'px',
                top: geom.y + 'px',
                right: 'auto',
                bottom: 'auto',
                width: geom.w + 'px',
                height: geom.h + 'px',
                display: st.open ? 'flex' : 'none',
              },
            }

      return h('div', shellProps,
        (full || embedded) ? null : h('div', { className: 'rt-grip', title: '拖动调整宽度', onMouseDown: startResizeLeft }),
        (full || embedded) ? null : h('div', { className: 'rt-resize-r', title: '拖动调整宽度', onMouseDown: startResizeRight }),
        (full || embedded) ? null : h('div', { className: 'rt-resize-b', title: '拖动调整高度', onMouseDown: startResizeBottom }),
        (full || embedded) ? null : h('div', { className: 'rt-resize-c', title: '拖动调整大小', onMouseDown: startResizeCorner }),
        h('div', { className: 'rt-head', onMouseDown: (full || embedded) ? undefined : startDrag, title: (full || embedded) ? undefined : '按住拖动面板' },
          embedded ? null : h('div', { className: 'rt-title' }, h('span', { className: 'rt-dot' }),
            full ? '演练台 · 全面浏览' : '演练台',
            full ? h('span', { className: 'rt-tag', style: { marginLeft: 6 } }, '独立窗口') : null),
          h('select', {
            className: 'rt-input rt-eng-select',
            style: { maxWidth: embedded ? '100%' : '170px', minWidth: embedded ? '160px' : undefined, flex: embedded ? '1 1 200px' : undefined },
            value: eng || '',
            onChange: (e) => {
              setEng(e.target.value)
              loadSnapshot(e.target.value)
              /* 同步「当前靶标」：原生 skill 目录按它解析技能根 */
              api({ op: 'activateEngagement', engagement: e.target.value }).catch(() => {})
            },
          },
            h('option', { value: '', disabled: true }, engagements.length ? '选择靶标' : '暂无靶标'),
            engagements.map((x) => h('option', { key: x.id, value: x.id }, x.name || x.id || '未命名')),
          ),
          h('div', { className: 'rt-spacer' }),
          embedded ? null : h(VersionBar, null),
          props.shellWorkbench || null,
          full ? h('button', { className: 'rt-btn', title: '回到带侧栏的普通界面（或按 Esc）', onClick: exitFull }, '退出全面浏览') : null,
          embedded ? null : h('button', { className: 'rt-btn', title: '刷新名册、快照与当前页面数据', onClick: refreshAll }, '刷新'),
          (full || embedded) ? null : h('button', { className: 'rt-btn', title: '在新浏览器窗口打开完整控制台', onClick: openFull }, '全面浏览'),
          (full || embedded) ? null : h('button', { className: 'rt-btn', title: '收起面板', onClick: () => setUI({ open: false }) }, '收起')),
        h(SessionBindingBanner, { getSessionId: props?.getSessionId, engagements, browsed: eng, refreshKey }),
        /* 页签栏用标准 tablist/tab 角色：读屏软件据此播报「第几个页签、是否选中」。
           键盘用户 Tab 进来后可用 Enter/Space 切换（由 clickable 提供）。 */
        h('div', { className: 'rt-tabs', role: 'tablist' }, tabs.map((t) => {
          const activate = () => {
            markTabSeen(t[0])
            setUI({ tab: t[0] })
            /* 强制当前页重新取数，避免切页后仍显示上一页缓存视觉 */
            setRefreshKey((k) => k + 1)
          }
          return h('div', Object.assign({}, clickable(activate, { label: t[1] }), {
            key: t[0], className: 'rt-tab' + (st.tab === t[0] ? ' on' : ''),
            role: 'tab',
            'aria-selected': st.tab === t[0] ? 'true' : 'false',
            title: unreadOf(t[0]) ? t[1] + '：有新内容，点开看过红点就会消失' : t[1],
          }), t[1], unreadOf(t[0])
            /* 红点是纯视觉信息，给读屏软件一个文字替代 */
            ? h('span', { className: 'rt-tab-dot', 'aria-label': '有新内容' })
            : null)
        })),
        h('div', { className: 'rt-body', key: 'body-' + st.tab }, h(RtBoundary, { key: st.tab }, body)),
        h('div', { className: 'rt-foot' },
          h('span', null, 'C 段 ' + (stats.segments || 0)),
          h('span', null, '资产 ' + (stats.assets || 0) + '（存活 ' + (stats.liveAssets || 0) + '）'),
          h('span', null, '端口 ' + (stats.openPorts || 0)),
          h('span', null, '指纹 ' + (stats.fingerprints || 0)),
          h('span', null, '漏洞 ' + (stats.vulns || 0)),
          h('span', null, '被动/主动 ' + (stats.passiveSignals || 0) + '/' + (stats.activeSignals || 0)),
          h('div', { className: 'rt-spacer' }),
          full ? h('span', null, '按 Esc 或点右上角「退出全面浏览」回到带侧栏的界面') : null,
          window.location?.origin === 'http://127.0.0.1:49226' ? h('a', { href: '/__harness/health', target: '_blank', rel: 'noopener noreferrer', style: { color: 'inherit' } }, '连接状态') : null,
          h('span', null, 'SQLite · ' + (snapshot && snapshot.engagement ? snapshot.engagement.name : ''))))
    }

    /* ---------------------------------------------------------- 入口按钮 */
    function SidebarButton(props) {
      const st = useUI()
      return h('button', {
        className: 'rt-icon-btn' + (st.open ? ' on' : ''),
        title: 'RedTeam 控制台（常驻右侧栏）',
        onClick: () => setUI({ open: !st.open }),
      }, h('span', { style: { fontSize: 14 } }, '⛨'), props.wide ? h('span', null, 'RedTeam') : null)
    }

    function HeaderButton() {
      const st = useUI()
      return h('button', {
        className: 'rt-hbtn' + (st.open ? ' on' : ''),
        title: 'RedTeam 控制台（常驻右侧栏）',
        onClick: () => setUI({ open: !st.open }),
      }, '⛨ RedTeam')
    }

    /** 侧栏「全面浏览」：在新浏览器窗口打开完整控制台（当前窗口不受影响）。 */
    function FullButton(props) {
      const open = () => {
        try { window.open(window.location.href.split('#')[0] + '#redteam-full', '_blank', 'noopener') } catch { /* 被浏览器拦截 */ }
      }
      return h('button', {
        className: 'rt-icon-btn',
        title: '全面浏览：在新窗口打开完整控制台（当前窗口不受影响；新窗口内按 Esc 退出）',
        onClick: open,
      }, h('span', { style: { fontSize: 14 } }, '⛶'), props.wide ? h('span', null, '全面浏览') : null)
    }

    /* ---------------------------------------------------------- 插件入口 */
    /** 唯一硬依赖：槽位注册表。 */
    const inject = ['slots']

    /**
     * 注入样式 + 三处槽位。样式标签与宽度变量随 fiber 卸载一起移除。
     * @param ctx - 客户端根上下文。
     */
    function applyDrillParts() {
      return { CSS: CSS, Panel: Panel, setUI: setUI, useUI: useUI, isFullWindow: isFullWindow, setDockWidth: setDockWidth };
    }

    exports.inject = inject
			return applyDrillParts();
		})();
/* __DSH_PURGE_DRILL_END__ */

		const AUTH_KEY = "dsh-purge-drill-auth";
		const WELCOME_KEY = "dsh-purge-user-notice-v1";
		let drillGrantGen = 0;
		let drillGrantPosting = 0;
		let drillGrantState = { ready: false, granted: false };
		let drillSyncRetryTimer = null;
		const AUTH_LEGAL_HTML = "<h3>Solemn Legal Disclaimer and Notice on Compliant Use</h3>\n    <p>You must read this notice in full before entering the drill console. This project is a non-profit open-source project that complies with national laws and regulations and with the rules of the platforms on which it is used, and is provided only for study, research, and technical reference. No entity may use this project for commercial sale, paid resale, or profit from illicit or gray-market activities.</p>\n    <p>The developers firmly oppose and prohibit all forms of illegal or criminal activity, and will never support, encourage, or assist unauthorized network attacks, exploitation, data theft, unauthorized intrusion into computer information systems, or the generation of illegal or prohibited content. Any use of this project for illegal or criminal activity is unrelated to the developers, and the perpetrator bears full legal responsibility independently in accordance with the law. The following clauses may not be circumvented under the pretext of scientific research, teaching, testing, demonstration, or internal study.</p>\n    <h3>1. This repository contains no illegal content</h3>\n    <p>The code, documentation, patches, and default prompts published by dsh-purge are not trojans, backdoors, unauthorized penetration tools, ransomware, or credential-stuffing scripts, nor are they attack payloads aimed at public networks or third-party systems. The project does not provide illegal content and does not instigate, organize, or assist in any illegal or criminal activity.</p>\n    <h3>2. Local operations do not constitute external authorization</h3>\n    <p>Applying patches, writing, rolling back, and uninstalling all take place within local files and local processes. These operations do not scan, probe, intrude into, or send attack traffic to any public host or unauthorized system, and this machine must not be used as a jump host.</p>\n    <p>If the plugin has update checks enabled, it may only access this plugin's own GitHub repository to verify the version. That access is unrelated to network attacks on third-party systems and must not be interpreted as authorization for external penetration testing.</p>\n    <h3>3. Permitted scope of use</h3>\n    <p>Use is permitted only in environments you can prove you are entitled to handle: the official Harness installed locally on a machine you administer; offline, local synthetic targets; cybersecurity exercise ranges for which the owner has issued lawful written authorization; and controlled environments in a compliant laboratory. Written authorization must correspond to specific targets, time, and scope. Entering only an organization name, or relying only on an oral statement, does not constitute authorization.</p>\n    <p>Targets without the owner's lawful written authorization, publicly reachable online systems, production services, and critical information infrastructure such as energy, transportation, water resources, finance, public services, and e-government systems must not be used as exercise targets.</p>\n    <h3>4. Laws that must be complied with, by article and paragraph</h3>\n    <p>Criminal Law of the People's Republic of China, Article 285(1): It is prohibited to violate state regulations and intrude into computer information systems in the fields of state affairs, national defense, and cutting-edge science and technology.</p>\n    <p>Article 285(2): It is prohibited to intrude into computer information systems other than those specified in the preceding paragraph, or to use other technical means to obtain data stored, processed, or transmitted in such systems, or to exercise illegal control over such systems.</p>\n    <p>Article 285(3): It is prohibited to provide programs or tools specially used for intruding into or illegally controlling computer information systems; providing programs or tools to others while knowing that they intend to intrude or illegally control is likewise prohibited.</p>\n    <p>Article 286(1): It is prohibited to delete, modify, add to, or interfere with the functions of a computer information system, causing the system to fail to operate normally.</p>\n    <p>Article 286(2): It is prohibited to delete, modify, or add to data and application programs stored, processed, or transmitted in a system.</p>\n    <p>Article 286(3): It is prohibited to intentionally create or spread destructive programs such as computer viruses that affect the normal operation of computer systems.</p>\n    <p>Article 287: It is prohibited to use computers to commit financial fraud, theft, embezzlement, misappropriation of public funds, theft of state secrets, or other crimes.</p>\n    <p>Article 287-1, paragraph 1, item (1): It is prohibited to establish websites or communication groups used for illegal or criminal activities such as fraud, teaching criminal methods, or producing or selling prohibited or controlled items.</p>\n    <p>Article 287-1, paragraph 1, item (2): It is prohibited to publish information about producing or selling drugs, firearms, obscene materials, or other prohibited or controlled items, or other illegal or criminal information.</p>\n    <p>Article 287-1, paragraph 1, item (3): It is prohibited to publish information for the purpose of committing fraud or other illegal or criminal activities.</p>\n    <p>Article 287-2: It is prohibited to knowingly provide technical support, advertising promotion, payment settlement, or other assistance to others who use information networks to commit crimes.</p>\n    <p>Article 253-1, paragraphs 1 and 3: It is prohibited to sell or provide citizens' personal information to others; it is prohibited to steal or otherwise unlawfully obtain citizens' personal information.</p>\n    <p>Cybersecurity Law of the People's Republic of China, Article 13, paragraph 2: When using networks, one must not endanger cybersecurity, and must not use networks to engage in activities that endanger national security, honor, and interests; incite subversion of state power or overthrow of the socialist system; incite secession or undermine national unity; promote terrorism or extremism; promote ethnic hatred or ethnic discrimination; spread violence or obscene and pornographic information; fabricate or spread false information to disrupt economic and social order; or infringe on the reputation, privacy, intellectual property, or other lawful rights and interests of others.</p>\n    <p>Article 14: It is prohibited to use networks to engage in activities that endanger the physical and mental health of minors.</p>\n    <p>Article 29: It is prohibited to illegally intrude into others' networks, interfere with the normal functions of others' networks, or steal network data; it is prohibited to provide programs or tools specially used for intruding into networks, interfering with the normal functions of networks and protective measures, or stealing network data; when knowing that others are engaged in activities endangering cybersecurity, it is prohibited to provide them with technical support, advertising promotion, payment settlement, or other assistance.</p>\n    <p>Article 33: Critical information infrastructure in public communications and information services, energy, transportation, water resources, finance, public services, and e-government is subject to priority protection. Without lawful authorization, no one may intrude into, interfere with, or destroy it.</p>\n    <p>Article 46: It is prohibited to steal or otherwise unlawfully obtain personal information, and it is prohibited to unlawfully sell or unlawfully provide personal information to others.</p>\n    <p>Article 48: It is prohibited to establish websites or communication groups used for fraud, teaching criminal methods, producing or selling prohibited or controlled items, or other illegal or criminal activities; it is prohibited to use networks to publish information involving the above illegal or criminal activities.</p>\n    <p>Article 50: Electronic information sent and application software provided must not contain malicious programs, and must not contain information that laws or administrative regulations prohibit from being published or transmitted.</p>\n    <p>Data Security Law of the People's Republic of China, Article 8: Data processing activities must not endanger national security or the public interest, or harm the lawful rights and interests of individuals or organizations.</p>\n    <p>Article 32(1): Data must be collected by lawful and proper means; data must not be stolen or otherwise unlawfully obtained.</p>\n    <p>Article 32(2): Where laws or administrative regulations specify the purpose and scope of data collection and use, data may only be collected and used within that purpose and scope.</p>\n    <p>Article 51: Those who steal or otherwise unlawfully obtain data, or thereby harm the lawful rights and interests of individuals or organizations, shall be punished in accordance with relevant laws and administrative regulations.</p>\n    <p>Personal Information Protection Law of the People's Republic of China, Article 5: Personal information must be processed lawfully, properly, necessarily, honestly, and in good faith, and must not be processed by misleading, fraudulent, coercive, or other such means.</p>\n    <p>Article 6, paragraphs 1 and 2: Personal information must be processed for a clear and reasonable purpose and in a way directly related to that purpose, using methods that have the least impact on individual rights and interests; collection must be limited to the minimum scope necessary to achieve the processing purpose, and excessive collection is prohibited.</p>\n    <p>Article 10: It is prohibited to unlawfully collect, use, process, or transmit others' personal information, and to unlawfully buy, sell, provide, or disclose others' personal information; it is prohibited to engage in personal information processing activities that endanger national security or the public interest.</p>\n    <p>Article 13: Personal information must not be processed where none of the following applies: the individual's consent has been obtained; processing is necessary for concluding or performing a contract to which the individual is a party; processing is necessary for performing statutory duties or obligations; processing is necessary for responding to public health emergencies or protecting the life, health, and property of the individual in an emergency; processing is necessary for public-interest news reporting or public opinion supervision within a reasonable scope; the personal information has already been lawfully disclosed by the individual or otherwise lawfully disclosed; or other circumstances provided by laws or administrative regulations.</p>\n    <p>Articles 28 and 29: Biometrics, medical health, financial accounts, whereabouts and movement trajectories, and personal information of minors under the age of 14 are sensitive personal information. It must not be processed without a specific purpose, sufficient necessity, and strict protection measures, and without the individual's separate consent.</p>\n    <p>In addition, other currently effective laws, administrative regulations, and regulatory provisions, as well as the terms of service and abuse policies of the model used, must also be complied with.</p>\n    <h3>5. Prohibited directions under this notice</h3>\n    <p>Unauthorized access. It is prohibited to register as a target any organization, domain, address, public network system, production service, or critical information infrastructure for which there is no written authorization, and to scan, probe, intrude into, control, or send traffic to it. Corresponds to Criminal Law Article 285(1) and (2), and Cybersecurity Law Articles 29 and 33.</p>\n    <p>Damage and malicious programs. It is prohibited to delete, modify, add to, or interfere with others' system functions or the data and application programs therein; to create or spread viruses, ransomware, or other destructive programs; or to plant malicious programs in information or software. Corresponds to Criminal Law Article 286(1) to (3), and Cybersecurity Law Article 50.</p>\n    <p>Tools and assistance. It is prohibited to provide this project or this machine to others for intrusion, illegal control, or data theft; or, while knowing that the other party is committing a cybercrime, to still provide programs, tools, technical support, advertising promotion, or payment settlement. Corresponds to Criminal Law Article 285(3) and Article 287-2, and Cybersecurity Law Article 29.</p>\n    <p>Data. It is prohibited to steal, unlawfully collect, use beyond scope, disclose, sell, or provide to others business data, accounts, passwords, and other protected data. Corresponds to Data Security Law Articles 8, 32, and 51.</p>\n    <p>Personal information. It is prohibited to unlawfully collect, use, process, transmit, buy, sell, provide, or disclose others' personal information; to over-collect; to process by misleading, fraudulent, or coercive means; or to process biometric, medical health, financial account, whereabouts, and children's personal information without authorization. Corresponds to Criminal Law Article 253-1(1) and (3); Cybersecurity Law Article 46; Personal Information Protection Law Articles 5, 6, 10, 13, 28, and 29.</p>\n    <p>Fraud and illegal information. It is prohibited to establish or use websites or groups to commit fraud, teach criminal methods, or produce or sell prohibited or controlled items; to publish such information; or to use computers to commit fraud, theft, embezzlement, misappropriation of public funds, or theft of state secrets. Corresponds to Criminal Law Article 287, Article 287-1(1)(i) to (iii), and Cybersecurity Law Article 48.</p>\n    <p>Content. It is prohibited to generate or spread content that endangers national security, honor, and interests; to incite subversion or secession; to promote terrorism, extremism, or ethnic hatred; to spread violence, obscene or pornographic content, or gambling; to fabricate or spread false information that disrupts economic and social order; to infringe on reputation, privacy, or intellectual property; or to produce content that endangers the physical and mental health of minors. Corresponds to Cybersecurity Law Article 13, paragraph 2, and Article 14.</p>\n    <p>Spread of results. Records, asset information, and files created during exercises may remain only within the targets and time limits specified in the written authorization; they must not be handed to anyone not entitled to know them, and must not be repurposed beyond the authorization.</p>\n    <h3>6. Liability rests with the user</h3>\n    <p>This project is provided \"as is\" under the MIT License. The developers make no warranty as to completeness, security, or fitness for purpose. Users bear independent and full civil, administrative, and criminal liability for their own downloading, deployment, operation, modification, and dissemination, as well as for all inputs and outputs. The author and contributors are not liable for direct, indirect, or joint liability arising from abuse.</p>\n    <p>By checking the boxes, the operator confirms on their own behalf; this cannot substitute for someone who has not read this notice, nor can it present another person's system as already authorized.</p>\n    <h3>7. Breach terminates the authorization</h3>\n    <p>Once used for illegal attacks, malicious activity, or any of the prohibited directions above, the license to use this project automatically terminates from the date of that act and is irrevocable. Use must stop immediately, and the project's code, scripts, and derived data must be destroyed, with liability borne in accordance with the law. After the authorization terminates, the drill console must not be opened or used any further.</p>\n    <h3>8. Relationship with DeepSeek</h3>\n    <p>This project is an independent open-source project and has no affiliation, commercial cooperation, authorization, or official endorsement with DeepSeek or its affiliates. The word \"official\" in this document only means that the evaluated object is the official DeepSeek Harness software package installed locally by the user; it does not mean that DeepSeek officially develops, endorses, or guarantees this plugin.</p>\n    <p>End of document. Only after the countdown ends, you scroll to here, and check all three boxes does it mean that you, as yourself, accept this notice and complete this drill console authorization.</p>";

		function readWelcomeAck() {
			try { return window.localStorage.getItem(WELCOME_KEY) === "1"; } catch { return false; }
		}
		function writeWelcomeAck() {
			try { window.localStorage.setItem(WELCOME_KEY, "1"); } catch { /* ignore */ }
		}

		function readDrillAuth() {
			if (drillGrantState.ready) return drillGrantState.granted;
			try { return window.localStorage.getItem(AUTH_KEY) === "1"; } catch { return false; }
		}
		function setDrillAuthLocal(ok) {
			try {
				if (ok) window.localStorage.setItem(AUTH_KEY, "1");
				else window.localStorage.removeItem(AUTH_KEY);
			} catch { /* ignore */ }
			drillGrantState = { ready: true, granted: !!ok };
		}
		function writeDrillAuth(ok) {
			drillGrantGen += 1;
			const gen = drillGrantGen;
			setDrillAuthLocal(ok);
			if (!ok) return;
			drillGrantPosting += 1;
			fetch("/dsh-purge/drill-grant", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: "{}",
			}).then((r) => r.json()).then((saved) => {
				if (gen !== drillGrantGen) return;
				setDrillAuthLocal(!!(saved && saved.granted));
			}).catch(() => { /* 页面先记住，下次同步再写入当前安装目录 */ })
				.finally(() => { drillGrantPosting = Math.max(0, drillGrantPosting - 1); });
		}
		function syncDrillGrant(attempt) {
			const n = attempt || 0;
			const gen = drillGrantGen;
			/* 复位上一次调度的重试 timer,避免多次 writeDrillAuth 叠加链条 */
			if (drillSyncRetryTimer) { try { clearTimeout(drillSyncRetryTimer); } catch { /* ignore */ } drillSyncRetryTimer = null; }
			fetch("/dsh-purge/drill-grant", { method: "GET" })
				.then((r) => r.json())
				.then((r) => {
					if (gen !== drillGrantGen) return;
					if (!r || r.ok === false) throw new Error("grant");
					if (r.granted) {
						setDrillAuthLocal(true);
						if (dockBus.authOpen) setDock({ authOpen: false });
						return;
					}
					if (drillGrantPosting > 0) return;
					setDrillAuthLocal(false);
					if (dockBus.authOpen || dockBus.tab === "drill") {
						setDock({ open: true, tab: "drill", authOpen: true, pending: dockBus.pending || "tab" });
					}
				})
				.catch(() => {
					if (gen !== drillGrantGen) return;
					if (n < 5) {
						drillSyncRetryTimer = window.setTimeout(() => {
							drillSyncRetryTimer = null;
							syncDrillGrant(n + 1);
						}, 400);
					}
				});
		}

		let dockBus = (() => {
			const full = __dshPurgeDrill.isFullWindow();
			return { open: full, tab: full ? "drill" : "clean", authOpen: full && !readDrillAuth(), pending: "tab", listeners: new Set() };
		})();
		function getDock() { return dockBus; }
		function setDock(patch) {
			dockBus = Object.assign({}, dockBus, patch);
			dockBus.listeners.forEach((fn) => { try { fn(dockBus); } catch { /* ignore */ } });
		}
		function useDock() {
			const [st, setSt] = useState(dockBus);
			useEffect(() => {
				const fn = (next) => setSt(next);
				dockBus.listeners.add(fn);
				return () => { dockBus.listeners.delete(fn); };
			}, []);
			return st;
		}

		let vmShellWorkbenchHost = null;
		let vmShellWorkbenchLifetime = null;
		const vmShellRecent = new Map();
		async function openVmShellWorkbench(host, signal, options = {}) {
			signal?.throwIfAborted();
			const sidebar = host?.get?.("sidebarRight") ?? host?.sidebarRight;
			const terminals = host?.get?.("webTerminals") ?? host?.webTerminals;
			if (!sidebar || !terminals || typeof sidebar.commandTarget !== "function") throw new Error("官方终端尚未就绪，请刷新页面后重试。");
			const target = sidebar.commandTarget();
			if (!target || !sidebar.isTargetCurrent(target)) throw new Error("请先选择或新建会话，再打开 Shell 工作台。");
			if (options.sessionId && options.sessionId !== target.sessionId) throw new Error("会话已切换，请刷新终端列表。");
			const before = sidebar.openTabs.getSnapshot();
			const owned = before.filter(tab => tab.sessionId === target.sessionId && tab.kind === "terminal");
			const model = tab => {
				const params = sidebar.tabDomain.occurrence(target.sessionId, { id: tab.tabId }).navigation.getSnapshot().params;
				return terminals.view(target.sessionId, tab.tabId, tab.contentId, params?.terminalId, params?.shellPath);
			};
			const usable = tab => { const state = model(tab).state.getSnapshot(); return !["closed", "closing", "failed"].includes(state.phase) && !["exited", "failed"].includes(state.info?.state); };
			let existing;
			if (options.tabId) {
				existing = owned.find(tab => tab.tabId === options.tabId);
				if (!existing || !usable(existing)) throw new Error("所选终端已结束或不属于当前会话，请选择其他终端或新建。");
			} else if (options.action !== "new") {
				const active = sidebar.active?.()?.id, recent = vmShellRecent.get(target.sessionId);
				const candidates = owned.filter(usable);
				const connected = candidates.filter(tab => model(tab).state.getSnapshot().phase === "connected");
				const preferred = connected.length ? connected : candidates;
				existing = preferred.find(tab => tab.tabId === active) || preferred.find(tab => tab.contentId === recent) || preferred[preferred.length - 1];
			}
			if (existing) {
				if (!sidebar.isExpanded()) sidebar.toggleExpanded();
				sidebar.focus(existing.tabId);
			} else {
				sidebar.openTabFromTarget("terminal", target);
			}
			const tab = existing || sidebar.openTabs.getSnapshot().find(item => item.sessionId === target.sessionId && item.kind === "terminal" && !before.some(old => old.sessionId === item.sessionId && old.tabId === item.tabId && old.contentId === item.contentId));
			if (!tab) throw new Error("终端标签未能打开，当前演练已保留。");
			const view = model(tab);
			if (view.state.getSnapshot().phase === "disconnected" || options.action === "reconnect") view.connect();
			// Observe the official model; allocation, input and process ownership remain with the native terminal UI.
			await new Promise((resolve, reject) => {
				let settled = false, unsubscribe;
				const finish = error => {
					if (settled) return;
					settled = true; clearTimeout(timer); unsubscribe?.(); signal?.removeEventListener("abort", aborted);
					error ? reject(error) : resolve();
				};
				const aborted = () => finish(new Error("终端打开已取消，当前演练已保留。"));
				const inspect = () => {
					const phase = view.state.getSnapshot().phase;
					if (phase === "connected") finish();
					else if (["failed", "closed", "closing", "disconnected"].includes(phase)) finish(new Error("终端启动或连接失败，当前演练已保留；请在右侧关闭失效终端后重试。"));
				};
				const timer = setTimeout(() => finish(new Error("等待终端就绪超时，当前演练已保留；请刷新页面后重试。")), 15000);
				signal?.addEventListener("abort", aborted, { once: true });
				if (signal?.aborted) return aborted();
				try { unsubscribe = view.state.subscribe(inspect); if (settled) unsubscribe(); else inspect(); } catch (error) { finish(error); }
			});
			signal?.throwIfAborted();
			if (sidebar.mounted.getSnapshot() !== target.sessionId) throw new Error("会话已切换，请在当前会话重新打开 Shell 工作台。");
			if (view.state.getSnapshot().phase !== "connected" || !sidebar.openTabs.getSnapshot().some(item => item.sessionId === target.sessionId && item.tabId === tab.tabId && item.contentId === tab.contentId)) throw new Error("终端已关闭或变化，当前演练已保留。");
			vmShellRecent.set(target.sessionId, tab.contentId);
			// Preserve the running page and PTY; leave the drill overlay only after the connection is observed.
			if (window.location.hash === "#redteam-full") window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
			__dshPurgeDrill.setUI({ open: false });
			setDock({ open: false });
		}
		async function readVmDirectory(host, input, signal, allowRoot = false) {
			const root = "/home/purge/workspace", path = String(input || "").trim().replace(/\/+$/, "");
			if ((!allowRoot || path !== root) && !path.startsWith(root + "/") || /[\u0000-\u001f\u007f\\]/.test(path) || path.includes("//") || path.length > 2048 || path.split("/").some(part => part === "." || part === "..")) throw new Error("请选择 /home/purge/workspace 下的项目目录，不要选择工作区根目录。");
			const picker = (host?.get?.("remote") ?? host?.remote)?.directoryPicker;
			if (!picker?.list) throw new Error("目录浏览尚未就绪，请刷新 Harness 后重试。");
			const controller = new AbortController(), combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
			let rejectAbort; const aborted = () => rejectAbort?.(combined.reason || new Error("目录检查已取消。"));
			const timer = setTimeout(() => controller.abort(new Error("目录检查超时，请重试。")), 10000);
			try {
				combined.throwIfAborted();
				const cancelled = new Promise((_, reject) => { rejectAbort = reject; combined.addEventListener("abort", aborted, { once: true }); });
				const result = await Promise.race([picker.list(path, combined), cancelled]);
				combined.throwIfAborted();
				if (!result.ok) throw new Error("目录不存在或无法读取，请检查 VM 路径后重试。");
				const value = result.value, canonical = String(value.path || "").replace(/\/+$/, "");
				if ((canonical !== root || !allowRoot) && !canonical.startsWith(root + "/")) throw new Error("目录不在 VM 工作区中，请重新选择。");
				const entries = (value.entries || []).filter(entry => !entry.hidden && typeof entry.path === "string" && entry.path.startsWith(root + "/") && !entry.path.split("/").some(part => part === "." || part === ".."));
				return { path: canonical, entries: entries.slice(0, 100), truncated: Boolean(value.truncated || entries.length > 100) };
			} finally { clearTimeout(timer); combined.removeEventListener("abort", aborted); }
		}
		function vmTerminalUnavailable(row) {
			return row.processState === "missing" || ["exited", "failed"].includes(row.processState || row.state.info?.state) || ["closed", "closing", "failed"].includes(row.state.phase);
		}
		function vmTerminalLabel(row) {
			if (row.processState === "missing") return "已失效";
			const process = row.processState || row.state.info?.state;
			if (process === "exited") return "已退出";
			if (process === "failed") return "进程失败";
			if (row.state.phase === "connected") return "已连接";
			if (row.processVerified === false) return process === "running" ? "上次运行中 · 当前待核对" : "进程状态待核对";
			if (process === "running" && ["idle", "loading", "disconnected"].includes(row.state.phase)) return "运行中 · 待连接";
			return ({ disconnected: "已断开", failed: "连接失败", closed: "已结束", closing: "关闭中", creating: "启动中", connecting: "连接中", loading: "正在核对…", idle: "待连接" })[row.state.phase] || "状态待核对";
		}
		function observeVmTerminals(host, onChange, onError, signal) {
			const service = name => host?.get?.(name) ?? host?.[name];
			const sidebar = service("sidebarRight"), terminals = service("webTerminals"), remote = service("remote");
			let disposed = false, sessionId, models = [], inventory = null, agentDir = "读取中…", subscriptions = [], generation = 0, reading, request, lastSnapshot, checkedAt = null, checkedMono = null, failed = false, expiry;
			const mono = () => typeof performance === "undefined" ? Date.now() : performance.now();
			const current = () => !disposed && !signal?.aborted && sidebar?.mounted.getSnapshot() === sessionId;
			const publish = () => {
				if (!current()) return;
				const rows = models.map(({ tab, view }) => {
					const state = view.state.getSnapshot(), listed = inventory?.get(view.id);
					const age = checkedAt === null ? Infinity : Math.max(Date.now() - checkedAt, mono() - checkedMono);
					const processVerified = !failed && checkedAt !== null && Date.now() >= checkedAt && mono() >= checkedMono && age < 15000;
					const info = ["exited", "failed"].includes(state.info?.state) ? state.info : listed || state.info;
					return { ...tab, state: { ...state, info }, processState: ["exited", "failed"].includes(state.info?.state) ? state.info.state : state.phase === "connected" ? state.info?.state || "running" : inventory ? (listed ? info.state : "missing") : info?.state, processVerified };
				});
				rows.sort((a, b) => Number(vmTerminalUnavailable(a)) - Number(vmTerminalUnavailable(b)));
				const signature = JSON.stringify({ sessionId, agentDir, checkedAt, failed, rows: rows.map(row => ({ tabId: row.tabId, contentId: row.contentId, phase: row.state.phase, writable: row.state.writable, processState: row.processState, processVerified: row.processVerified, info: row.state.info, title: row.state.title })) });
				if (signature !== lastSnapshot) { lastSnapshot = signature; onChange({ sessionId, rows, agentDir, lastCheckedAt: checkedAt, checkFailed: failed }); }
			};
			const refresh = () => {
				if (!current() || !sessionId) return Promise.resolve();
				if (reading) return reading;
				const epoch = generation, captured = sessionId, controller = new AbortController(); request = controller;
				let failAbort; const abort = () => failAbort?.(controller.signal.reason || new Error("状态读取已取消"));
				const deadline = setTimeout(() => controller.abort(new Error("状态读取超时")), 10000);
				const cancelled = new Promise((_, reject) => { failAbort = reject; controller.signal.addEventListener("abort", abort, { once: true }); });
				const operation = (async () => {
					try {
						const [list, environment] = await Promise.race([Promise.all([remote.terminal.list(captured), remote.terminal.environment(captured, controller.signal)]), cancelled]);
						if (!current() || epoch !== generation || captured !== sessionId) return;
						if (!list.ok || !environment.ok) throw new Error("读取失败");
						inventory = new Map(list.value.map(info => [info.id, info])); agentDir = environment.value.cwd; checkedAt = Date.now(); checkedMono = mono(); failed = false; clearTimeout(expiry); expiry = setTimeout(publish, 15000); publish(); onError("");
					} catch { if (current() && epoch === generation) { failed = true; publish(); onError("终端状态暂时无法核对，请刷新列表重试。"); } }
					finally { clearTimeout(deadline); controller.signal.removeEventListener("abort", abort); if (request === controller) { request = null; reading = null; } }
				})();
				reading = operation; return operation;
			};
			const topology = () => {
				if (disposed) return;
				generation++; request?.abort(); request = null; reading = null;
				subscriptions.forEach(fn => fn()); subscriptions = [];
				const next = sidebar?.mounted.getSnapshot();
				if (sessionId !== next) { clearTimeout(expiry); inventory = null; agentDir = "读取中…"; checkedAt = checkedMono = null; failed = false; }
				sessionId = next;
				models = (sidebar?.openTabs.getSnapshot() || []).filter(tab => tab.sessionId === sessionId && tab.kind === "terminal").map(tab => {
					const params = sidebar.tabDomain.occurrence(sessionId, { id: tab.tabId }).navigation.getSnapshot().params;
					return { tab, view: terminals.view(sessionId, tab.tabId, tab.contentId, params?.terminalId, params?.shellPath) };
				});
				models.forEach(({ view }) => subscriptions.push(view.state.subscribe(publish))); publish(); refresh();
			};
			const stopTabs = sidebar?.openTabs.subscribe?.(topology), stopSession = sidebar?.mounted.subscribe?.(topology);
			const timer = setInterval(() => { publish(); refresh(); }, 5000);
			const dispose = () => { if (disposed) return; disposed = true; generation++; request?.abort(); subscriptions.forEach(fn => fn()); stopTabs?.(); stopSession?.(); clearInterval(timer); clearTimeout(expiry); signal?.removeEventListener("abort", dispose); };
			signal?.addEventListener("abort", dispose, { once: true });
			if (signal?.aborted) dispose(); else topology();
			return { refresh, dispose };
		}
		async function importVmClone(host, input, confirm, signal, onStage = () => {}) {
			const path = String(input || "").trim().replace(/\/+$/, "");
			if (path === "/home/purge/workspace" || !path.startsWith("/home/purge/workspace/") || /[\u0000-\u001f\u007f\\]/.test(path) || path.length > 2048 || path.split("/").some(part => part === "." || part === "..")) throw new Error("请输入 /home/purge/workspace 下已存在的项目绝对路径。");
			const workspaces = host?.get?.("workspaces") ?? host?.workspaces;
			const ui = host?.get?.("uiWorkspace") ?? host?.uiWorkspace;
			const sidebar = host?.get?.("sidebarRight") ?? host?.sidebarRight;
			if (!workspaces || !ui || !sidebar) throw new Error("工作区服务尚未就绪，请刷新页面。");
			signal?.throwIfAborted();
			if (!confirm("将目录加入 VM 工作区并打开该工作区的会话：\n" + path + "\n\n旧会话、草稿和终端会保留。不会自动执行仓库代码。")) return { cancelled: true };
			signal?.throwIfAborted();
			const records = importVmClone.operations ??= new WeakMap();
			let pending = records.get(workspaces); if (!pending) records.set(workspaces, pending = new Map());
			let record = pending.get(path);
			const known = readVmImportOutcome(host, path);
			if (!record?.pending && known.state === "removed") { pending.delete(path); return { removed: true, path }; }
			if (record?.workspace && !known.confirmed) return { uncertain: true, path };
			if (!record?.pending && known.workspace) { record ??= { pending: false }; record.workspace = known.workspace; pending.set(path, record); }
			if (record?.pending || record && !record.workspace) return { uncertain: true, path };
			const previous = sidebar.mounted.getSnapshot(), controller = new AbortController();
			let active = true, rejectAbort;
			const abort = () => { active = false; controller.abort(); rejectAbort?.(new Error("导入等待已停止，结果尚未确认。")); };
			const timer = setTimeout(abort, 15000); signal?.addEventListener("abort", abort, { once: true });
			const cancelled = new Promise((_, reject) => { rejectAbort = reject; });
			const guard = () => { if (!active || signal?.aborted || sidebar.mounted.getSnapshot() !== previous) throw new Error("导入导航已取消。"); };
			try {
				if (!record) { record = { pending: true, workspace: null }; pending.set(path, record); }
				record.pending = true;
				const operation = (async () => {
					try {
						if (!record.workspace) {
							onStage("正在添加工作区…");
							try { record.workspace = await workspaces.create({ path }); }
							catch (error) {
								// These unary Gateway checks run before the Workspace method. invalid-path can also wrap storage failures.
								if (error?.name === "WorkspaceCreateError" && ["gateway/arguments-invalid", "gateway/input-invalid"].includes(error.rpcError?.code)) {
									if (pending.get(path) === record) pending.delete(path);
									return { rejected: true, path };
								}
								throw error;
								}
						}
						if (!active || signal?.aborted) return { uncertain: true, path };
						if (sidebar.mounted.getSnapshot() !== previous) return { opened: false, workspace: record.workspace };
						onStage("已添加，正在打开会话…"); let openedSession;
						await ui.openWorkspace(record.workspace.workspaceId, id => { guard(); openedSession = id; });
						if (!active || signal?.aborted) return { uncertain: true, path };
						return { opened: Boolean(openedSession && sidebar.mounted.getSnapshot() === openedSession), workspace: record.workspace };
					} finally { record.pending = false; }
				})();
				return await Promise.race([operation, cancelled]);
			} catch (error) { if (controller.signal.aborted || signal?.aborted) return { uncertain: true, path }; throw error; }
			finally { active = false; clearTimeout(timer); signal?.removeEventListener("abort", abort); }
		}
		function readVmImportOutcome(host, path) {
			const workspaces = host?.get?.("workspaces") ?? host?.workspaces;
			const record = importVmClone.operations?.get(workspaces)?.get(path);
			const snapshot = workspaces?.list?.getSnapshot();
			const listReady = snapshot?.phase === "ready" && snapshot.state !== "error" && snapshot.state !== "loading";
			const listed = listReady ? snapshot.items?.find(item => item.path === path) : null;
			const workspace = listReady ? listed : record?.workspace;
			return { state: workspace ? "registered" : listReady && record?.workspace && !record.pending ? "removed" : "unconfirmed", confirmed: Boolean(listReady && listed), listReady, pending: Boolean(record?.pending), path, workspace: workspace || null };
		}

		function vmToolchainLabel(row) {
				if (row.queryState === "timeout" && !row.installed?.available) return "查询超时 · 本地版本未确认";
			if (!row.installed?.available) return "本地版本未确认";
			const match = row.comparison || {};
				if (row.queryState === "timeout") return match.matchesLatestRelease === true ? "部分查询超时 · 正式版一致" : match.matchesDefaultBranch === true ? "部分查询超时 · main 一致" : "查询超时 · 未确认";
			if (match.matchesLatestRelease === true) return match.matchesDefaultBranch === false ? "正式版一致 · main 不同" : "正式版一致";
			if (match.matchesDefaultBranch === true) return match.matchesLatestRelease === false ? "main 一致 · Release 不同" : "main 一致 · Release 未确认";
			if (row.latestRelease?.state === "no_release") return "暂无正式 Release";
			return match.matchesLatestRelease === false || match.matchesDefaultBranch === false ? "存在提交差异" : "未确认";
		}
		function vmToolchainIssues(row) {
			const messages = { rate_limited: "GitHub 正在限流，请稍后重试。", access_denied: "GitHub 拒绝了查询，请检查现有连接。", local_modified: "本地文件有改动或缺失，请先核对安装内容。", container_unavailable: "容器元数据不可用，请检查现有 PentAGI 服务。", installation_unavailable: "本地安装信息不可用，请先核对安装。", timeout: "查询超时，已确认的字段仍会保留。", network_unavailable: "GitHub 连接或响应异常，请稍后重试。", release_commit_unavailable: "正式版标签已找到，提交仍未确认。", unexpected_redirect: "GitHub 返回了非预期跳转，请核对固定项目来源。", inspection_failed: "检查未完成，请核对本地安装后重试。", repository_unverified: "仓库来源尚未确认，暂时不能判断是否有正式版。", container_metadata_unverified: "容器版本标签不完整，请核对现有镜像元数据。" };
			const result = [];
			for (const [key, label] of [["installed", "本地安装"], ["latestRelease", "正式 Release"], ["defaultBranch", "默认分支"]]) {
				const item = row[key]; if (!item) continue;
				if (item.errorCode || item.available === false || ["unavailable", "timeout"].includes(item.state) || item.reason) result.push(label + "：" + (messages[item.errorCode] || "结果未确认，请核对连接或安装后重试。"));
			}
			return [...new Set(result)];
		}
		function mergeVmToolchainReport(previous, next, project, requestOrder = 0) {
			if (!Number.isSafeInteger(requestOrder) || requestOrder < 0) throw Error("查询顺序无法确认，请重试。");
			const names = ["rea", "reverse-skill", "pentagi"], expected = project === "all" ? names : names.includes(project) ? [project] : [];
			if (!expected.length || !Array.isArray(next?.projects) || next.projects.length !== expected.length || !Number.isFinite(Date.parse(next.checkedAt))) throw Error("版本结果范围或检查时间无法确认，请重试。");
			const received = new Set();
			const updates = next.projects.map(row => {
				if (!expected.includes(row?.project) || received.has(row.project)) throw Error("版本结果与请求项目不一致，请重试。");
				received.add(row.project); const checkedAt = row.checkedAt || next.checkedAt;
				if (!Number.isFinite(Date.parse(checkedAt))) throw Error("项目检查时间无法确认，请重试。");
				return { ...row, checkedAt, _requestOrder: requestOrder };
			});
			const rows = new Map((previous?.projects || []).filter(row => names.includes(row.project)).map(row => [row.project, row]));
			for (const row of updates) { const old = rows.get(row.project); if (!old || requestOrder >= (old._requestOrder || 0)) rows.set(row.project, row); }
			return { ...(requestOrder < (previous?._requestOrder || 0) ? previous : next), _requestOrder: Math.max(previous?._requestOrder || 0, requestOrder), projects: names.filter(name => rows.has(name)).map(name => rows.get(name)) };
		}
		async function readVmToolchain(signal, project = "all") {
			if (!["all", "rea", "reverse-skill", "pentagi"].includes(project)) throw Error("只能检查固定的三个项目。");
			const controller = new AbortController();
			const cancel = () => controller.abort(Error("版本查询已取消。"));
			if (signal?.aborted) cancel(); else signal?.addEventListener("abort", cancel, { once: true });
			let rejectAbort;
			const aborted = new Promise((_, reject) => { rejectAbort = () => reject(controller.signal.reason || Error("版本查询已取消。")); controller.signal.addEventListener("abort", rejectAbort, { once: true }); if (controller.signal.aborted) rejectAbort(); });
			const timer = setTimeout(() => controller.abort(Error("版本查询超时，请检查 VM 的 GitHub 连接后重试。")), 28000);
			try {
				return await Promise.race([aborted, (async () => {
					const response = await fetch("/redteam/api", { method: "POST", credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ op: "toolchainVersions", project }) });
					if (!response.ok) throw Error(response.status === 401 ? "登录已失效，请重新打开 VM 登录入口。" : "版本查询接口不可用，请重试。");
					const result = await response.json();
					if (!result.ok || !Array.isArray(result.report?.projects)) throw Error(result.error || "版本结果无法确认，请重试。");
					return result.report;
				})()]);
			} finally { clearTimeout(timer); signal?.removeEventListener("abort", cancel); controller.signal.removeEventListener("abort", rejectAbort); }
		}
		function VmToolchainStatusCard() {
			const [report, setReport] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
			const request = useRef(null), generation = useRef(0);
			useEffect(() => () => { generation.current++; request.current?.abort(); }, []);
			const check = async (project = "all") => {
				if (request.current) return;
				const current = ++generation.current, controller = new AbortController(); request.current = controller; setBusy(project); setError("");
				try { const next = await readVmToolchain(controller.signal, project); const validated = mergeVmToolchainReport(null, next, project, current); if (current === generation.current) setReport(previous => mergeVmToolchainReport(previous, validated, project, current)); }
				catch (e) { if (current === generation.current) setError(e.message || "查询未完成，请重试。"); }
				finally { if (current === generation.current) { request.current = null; setBusy(false); } }
			};
			const repositories = { rea: "morluto/rea", "reverse-skill": "zhaoxuya520/reverse-skill", pentagi: "vxcontrol/pentagi" };
			const value = item => item?.version || item?.tag || item?.revision?.slice(0, 8) || "未确认";
			return h("section", { className: "dshp-vm-toolchain", "aria-label": "工具版本" },
				h("div", { className: "dshp-vm-section-head" }, h("div", null, h("h3", null, "工具版本"), h("p", { className: "dshp-vm-help" }, "REA / reverse-skill / PentAGI · 手动查询 GitHub")), h("button", { type: "button", className: "dshp-vm-btn primary", disabled: Boolean(busy), onClick: () => check("all") }, busy ? "正在检查版本…" : "检查工具版本")),
				report ? h("div", { className: "dshp-vm-toolchain-rows" }, report.projects.map(row => h("article", { className: "dshp-vm-toolchain-row", key: row.project },
					h("div", null, h("strong", null, row.project === "rea" ? "REA" : row.project === "pentagi" ? "PentAGI" : row.project), h("span", { className: "dshp-vm-toolchain-state" }, vmToolchainLabel(row)), h("button", { type: "button", className: "dshp-vm-btn quiet", style: { marginLeft: "auto", padding: "4px 8px", fontSize: "10px" }, disabled: Boolean(busy), "aria-label": "仅重查 " + (row.project === "rea" ? "REA" : row.project === "pentagi" ? "PentAGI" : row.project), onClick: () => check(row.project) }, busy === row.project ? "正在重查…" : "重查此项")),
					h("dl", null, h("div", null, h("dt", null, "本地"), h("dd", null, value(row.installed))), h("div", null, h("dt", null, "正式 Release"), h("dd", null, row.latestRelease?.state === "no_release" ? "暂无正式版" : value(row.latestRelease))), h("div", null, h("dt", null, "默认分支"), h("dd", null, row.defaultBranch?.revision?.slice(0, 8) || "未确认"))),
					...vmToolchainIssues(row).map(message => h("p", { key: message, className: "dshp-vm-help" }, message)),
					h("p", { className: "dshp-vm-help" }, h("time", { dateTime: row.checkedAt }, "此项检查：" + new Date(row.checkedAt).toLocaleString("zh-CN"))),
					repositories[row.project] ? h("a", { href: "https://github.com/" + repositories[row.project], target: "_blank", rel: "noreferrer" }, "GitHub 来源 ↗") : null))) : h("p", { className: "dshp-vm-help" }, "点击检查后显示正式 Release 与默认分支差异；尚未查询。"),
				error ? h("p", { className: "dshp-vm-field-error", role: "alert" }, error) : null,
				h("p", { className: "dshp-vm-help", role: "status" }, busy ? "正在进行只读查询，关闭面板会取消；其他结果仍会保留。" : report ? "各项保留独立检查时间 · 不自动升级" : "只读检查 · 不自动升级"));
		}
		function VmWorkbenchManager({ onClose }) {
			const [rows, setRows] = useState([]), [path, setPath] = useState(""), [agentDir, setAgentDir] = useState("读取中…"), [error, setError] = useState(""), [busy, setBusy] = useState(false);
			const [confirmation, setConfirmation] = useState(null), [statusError, setStatusError] = useState(""), [checking, setChecking] = useState(false), [directoryBusy, setDirectoryBusy] = useState(false), [directoryList, setDirectoryList] = useState(null), [directoryError, setDirectoryError] = useState("");
			const [importing, setImporting] = useState(false), [importStage, setImportStage] = useState(""), [importOutcome, setImportOutcome] = useState(null), [terminalCheck, setTerminalCheck] = useState(null);
			const box = useRef(null), alive = useRef(true), observer = useRef(null), requests = useRef(null), pathGeneration = useRef(0), pickerGeneration = useRef(0), importRequest = useRef(null);
			const host = vmShellWorkbenchHost;
			const service = name => host?.get?.(name) ?? host?.[name];
			const refresh = () => observer.current?.refresh();
			const stopImport = () => importRequest.current?.abort();
			const closePanel = () => { stopImport(); onClose(); };
			useEffect(() => {
				alive.current = true; const previous = document.activeElement, lifetime = new AbortController(); requests.current = lifetime;
				const disposed = () => lifetime.abort(); vmShellWorkbenchLifetime?.signal.addEventListener("abort", disposed, { once: true });
				if (vmShellWorkbenchLifetime?.signal.aborted) lifetime.abort();
				box.current?.querySelector("button")?.focus();
				observer.current = observeVmTerminals(host, snapshot => { if (alive.current) { setRows(snapshot.rows); setAgentDir(snapshot.agentDir); setTerminalCheck({ at: snapshot.lastCheckedAt, failed: snapshot.checkFailed }); } }, message => { if (alive.current) setStatusError(message); }, lifetime.signal);
				return () => { alive.current = false; pathGeneration.current++; pickerGeneration.current++; lifetime.abort(); importRequest.current?.abort(); observer.current?.dispose(); vmShellWorkbenchLifetime?.signal.removeEventListener("abort", disposed); if (previous?.isConnected) previous.focus(); };
			}, []);
			const choose = async () => {
				if (directoryBusy || busy) return; const generation = ++pickerGeneration.current; setDirectoryBusy(true); setDirectoryError("");
				try { const result = await readVmDirectory(host, "/home/purge/workspace", requests.current?.signal, true); if (alive.current && generation === pickerGeneration.current) setDirectoryList(result); }
				catch (e) { if (alive.current && generation === pickerGeneration.current) setDirectoryError(e.message || "目录读取失败，请重试。"); }
				finally { if (alive.current && generation === pickerGeneration.current) setDirectoryBusy(false); }
			};
			const check = async () => {
				if (busy || checking) return; const generation = ++pathGeneration.current, captured = service("sidebarRight")?.mounted.getSnapshot(); setChecking(true); setError("");
				try {
					const result = await readVmDirectory(host, path, requests.current?.signal);
					if (!alive.current || generation !== pathGeneration.current) return;
					if (service("sidebarRight")?.mounted.getSnapshot() !== captured) throw new Error("会话已切换，请重新检查目录。");
					setConfirmation(result.path);
				} catch (e) { if (alive.current && generation === pathGeneration.current) { setError(e.message || "目录检查失败，请重试。"); box.current?.querySelector("input")?.focus(); } }
				finally { if (alive.current && generation === pathGeneration.current) setChecking(false); }
			};
			const act = async options => { if (busy) return; setBusy(true); setError(""); try { await openVmShellWorkbench(host, requests.current?.signal, options); onClose(); } catch (e) { if (alive.current) setError(e.message || "终端操作失败"); } finally { if (alive.current) { setBusy(false); refresh(); } } };
			const add = async () => {
				if (busy || !confirmation) return; const captured = service("sidebarRight")?.mounted.getSnapshot(), controller = new AbortController(); importRequest.current = controller; setBusy(true); setImporting(true); setImportStage("正在核对目录…"); setError("");
				const signal = requests.current?.signal ? AbortSignal.any([requests.current.signal, controller.signal]) : controller.signal;
				let submitted = false;
				try {
					const checked = await readVmDirectory(host, confirmation, signal);
					if (checked.path !== confirmation) throw new Error("目录已变化，请取消后重新检查。");
					if (service("sidebarRight")?.mounted.getSnapshot() !== captured) throw new Error("会话已切换，请取消后重新检查目录。");
					const result = await importVmClone(host, confirmation, () => true, signal, stage => { submitted = true; if (alive.current) setImportStage(stage); });
					if (!alive.current) return;
					if (result.rejected) { setImportOutcome(null); setConfirmation(null); setError("注册请求在参数核对时被拒绝，未执行添加；请重新检查目录后确认。"); return; }
					if (result.removed) { setImportOutcome(null); setConfirmation(null); setError("旧工作区注册已移除；未重新添加，请检查目录后再次确认。"); return; }
					if (result.uncertain) { setImportOutcome(readVmImportOutcome(host, confirmation)); setError("已停止等待；导入结果尚未确认，请核对结果，不要重复提交。"); return; }
					if (result.opened) { if (window.location.hash === "#redteam-full") window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search); __dshPurgeDrill.setUI({ open: false }); setDock({ open: false }); onClose(); }
					else if (!result.cancelled) setError("目录已添加；会话已切换，因此没有替你切换工作区。");
				} catch (e) { if (alive.current) {
					if (!submitted) { setImportOutcome(null); setConfirmation(null); setError(signal.aborted ? "目录核对已停止，尚未提交；可重新检查。" : e.message || "目录核对失败，尚未提交；请重试。"); }
					else { setImportOutcome(readVmImportOutcome(host, confirmation)); setError(signal.aborted ? "已停止等待；请核对是否已添加。" : "导入未确认，请核对结果后再操作。"); }
				} } finally { if (importRequest.current === controller) importRequest.current = null; if (alive.current) { setBusy(false); setImporting(false); setImportStage(""); } }
			};
			const available = rows.filter(row => !vmTerminalUnavailable(row) && (row.state.phase === "connected" || row.processVerified !== false)), unavailable = rows.filter(vmTerminalUnavailable), unconfirmed = rows.filter(row => !vmTerminalUnavailable(row) && row.state.phase !== "connected" && row.processVerified === false);
			const terminalCard = row => h("article", { key: row.contentId, className: "dshp-vm-terminal" + (!vmTerminalUnavailable(row) ? " is-ready" : "") },
				h("div", { className: "dshp-vm-terminal-head" }, h("strong", { className: "dshp-vm-terminal-name" }, row.state.info?.title || row.state.title || row.tabId), h("span", { className: "dshp-vm-state" }, vmTerminalLabel(row))),
				h("div", { className: "dshp-vm-meta-label" }, "启动目录"), h("code", { className: "dshp-vm-path" }, row.state.info?.cwd || "尚未记录"),
				h("div", { className: "dshp-vm-actions" }, h("button", { type: "button", className: "dshp-vm-btn", disabled: busy || vmTerminalUnavailable(row), onClick: () => act({ action: "select", tabId: row.tabId, sessionId: row.sessionId }) }, "打开此终端"), !vmTerminalUnavailable(row) && (row.state.phase === "disconnected" || (row.state.phase === "connected" && row.state.writable === false)) ? h("button", { type: "button", className: "dshp-vm-btn", disabled: busy, onClick: () => act({ action: "reconnect", tabId: row.tabId, sessionId: row.sessionId }) }, row.state.phase === "disconnected" ? "重新连接" : "接管输入") : null));
			const panel = h("div", { className: "dshp-vm-overlay", onKeyDown: e => { if (e.key === "Escape") { e.stopPropagation(); if (!busy || importing) closePanel(); } if (e.key === "Tab") { const fields = [...box.current.querySelectorAll("button:not(:disabled),input:not(:disabled),summary,a[href]")]; const index = fields.indexOf(document.activeElement); if (e.shiftKey && index <= 0) { e.preventDefault(); fields[fields.length - 1]?.focus(); } else if (!e.shiftKey && index === fields.length - 1) { e.preventDefault(); fields[0]?.focus(); } } } },
				h("div", { ref: box, role: "dialog", "aria-modal": "true", "aria-label": "终端与项目", className: "dshp-vm-panel" },
					h("header", { className: "dshp-vm-head" }, h("span", { className: "dshp-vm-mark", "aria-hidden": "true" }, ">_"), h("div", { className: "dshp-vm-title" }, h("div", { className: "dshp-vm-eyebrow" }, "VM WORKSPACE"), h("h2", null, "终端与项目")), h("button", { type: "button", className: "dshp-vm-btn quiet", disabled: busy && !importing, onClick: closePanel, "aria-label": "关闭" }, "关闭 ×")),
					h("div", { className: "dshp-vm-meta" }, h("div", { className: "dshp-vm-meta-main" }, h("div", { className: "dshp-vm-meta-label" }, "Agent 工作目录"), h("code", { className: "dshp-vm-path" }, agentDir)), h("span", { className: "dshp-vm-local" }, "VM 本地")),
					h("div", { className: "dshp-vm-grid" },
						h("section", { className: "dshp-vm-section", "aria-label": "会话终端" },
							h("div", { className: "dshp-vm-section-head" }, h("h3", null, "会话终端"), h("span", { className: "dshp-vm-count", "aria-live": "polite" }, available.length + " 可用" + (unconfirmed.length ? " · " + unconfirmed.length + " 待核对" : ""))),
							h("p", { className: "dshp-vm-help" }, "进程状态自动核对；待连接的终端可直接打开。"),
							h("div", { className: "dshp-vm-actions" }, h("button", { type: "button", className: "dshp-vm-btn primary", disabled: busy, onClick: () => act({ action: "new" }) }, "+ 新建终端"), h("button", { type: "button", className: "dshp-vm-btn quiet", disabled: busy, onClick: refresh }, "刷新列表")),
							h("div", { className: "dshp-vm-terminals" }, available.length ? available.map(terminalCard) : h("div", { className: "dshp-vm-empty" }, "当前没有可用终端。", h("br"), "点击“新建终端”开始。")),
							unavailable.length ? h("details", { className: "dshp-vm-history" }, h("summary", null, "失效或已结束记录（" + unavailable.length + "）"), h("div", { className: "dshp-vm-terminals" }, unavailable.map(terminalCard))) : null,
							unconfirmed.length ? h("div", { className: "dshp-vm-terminals", "aria-label": "状态待核对的终端" }, unconfirmed.map(terminalCard)) : null,
							terminalCheck?.at ? h("p", { className: "dshp-vm-help" }, "进程上次核对：" + new Date(terminalCheck.at).toLocaleTimeString("zh-CN") + (terminalCheck.failed ? " · 当前无法核对" : " · 核对有效期 15 秒")) : null,
							statusError ? h("p", { role: "status", className: "dshp-vm-help" }, statusError) : null,
							h("p", { className: "dshp-vm-help", style: { marginTop: 14 } }, "这里显示启动目录。执行 cd 后，以终端中的 pwd 为准；不会自动切换 Agent 工作区。")),
						h("section", { className: "dshp-vm-section", "aria-label": "导入项目" },
							h("div", { className: "dshp-vm-section-head" }, h("h3", null, "导入项目")), h("p", { className: "dshp-vm-help", id: "dshp-vm-import-help" }, "选择已克隆的 VM 目录，检查通过后再确认导入。"),
							h("button", { type: "button", className: "dshp-vm-btn", disabled: busy || checking || directoryBusy || confirmation !== null, onClick: choose }, directoryBusy ? "正在读取目录…" : "选择 VM 目录"),
							directoryList ? h("div", { className: "dshp-vm-directory-list", "aria-label": "工作区中的目录" }, directoryList.entries.length ? directoryList.entries.map(entry => h("button", { key: entry.path, type: "button", className: "dshp-vm-dir-choice", disabled: busy || checking || confirmation !== null, onClick: () => { pathGeneration.current++; setPath(entry.path); setConfirmation(null); setError(""); setDirectoryList(null); box.current?.querySelector("input")?.focus(); } }, entry.name)) : h("p", { className: "dshp-vm-help" }, "暂未发现目录，请先在 Shell 中完成 clone。"), directoryList.truncated ? h("p", { className: "dshp-vm-help" }, "仅显示前 100 个目录，也可填写完整 VM 路径。") : null) : null,
							directoryError ? h("p", { role: "alert", className: "dshp-vm-field-error" }, directoryError) : null,
							h("label", { className: "dshp-vm-label", style: { marginTop: 14 }, htmlFor: "dshp-vm-project-path" }, "已克隆目录的 VM 路径"),
							h("input", { id: "dshp-vm-project-path", name: "vm-project-path", autoComplete: "off", spellCheck: false, className: "dshp-vm-input", "aria-describedby": "dshp-vm-import-help dshp-vm-path-error", "aria-invalid": Boolean(error), value: path, onChange: e => { pathGeneration.current++; setPath(e.target.value); setConfirmation(null); setChecking(false); setError(""); }, disabled: busy || confirmation !== null, placeholder: "/home/purge/workspace/项目目录" }),
							h("p", { id: "dshp-vm-path-error", role: "alert", className: "dshp-vm-field-error" }, error),
							h("button", { type: "button", className: "dshp-vm-btn primary dshp-vm-import-btn", disabled: busy || checking || confirmation !== null, onClick: check }, checking ? "正在检查目录…" : "检查并导入目录 →"),
							confirmation !== null ? h("div", { role: "group", "aria-label": "确认导入目录", className: "dshp-vm-confirm" }, h("h4", null, "确认项目目录"), h("code", { className: "dshp-vm-path" }, confirmation), h("p", { className: "dshp-vm-help" }, "旧会话、草稿和终端会保留。不会自动执行仓库代码。"), h("div", { className: "dshp-vm-actions" }, h("button", { type: "button", className: "dshp-vm-btn primary", disabled: busy || Boolean(importOutcome?.path === confirmation && (importOutcome.state === "unconfirmed" || importOutcome.pending || importOutcome.state === "registered" && !importOutcome.confirmed)), onClick: add }, busy ? "处理中…" : importOutcome?.path === confirmation && importOutcome.state === "removed" ? "重新检查已移除工作区" : importOutcome?.path === confirmation && importOutcome.state === "registered" ? "打开已添加工作区" : "确认导入并打开"), h("button", { type: "button", className: "dshp-vm-btn", disabled: busy, onClick: () => { pathGeneration.current++; setConfirmation(null); setError(""); } }, "取消导入"))) : null)),
					importing ? h("div", { role: "status", className: "dshp-vm-confirm" }, h("p", null, importStage + " · 目录核对最多 10 秒，添加/打开最多 15 秒；停止等待不会撤销已发送的操作。"), h("button", { type: "button", className: "dshp-vm-btn", onClick: stopImport }, "停止等待")) : null,
					importOutcome ? h("div", { className: "dshp-vm-confirm", role: "status" }, h("p", null, importOutcome.path), h("p", null, importOutcome.state === "removed" ? "当前列表中已移除该注册；重新检查后再明确确认添加。" : importOutcome.state === "registered" ? (importOutcome.confirmed ? "当前列表已确认存在。" : "已收到添加回执，当前列表尚未确认。") + (importOutcome.pending ? "原操作仍在收尾，请稍后核对。" : "请核对当前列表后明确打开。") : "添加结果尚未确认；不自动重试。"), h("button", { type: "button", className: "dshp-vm-btn", disabled: busy, onClick: () => setImportOutcome(readVmImportOutcome(host, importOutcome.path)) }, "核对导入结果")) : null,
					h(VmToolchainStatusCard, null),
					h("footer", { className: "dshp-vm-footer" }, h("span", null, "目录与终端均位于隔离虚拟机"), h("span", null, "Esc 关闭"))));
			return require("react-dom").createPortal(panel, document.body);
		}
		function ShellWorkbenchButton(props = {}) {
			const [error, setError] = useState("");
			const [opening, setOpening] = useState(false);
			const [manager, setManager] = useState(false);
			if (window.location.origin !== "http://127.0.0.1:49226") return null;
			return h("span", { className: "dshp-vm-launch" },
				h("button", {
					type: "button", className: props.className || "dshp-hero-chip-btn", "aria-label": "Shell 工作台", disabled: opening,
					title: "在当前 VM 会话的目录中打开终端，可运行 cd、git clone 等命令",
					onClick: async () => { if (opening) return; setError(""); setOpening(true); try { await openVmShellWorkbench(vmShellWorkbenchHost, vmShellWorkbenchLifetime?.signal); } catch (e) { setError(e.message || "终端打开失败"); } finally { setOpening(false); } },
				}, opening ? "正在打开…" : ">_ Shell 工作台"),
				h("button", { type: "button", className: props.className || "dshp-hero-chip-btn", onClick: () => setManager(true) }, "终端与项目"),
				manager ? h(VmWorkbenchManager, { onClose: () => setManager(false) }) : null,
				error ? h("span", { role: "alert", style: { color: "var(--dsw-alias-label-error, #a32222)", fontSize: 12 } }, error) : null);
		}

		function requestDrill(kind) {
			const pending = kind || "tab";
			const openEnv = () => {
				try {
					if (__dshPurgeDrill && __dshPurgeDrill.setUI) {
						__dshPurgeDrill.setUI({ open: true, tab: "env" });
					}
				} catch { /* ignore */ }
			};
			if (readDrillAuth()) {
				setDock({ open: true, tab: "drill", authOpen: false, pending: "tab" });
				try { if (__dshPurgeDrill && __dshPurgeDrill.setUI) __dshPurgeDrill.setUI({ open: true }); } catch { /* ignore */ }
				if (pending === "env") openEnv();
				if (pending === "full") {
					try { window.open(window.location.href.split("#")[0] + "#redteam-full", "_blank", "noopener"); } catch { /* ignore */ }
				}
				return;
			}
			/* 未授权：直接切到演练台页签并弹出授权窗（不再停在清洗页，避免像「没触发」） */
			setDock({ open: true, tab: "drill", authOpen: true, pending: pending });
		}

		function requestDrillEnv() {
			requestDrill("env");
		}

		function openDockClean() {
			setDock({ open: true, tab: "clean", authOpen: false, pending: "tab" });
		}
		function toggleDock() {
			if (dockBus.open) setDock({ open: false, authOpen: false, pending: "tab" });
			else openDockClean();
		}
		syncDrillGrant();

		const DOCK_GEOM_KEY = "dsh-purge-dock-geom-v4";
		/* 默认停在右上，底边留在输入框上面。拖动之后停在用户松开的位置，只保证不拖出窗口。 */
		const DOCK_COMPOSER_CLEAR = 172;
		function defaultDockGeom() {
			const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
			const vh = typeof window !== "undefined" ? window.innerHeight : 800;
			const w = Math.min(620, Math.max(380, vw - 16));
			const y = 48;
			const h = Math.max(240, Math.min(640, vh - y - DOCK_COMPOSER_CLEAR));
			return { x: Math.max(8, vw - w - 8), y: y, w: w, h: h };
		}
		function clampDockGeom(g) {
			const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
			const vh = typeof window !== "undefined" ? window.innerHeight : 800;
			const w = Math.min(Math.max(380, Number(g && g.w) || 620), Math.max(380, vw - 16));
			const h = Math.min(Math.max(240, Number(g && g.h) || 520), Math.max(240, vh - 16));
			const x = Math.min(Math.max(8, Number(g && g.x) || 8), Math.max(8, vw - w - 8));
			const y = Math.min(Math.max(8, Number(g && g.y) || 8), Math.max(8, vh - Math.min(h, vh - 16) - 8));
			return { x: x, y: y, w: w, h: h };
		}
		function loadDockGeom() {
			try {
				const raw = JSON.parse(window.localStorage.getItem(DOCK_GEOM_KEY) || "null");
				if (raw && typeof raw === "object") return clampDockGeom(raw);
			} catch { /* ignore */ }
			return clampDockGeom(defaultDockGeom());
		}
		function saveDockGeom(g) {
			try { window.localStorage.setItem(DOCK_GEOM_KEY, JSON.stringify(clampDockGeom(g))); } catch { /* ignore */ }
		}

		function WelcomeNotice() {
			const t = useT();
			const [open, setOpen] = useState(() => !readWelcomeAck());
			const [checked, setChecked] = useState(false);
			if (!open) return null;
			const repo = t("welcome.repo");
			const node = h("div", { className: "dshp-auth-mask", role: "dialog", "aria-modal": "true" },
				h("div", { className: "dshp-auth-modal", style: { width: "min(560px,100%)" } },
					h("h2", null, t("welcome.title")),
					h("div", { className: "muted", style: { color: "var(--dsw-alias-label-secondary,#999)", fontSize: 12 } }, t("welcome.lead")),
					h("div", { className: "dshp-auth-warn" }, t("welcome.warn")),
					h("div", { className: "dshp-auth-legal", style: { height: "auto", maxHeight: 280 } },
						h("p", null, t("welcome.body")),
						h("p", null,
							h("a", {
								href: repo,
								target: "_blank",
								rel: "noopener noreferrer",
								style: { color: "var(--dsw-alias-label-brand, #8fbf9a)", wordBreak: "break-all" },
							}, repo),
						),
						h("h3", null, t("welcome.bans")),
						h("p", null, t("welcome.ban1")),
						h("p", null, t("welcome.ban2")),
						h("p", null, t("welcome.ban3")),
					),
					h("div", { className: "dshp-auth-checks" },
						h("label", null,
							h("input", {
								type: "checkbox",
								checked: checked,
								onChange: (e) => setChecked(!!(e && e.target && e.target.checked)),
							}),
							h("span", null, t("welcome.check")),
						),
					),
					h("div", { className: "dshp-auth-ops" },
						h("button", {
							type: "button",
							className: "primary",
							disabled: !checked,
							onClick: () => {
								if (!checked) return;
								writeWelcomeAck();
								setOpen(false);
							},
						}, t("welcome.ok")),
					),
				),
			);
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function" && typeof document !== "undefined" && document.body) {
					return rd.createPortal(node, document.body);
				}
			} catch { /* ignore */ }
			return node;
		}

		function AuthGate(props) {
			const t = useT();
			const [left, setLeft] = useState(10);
			const [readEnd, setReadEnd] = useState(false);
			const [checks, setChecks] = useState({ read: false, scope: false, ban: false });
			const legalRef = useRef(null);
			useEffect(() => {
				const id = window.setInterval(() => {
					setLeft((n) => {
						if (n <= 1) { window.clearInterval(id); return 0; }
						return n - 1;
					});
				}, 1000);
				return () => window.clearInterval(id);
			}, []);
			useEffect(() => {
				const el = legalRef.current;
				if (!el) return;
				if (el.scrollHeight <= el.clientHeight + 4) setReadEnd(true);
			}, []);
			const locked = left > 0 || !readEnd;
			const ready = !locked && checks.read && checks.scope && checks.ban;
			const hint = left > 0
				? t("auth.hint.wait").replace("{n}", String(left))
				: (readEnd ? t("auth.hint.check") : t("auth.hint.scroll"));
			const onScroll = () => {
				const el = legalRef.current;
				if (!el) return;
				if (el.scrollTop + el.clientHeight >= el.scrollHeight - 8) setReadEnd(true);
			};
			const toggle = (id) => {
				if (locked) return;
				setChecks((prev) => Object.assign({}, prev, { [id]: !prev[id] }));
			};
			const okLabel = !ready
				? t("auth.ok")
				: (props.pending === "full"
					? t("auth.ok.full")
					: (props.pending === "env" ? t("auth.ok.env") : t("auth.ok.tab")));
			return h("div", { className: "dshp-auth-mask", role: "dialog", "aria-modal": "true" },
				h("div", { className: "dshp-auth-modal" },
					h("h2", null, t("auth.title")),
					h("div", { className: "muted", style: { color: "var(--dsw-alias-label-secondary,#999)", fontSize: 12 } }, t("auth.lead")),
					h("div", { className: "dshp-auth-warn" }, t("auth.warn")),
					h("div", {
						className: "dshp-auth-legal",
						ref: legalRef,
						onScroll,
						dangerouslySetInnerHTML: { __html: AUTH_LEGAL_HTML },
					}),
					h("div", { style: { color: "var(--dsw-alias-label-secondary,#999)", fontSize: 12 } }, hint),
					h("div", { className: "dshp-auth-checks" },
						[["read", "auth.check.read"], ["scope", "auth.check.scope"], ["ban", "auth.check.ban"]].map((row) =>
							h("label", { key: row[0], className: locked ? "locked" : "" },
								h("input", {
									type: "checkbox",
									checked: !!checks[row[0]],
									disabled: locked,
									onChange: () => toggle(row[0]),
								}),
								h("span", null, t(row[1])),
							),
						),
					),
					h("div", { className: "dshp-auth-ops" },
						h("button", { type: "button", onClick: () => setDock({ authOpen: false, tab: "clean", pending: "tab" }) }, t("auth.no")),
						h("button", {
							type: "button",
							className: "primary",
							disabled: !ready,
							onClick: () => {
								if (!ready) return;
								writeDrillAuth(true);
								const kind = props.pending || "tab";
								setDock({ authOpen: false, open: true, tab: "drill", pending: "tab" });
								try { if (__dshPurgeDrill && __dshPurgeDrill.setUI) __dshPurgeDrill.setUI({ open: true }); } catch { /* ignore */ }
								if (kind === "env") {
									try { if (__dshPurgeDrill && __dshPurgeDrill.setUI) __dshPurgeDrill.setUI({ open: true, tab: "env" }); } catch { /* ignore */ }
								}
								if (kind === "full") {
									try { window.open(window.location.href.split("#")[0] + "#redteam-full", "_blank", "noopener"); } catch { /* ignore */ }
								}
							},
						}, okLabel),
					),
				),
			);
		}

		function isRedteamPresetId(value) {
			const text = String(value || "").trim();
			if (!text) return false;
			if (text === "redteam") return true;
			if (/^red[\s_-]*team$/i.test(text)) return true;
			const label = text.replace(/不是红队/g, "").replace(/非红队/g, "");
			if (/红队/.test(label)) return true;
			return false;
		}

		function readSessionAgentPreset(sess) {
			if (!sess || typeof sess !== "object") return "";
			try {
				const pv = sess.projectionValues;
				if (pv && typeof pv.agentPreset === "string") return pv.agentPreset;
			} catch { /* ignore */ }
			try {
				if (typeof sess.agentPreset === "string") return sess.agentPreset;
			} catch { /* ignore */ }
			try {
				const header = sess.header;
				if (header && typeof header.agentPreset === "string") return header.agentPreset;
			} catch { /* ignore */ }
			return "";
		}

		function readSessionCwd(sess) {
			if (!sess || typeof sess !== "object") return "";
			try {
				const pv = sess.projectionValues;
				if (pv && typeof pv.cwd === "string" && pv.cwd.trim()) return pv.cwd.trim();
			} catch { /* ignore */ }
			try {
				if (typeof sess.cwd === "string" && sess.cwd.trim()) return sess.cwd.trim();
			} catch { /* ignore */ }
			try {
				const header = sess.header;
				if (header && typeof header.cwd === "string" && header.cwd.trim()) return header.cwd.trim();
			} catch { /* ignore */ }
			return "";
		}

		function clientCurrentCwd() {
			try {
				const sessions = rewindSessions || (rewindHost && rewindHost.sessions);
				if (!sessions) return "";
				const sid = currentSessionId(sessions);
				if (!sid) return "";
				try {
					const snap = typeof sessions.list?.getSnapshot === "function" ? sessions.list.getSnapshot() : null;
					const sess = snap && snap.byId ? snap.byId[sid] : null;
					const found = readSessionCwd(sess);
					if (found) return found;
				} catch { /* ignore */ }
				try {
					const actx = typeof sessions.scope === "function" ? sessions.scope(sid) : undefined;
					const face = typeof sessions.sessionOf === "function" ? sessions.sessionOf(actx) : undefined;
					const faceSnap = face && typeof face.getSnapshot === "function" ? face.getSnapshot() : face;
					const found = readSessionCwd(faceSnap);
					if (found) return found;
				} catch { /* ignore */ }
			} catch { /* ignore */ }
			return "";
		}

		function isRedteamModeActive() {
			try {
				const sessions = rewindSessions || (rewindHost && rewindHost.sessions);
				const sid = currentSessionId(sessions);
				if (sid && sessions) {
					try {
						const snap = typeof sessions.list?.getSnapshot === "function" ? sessions.list.getSnapshot() : null;
						const sess = snap && snap.byId ? snap.byId[sid] : null;
						if (isRedteamPresetId(readSessionAgentPreset(sess))) return true;
					} catch { /* ignore */ }
					try {
						const actx = typeof sessions.scope === "function" ? sessions.scope(sid) : undefined;
						const face = typeof sessions.sessionOf === "function" ? sessions.sessionOf(actx) : undefined;
						const faceSnap = face && typeof face.getSnapshot === "function" ? face.getSnapshot() : face;
						if (isRedteamPresetId(readSessionAgentPreset(faceSnap))) return true;
					} catch { /* ignore */ }
				}
			} catch { /* ignore */ }
			/* 新会话：模式下拉里的「红队模式」chip（选好但还没写入 session）
			 * 优先走语义化 data-* 挂点,其次 class 子串模糊匹配 + 文本兜底;
			 * 不写死 CSS Module 哈希(HKgFRW_seat 这种每次构建都会变)。 */
			try {
				const semantic = document.querySelector(
					"[data-agent-preset='redteam'], [data-preset-id='redteam'], [data-mode='redteam']"
				);
				if (semantic) return true;
				const nodes = document.querySelectorAll(
					"[class*='seat' i][class*='label' i], [class*='seatLabel' i], button[class*='seat' i], [role='button'][class*='seat' i]"
				);
				for (const el of nodes) {
					const text = String(el.textContent || "").replace(/\s+/g, " ").trim();
					if (/红队模式/.test(text) || /^RedTeam\b/i.test(text)) return true;
				}
			} catch { /* ignore */ }
			try {
				/* Match the mode label in either language; the Chinese title is rebuilt from
				 * code points so this file does not hardcode CJK literals. */
				const zhRedTeamLabel = String.fromCharCode(0x7ea2, 0x961f);
				const labels = document.querySelectorAll(
					"[class*='label' i][class*='preset' i], [class*='presetLabel' i], [title*='" + zhRedTeamLabel + "'], [title*='Red team' i], [title*='RedTeam' i]"
				);
				for (const el of labels) {
					const text = String(el.textContent || "").trim();
					if (/红队模式/.test(text) || /^RedTeam\b/i.test(text)) return true;
					if (isRedteamPresetId(text)) return true;
				}
			} catch { /* ignore */ }
			return false;
		}

		function looksLikeSendControl(el) {
			if (!el || el.nodeType !== 1) return false;
			const btn = el.closest("button, [role='button']");
			if (!btn) return false;
			if (btn.closest(".dshp-dock, .dshp-auth-mask, .rt-dock, .dshp-env-gate")) return false;
			const label = [
				btn.getAttribute("aria-label"),
				btn.getAttribute("title"),
				btn.getAttribute("data-testid"),
				btn.textContent,
			].filter(Boolean).join(" ");
			if (/停止|Stop/i.test(label) && !/发送|Send/i.test(label)) return false;
			if (/发送|Submit|Send(?!\s*feedback)/i.test(label)) return true;
			/* composer 主按钮：data-composer-card 内的 primary */
			try {
				const card = btn.closest("[data-composer-card], [data-composer-seat]");
				if (card) {
					const cls = String(btn.className || "");
					if (/primary/i.test(cls) && btn.querySelector("svg")) return true;
				}
			} catch { /* ignore */ }
			if (btn.type === "submit") {
				const form = btn.closest("form");
				if (form && form.querySelector("textarea, [contenteditable='true']")) return true;
			}
			return false;
		}

		function fetchEnvAdaptStatus() {
			return fetch("/redteam/api", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ op: "platformEnvAdaptStatus" }),
			}).then((r) => r.json()).catch(() => null);
		}

		/** 同步探测的占位：不再做同步 XHR（会卡 UI 主线程、Chrome 已逐步弃用）。
		 * 调用方 mustBlockSubmit 在 cache 过期/缺失时按"未知→保守 block"处理,
		 * 同时 EnvAdaptSendGate 的 useEffect 轮询会异步 refresh,下次调用即可放行。 */
		function fetchEnvAdaptStatusSync() { return null; }

		/** 红队发送前门禁：未就绪 → 授权并打开环境适配；可确认跳过。 */
		function EnvAdaptSendGate() {
			const t = useT();
			const [open, setOpen] = useState(false);
			const [confirmSkip, setConfirmSkip] = useState(false);
			const [status, setStatus] = useState(null);
			const [busy, setBusy] = useState(false);
			const cacheRef = useRef({ at: 0, ready: false });
			const openRef = useRef(false);
			openRef.current = open;

			const refresh = useCallback(async () => {
				const r = await fetchEnvAdaptStatus();
				const ready = !!(r && r.ready);
				cacheRef.current = { at: Date.now(), ready: ready, skipped: !!(r && r.skipped) };
				setStatus(r);
				return r;
			}, []);

			const blockAndOpen = useCallback(() => {
				setConfirmSkip(false);
				refresh();
				/* 第一次：只走完整授权窗 → 授权后进环境适配页 */
				if (!readDrillAuth()) {
					setOpen(false);
					requestDrillEnv();
					return true;
				}
				/* 已授权过：只弹精简环境适配窗，不再自动拉开整块演练台 */
				setOpen(true);
				return true;
			}, [refresh]);

			const mustBlockSubmit = useCallback(() => {
				if (!isRedteamModeActive()) return false;
				const cached = cacheRef.current;
				/* cache 过期时触发异步刷新;本次调用按最后一次 cache 判断,未知保守 block */
				if (!cached.at || Date.now() - cached.at > 2500) {
					refresh().catch(() => {});
				}
				if (cached.ready) return false;
				blockAndOpen();
				return true;
			}, [blockAndOpen, refresh]);

			/* 挂住宿主 SessionInputShell.submit —— 比点按钮启发式可靠。
			 * patch 必须可逆:存 origSubmit 到 WeakMap,unmount / 依赖变更时恢复,
			 * 否则插件禁用后 shell.submit 还是我们的 wrapper,持死 mustBlockSubmit 闭包。 */
			useEffect(() => {
				const patched = new WeakMap();
				const patchedShells = [];
				const patchShell = (shell) => {
					if (!shell || patched.has(shell)) return;
					if (typeof shell.submit !== "function") return;
					const origSubmit = shell.submit;
					patched.set(shell, { origSubmit });
					patchedShells.push(shell);
					const bound = origSubmit.bind(shell);
					shell.submit = function gatedSubmit(mode) {
						try {
							if (mustBlockSubmit()) return;
						} catch { /* 门禁异常时不吞掉发送 */ }
						return bound(mode);
					};
				};
				const tick = () => {
					try {
						const sessions = rewindSessions || (rewindHost && rewindHost.sessions);
						const sid = currentSessionId(sessions);
						if (!sid) return;
						patchShell(conversationInput(sid));
					} catch { /* ignore */ }
				};
				tick();
				const iv = window.setInterval(tick, 400);
				return () => {
					window.clearInterval(iv);
					for (const shell of patchedShells) {
						const info = patched.get(shell);
						if (!info) continue;
						try { shell.submit = info.origSubmit; } catch { /* ignore */ }
					}
					patchedShells.length = 0;
				};
			}, [mustBlockSubmit]);

			useEffect(() => {
				let alive = true;
				const tick = () => {
					if (!alive) return;
					if (!isRedteamModeActive()) return;
					refresh();
				};
				tick();
				const iv = window.setInterval(tick, 5000);
				return () => { alive = false; window.clearInterval(iv); };
			}, [refresh]);

			useEffect(() => {
				const onPointer = (e) => {
					if (!looksLikeSendControl(e.target)) return;
					if (!mustBlockSubmit()) return;
					e.preventDefault();
					e.stopPropagation();
					if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
				};
				const onKey = (e) => {
					if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
					const inComposer = e.target && e.target.closest
						&& e.target.closest("[data-composer-card], [data-composer-seat], [contenteditable='true'], textarea");
					if (!inComposer) return;
					if (e.target.closest && e.target.closest(".dshp-dock, .dshp-auth-mask, .rt-dock, .dshp-env-gate")) return;
					if (!mustBlockSubmit()) return;
					e.preventDefault();
					e.stopPropagation();
					if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
				};
				document.addEventListener("pointerdown", onPointer, true);
				document.addEventListener("click", onPointer, true);
				document.addEventListener("keydown", onKey, true);
				return () => {
					document.removeEventListener("pointerdown", onPointer, true);
					document.removeEventListener("click", onPointer, true);
					document.removeEventListener("keydown", onKey, true);
				};
			}, [mustBlockSubmit]);

			if (!open) return null;

			const message = (status && status.message) || t("envGate.lead");
			return h("div", { className: "dshp-auth-mask dshp-env-gate", role: "dialog", "aria-modal": "true" },
				h("div", { className: "dshp-auth-modal", style: { width: "min(480px,100%)" } },
					h("h2", null, t("envGate.title")),
					h("div", { style: { fontSize: 13, lineHeight: 1.55 } }, message),
					h("div", { style: { fontSize: 12, color: "var(--dsw-alias-label-secondary,#999)", lineHeight: 1.5 } }, t("envGate.kaliHint")),
					confirmSkip
						? h("div", { className: "dshp-auth-warn" }, t("envGate.skipConfirm"))
						: null,
					h("div", { className: "dshp-auth-ops" },
						confirmSkip
							? [
								h("button", {
									key: "no",
									type: "button",
									onClick: () => setConfirmSkip(false),
								}, t("envGate.skipNo")),
								h("button", {
									key: "yes",
									type: "button",
									className: "primary",
									disabled: busy,
									onClick: () => {
										setBusy(true);
										fetch("/redteam/api", {
											method: "POST",
											headers: { "content-type": "application/json" },
											body: JSON.stringify({ op: "platformEnvAdaptSkip", skip: true }),
										}).then((r) => r.json()).then((r) => {
											setBusy(false);
											cacheRef.current = { at: Date.now(), ready: true, skipped: true };
											setStatus(r);
											setOpen(false);
											setConfirmSkip(false);
										}).catch(() => {
											setBusy(false);
											cacheRef.current = { at: Date.now(), ready: true, skipped: true };
											setOpen(false);
										});
									},
								}, t("envGate.skipYes")),
							]
							: [
								h("button", {
									key: "skip",
									type: "button",
									onClick: () => setConfirmSkip(true),
								}, t("envGate.skip")),
								h("button", {
									key: "go",
									type: "button",
									className: "primary",
									onClick: () => {
										setOpen(false);
										requestDrillEnv();
									},
								}, t("envGate.go")),
							],
					),
				),
			);
		}

		function PurgeDock() {
			const t = useT();
			const st = useDock();
			const [geom, setGeom] = useState(() => loadDockGeom());
			const [dockTheme, setDockTheme] = useState(detectHostTheme);
			useEffect(() => {
				const sync = () => setDockTheme(detectHostTheme());
				sync();
				const obs = new MutationObserver(sync);
				if (document.body) obs.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class", "style"] });
				obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class", "style"] });
				const timer = window.setInterval(sync, 1500);
				return () => { obs.disconnect(); window.clearInterval(timer); };
			}, []);
			useEffect(() => {
				let uiTag = document.querySelector('style[data-dsh-purge-ui="1"]');
				if (!uiTag) {
					uiTag = document.createElement("style");
					uiTag.setAttribute("data-dsh-purge-ui", "1");
					uiTag.textContent = PURGE_CSS;
					document.head.append(uiTag);
				}
				if (!__dshPurgeDrill || !__dshPurgeDrill.CSS) return undefined;
				const styleTag = document.createElement("style");
				styleTag.setAttribute("data-dsh-purge-drill", "1");
				styleTag.textContent = __dshPurgeDrill.CSS;
				document.head.append(styleTag);
				const widthTag = document.createElement("style");
				widthTag.setAttribute("data-dsh-purge-dock-w", "1");
				widthTag.textContent = ":root{--dshp-dock-w:" + geom.w + "px;--dshp-dock-h:" + geom.h + "px}";
				document.head.append(widthTag);
				return () => { styleTag.remove(); widthTag.remove(); };
			}, []);
			useEffect(() => {
				saveDockGeom(geom);
				const tag = document.querySelector('style[data-dsh-purge-dock-w="1"]');
				if (tag) tag.textContent = ":root{--dshp-dock-w:" + geom.w + "px;--dshp-dock-h:" + geom.h + "px}";
			}, [geom]);
			useEffect(() => {
				const onResize = () => setGeom((g) => clampDockGeom(g));
				window.addEventListener("resize", onResize);
				return () => window.removeEventListener("resize", onResize);
			}, []);
			useEffect(() => {
				if (st.tab === "drill" && readDrillAuth() && __dshPurgeDrill && __dshPurgeDrill.setUI) {
					try { __dshPurgeDrill.setUI({ open: true }); } catch { /* ignore */ }
				}
			}, [st.tab, st.open]);
			const onTab = (id) => {
				if (id === "drill") { requestDrill("tab"); return; }
				setDock({ tab: "clean", authOpen: false, pending: "tab" });
			};
			const startDrag = (e) => {
				if (e.button !== 0) return;
				if (e.target && e.target.closest && e.target.closest("button,a,input,select,textarea,label")) return;
				e.preventDefault();
				const sx = e.clientX;
				const sy = e.clientY;
				const ox = geom.x;
				const oy = geom.y;
				const move = (ev) => setGeom((g) => clampDockGeom({ x: ox + (ev.clientX - sx), y: oy + (ev.clientY - sy), w: g.w, h: g.h }));
				const up = () => {
					window.removeEventListener("mousemove", move);
					window.removeEventListener("mouseup", up);
				};
				window.addEventListener("mousemove", move);
				window.addEventListener("mouseup", up);
			};
			const startResize = (e) => {
				if (e.button !== 0) return;
				e.preventDefault();
				e.stopPropagation();
				const sx = e.clientX;
				const sy = e.clientY;
				const ow = geom.w;
				const oh = geom.h;
				const move = (ev) => setGeom((g) => clampDockGeom({ x: g.x, y: g.y, w: ow + (ev.clientX - sx), h: oh + (ev.clientY - sy) }));
				const up = () => {
					window.removeEventListener("mousemove", move);
					window.removeEventListener("mouseup", up);
				};
				window.addEventListener("mousemove", move);
				window.addEventListener("mouseup", up);
			};
			const startResizeLeft = (e) => {
				if (e.button !== 0) return;
				e.preventDefault();
				e.stopPropagation();
				const sx = e.clientX;
				const ox = geom.x;
				const ow = geom.w;
				const move = (ev) => {
					const dx = ev.clientX - sx;
					setGeom((g) => clampDockGeom({ x: ox + dx, y: g.y, w: ow - dx, h: g.h }));
				};
				const up = () => {
					window.removeEventListener("mousemove", move);
					window.removeEventListener("mouseup", up);
				};
				window.addEventListener("mousemove", move);
				window.addEventListener("mouseup", up);
			};
			const startResizeRight = (e) => {
				if (e.button !== 0) return;
				e.preventDefault();
				e.stopPropagation();
				const sx = e.clientX;
				const ow = geom.w;
				const move = (ev) => setGeom((g) => clampDockGeom({ x: g.x, y: g.y, w: ow + (ev.clientX - sx), h: g.h }));
				const up = () => {
					window.removeEventListener("mousemove", move);
					window.removeEventListener("mouseup", up);
				};
				window.addEventListener("mousemove", move);
				window.addEventListener("mouseup", up);
			};
			const startResizeBottom = (e) => {
				if (e.button !== 0) return;
				e.preventDefault();
				e.stopPropagation();
				const sy = e.clientY;
				const oh = geom.h;
				const move = (ev) => setGeom((g) => clampDockGeom({ x: g.x, y: g.y, w: g.w, h: oh + (ev.clientY - sy) }));
				const up = () => {
					window.removeEventListener("mousemove", move);
					window.removeEventListener("mouseup", up);
				};
				window.addEventListener("mousemove", move);
				window.addEventListener("mouseup", up);
			};
			const body = st.tab === "clean"
				? h(SettingsRoot, { t })
				: (readDrillAuth() && __dshPurgeDrill.Panel
					? h(__dshPurgeDrill.Panel, { embedded: true, getSessionId: drillSessionId, shellWorkbench: h(ShellWorkbenchButton, { className: "rt-btn" }) })
					: h("div", { style: { padding: 16, color: "var(--dsw-alias-label-secondary)" } }, t("dock.unauthorized")));
			const panel = __dshPurgeDrill.isFullWindow() && readDrillAuth()
				? h(__dshPurgeDrill.Panel, { embedded: false, getSessionId: drillSessionId, shellWorkbench: h(ShellWorkbenchButton, { className: "rt-btn" }) })
				: h("div", {
				className: "dshp-dock",
				"data-theme": dockTheme === "white" ? "white" : "dusk",
				"data-open": st.open ? "1" : "0",
				style: {
					left: geom.x + "px",
					top: geom.y + "px",
					right: "auto",
					bottom: "auto",
					width: geom.w + "px",
					height: geom.h + "px",
				},
			},
				h("div", { className: "dshp-dock-head", onMouseDown: startDrag, title: "Drag to move the panel" },
					h("b", null, "dsh-purge"),
					h("span", { style: { flex: 1 } }),
					st.tab === "drill" && readDrillAuth()
						? h("button", { type: "button", onClick: () => requestDrill("full") }, t("dock.full"))
						: null,
					h("button", { type: "button", onClick: () => setDock({ open: false, authOpen: false, tab: "clean", pending: "tab" }) }, t("dock.close")),
				),
				h("div", { className: "dshp-dock-tabs", role: "tablist" },
					h("button", {
						type: "button",
						className: "dshp-dock-tab" + (st.tab === "clean" ? " on" : ""),
						role: "tab",
						"aria-selected": st.tab === "clean" ? "true" : "false",
						onClick: () => onTab("clean"),
					}, t("dock.clean")),
					h("button", {
						type: "button",
						className: "dshp-dock-tab" + (st.tab === "drill" ? " on" : ""),
						role: "tab",
						"aria-selected": st.tab === "drill" ? "true" : "false",
						onClick: () => onTab("drill"),
					}, t("dock.drill") + (readDrillAuth() ? "" : " · " + t("dock.unauthorized"))),
				),
				h("div", { className: "dshp-dock-body" }, body),
				h("div", { className: "dshp-dock-resize-l", title: "Drag to resize width", onMouseDown: startResizeLeft }),
				h("div", { className: "dshp-dock-resize-r", title: "Drag to resize width", onMouseDown: startResizeRight }),
				h("div", { className: "dshp-dock-resize-b", title: "Drag to resize height", onMouseDown: startResizeBottom }),
				h("div", { className: "dshp-dock-resize", title: "Drag to resize", onMouseDown: startResize }),
			);
			let portal = null;
			let authPortal = null;
			const authNode = st.authOpen ? h(AuthGate, { pending: st.pending }) : null;
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function" && typeof document !== "undefined" && document.body) {
					portal = rd.createPortal(panel, document.body);
					if (authNode) authPortal = rd.createPortal(authNode, document.body);
				}
			} catch { /* host 可能没暴露 react-dom */ }
			return h(react.Fragment, null,
				portal || panel,
				authPortal || authNode,
			);
		}

		function hasInlinePurgeEntry() {
			if (typeof document === "undefined") return false;
			if (document.querySelector("[data-testid='dsh-purge-hero-chip'], [data-testid='dsh-purge-tab-chip']")) return true;
			const nodes = document.querySelectorAll("button, [role='tab'], [role='button'], [class*='chip']");
			for (let i = 0; i < nodes.length; i += 1) {
				const el = nodes[i];
				if (!el || el.classList.contains("dshp-launch")) continue;
				if (el.closest && el.closest(".dshp-dock, .dshp-launch")) continue;
				if (String(el.textContent || "").trim() === "dsh-purge") return true;
			}
			return false;
		}

		function PurgeLauncher() {
			const t = useT();
			const st = useDock();
			const [hide, setHide] = useState(hasInlinePurgeEntry);
			useEffect(() => {
				const sync = () => setHide(hasInlinePurgeEntry());
				sync();
				const obs = typeof MutationObserver !== "undefined"
					? new MutationObserver(sync)
					: null;
				if (obs && document.body) obs.observe(document.body, { childList: true, subtree: true });
				const iv = setInterval(sync, 800);
				return () => {
					if (obs) obs.disconnect();
					clearInterval(iv);
				};
			}, []);
			if (st.open || hide) return null;
			return h("button", {
				type: "button",
				className: "dshp-launch",
				"data-open": "0",
				"data-hide": "0",
				"data-testid": "dsh-purge-launch",
				title: t("dock.newSession"),
				onClick: () => toggleDock(),
			}, t("dock.newSession"));
		}

		/** 首页：模式旁挂「dsh-purge」→ 打开插件。红队模式走模式下拉（registry 声明）。 */
		function HeroNewSessionMount() {
			const t = useT();
			const st = useDock();
			const [host, setHost] = useState(null);
			useEffect(() => {
				let dead = false;
				let warnedMiss = false;
				const ensure = () => {
					if (dead || typeof document === "undefined") return;
					/* 多路挂点兜底:语义化 data-* 优先,class 子串模糊匹配兜底(不绑定具体 CSS Module 哈希) */
					const row =
						document.querySelector('[data-dsh-hero-workspace-row]') ||
						document.querySelector('[data-conversation-hero]') ||
						document.querySelector('[class*="heroWorkspaceRow" i]') ||
						document.querySelector('[class*="hero" i][class*="workspace" i][class*="row" i]');
					if (!row) {
						if (!warnedMiss) {
							warnedMiss = true;
							try { console.warn("[dsh-purge] HeroNewSessionMount: anchor row missing (the host may have changed)"); } catch { /* ignore */ }
						}
						setHost((prev) => (prev ? null : prev));
						return;
					}
					warnedMiss = false;
					let el = row.querySelector(":scope > .dshp-hero-chip");
					if (!el) {
						el = document.createElement("div");
						el.className = "dshp-hero-chip";
						el.setAttribute("data-testid", "dsh-purge-hero-chip");
						row.appendChild(el);
					}
					setHost((prev) => (prev === el ? prev : el));
				};
				ensure();
				const obs = typeof MutationObserver !== "undefined"
					? new MutationObserver(() => ensure())
					: null;
				if (obs) obs.observe(document.body, { childList: true, subtree: true });
				const iv = setInterval(ensure, 1000);
				return () => {
					dead = true;
					if (obs) obs.disconnect();
					clearInterval(iv);
				};
			}, []);
			if (!host) return null;
			const btn = h("button", {
				type: "button",
				className: "dshp-hero-chip-btn" + (st.open ? " on" : ""),
				title: t("dock.newSession"),
				onClick: () => toggleDock(),
			},
				st.open ? h("span", { className: "dshp-live-dot", "aria-hidden": "true" }) : null,
				t("dock.newSession"),
			);
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function") return rd.createPortal(h(react.Fragment, null, btn, h(ShellWorkbenchButton)), host);
			} catch { /* host 可能没暴露 react-dom */ }
			return null;
		}

		/** 挂在「对话 / 轨迹 / 上下文」这一排，紧挨上下文。 */
		function TabRowPurgeMount() {
			const t = useT();
			const st = useDock();
			const [host, setHost] = useState(null);
			useEffect(() => {
				let dead = false;
				let warnedMiss = false;
				const ensure = () => {
					if (dead || typeof document === "undefined") return;
					/* 多路挂点兜底:data-* 优先,ARIA / class 子串兜底 */
					/* The tab row may be labelled in the host locale; match either language. */
					const zhConversationTab = String.fromCharCode(0x5bf9, 0x8bdd);
					const row =
						document.querySelector("[data-conversation-tabs]") ||
						document.querySelector("[data-conversation-tabrow]") ||
						document.querySelector("[role='tablist'][aria-label*='" + zhConversationTab + "'], [role='tablist'][aria-label*='Conversation' i]") ||
						document.querySelector("[class*='conversation' i][class*='tab' i][class*='row' i]");
					if (!row) {
						if (!warnedMiss) {
							warnedMiss = true;
							try { console.warn("[dsh-purge] TabRowPurgeMount: tab row anchor missing"); } catch { /* ignore */ }
						}
						setHost((prev) => (prev ? null : prev));
						return;
					}
					warnedMiss = false;
					let el = row.querySelector(":scope > .dshp-tab-chip");
					if (!el) {
						el = document.createElement("div");
						el.className = "dshp-tab-chip";
						el.setAttribute("data-testid", "dsh-purge-tab-chip");
						row.appendChild(el);
					}
					setHost((prev) => (prev === el ? prev : el));
				};
				ensure();
				const obs = typeof MutationObserver !== "undefined"
					? new MutationObserver(() => ensure())
					: null;
				if (obs) obs.observe(document.body, { childList: true, subtree: true });
				const iv = setInterval(ensure, 1000);
				return () => {
					dead = true;
					if (obs) obs.disconnect();
					clearInterval(iv);
				};
			}, []);
			if (!host) return null;
			const btn = h("button", {
				type: "button",
				className: "dshp-tab-btn" + (st.open ? " on" : ""),
				title: st.open ? (t("dock.inSession") + " · On") : (t("dock.inSession") + " · Click to open"),
				onClick: () => toggleDock(),
			}, t("dock.inSession"));
			try {
				const rd = require("react-dom");
				if (rd && typeof rd.createPortal === "function") return rd.createPortal(btn, host);
			} catch { /* host 可能没暴露 react-dom */ }
			return null;
		}


		function installRewindUi(ctx) {
			rewindHost = ctx;
			rewindSessions = ctx.sessions;
			rewindWorkspace = ctx.uiWorkspace || null;
			rewindConversation = ctx.conversation || null;
			ctx.slots.inject("conversation.input.right", () => ctx.slots.register({
				name: "conversation.input.right",
				id: "dsh-purge-rewind",
				order: 20,
				inject: (sessionId) => ({
					sessionId,
					t: ctx.locale.bind(NS),
				}),
			}, RewindSafe));
			// ctx.slots.inject("conversation.input.right", () => ctx.slots.register({
			// 	name: "conversation.input.right",
			// 	id: "dsh-purge-continue",
			// 	order: 21,
			// 	inject: (sessionId) => ({
			// 		sessionId,
			// 		t: ctx.locale.bind(NS),
			// 	}),
			// }, ContinueSafe));
			ctx.effect(() => installRewindWatch(ctx), "dsh-purge: rewind watch");
		}

		// 普通 command 结果不会激活宿主的空会话；补上输入节点，让结果卡片可见。
		const purgeCommandInputDefinition = {
			kind: "dsh-purge-command-input",
			target: "chat",
			match: (event) => event.type === "command/run" && event.data.name === "purge"
				? { id: String(event.data.commandId), role: "start" } : null,
			start: (_context, match) => ({
				commandId: match.event.data.commandId,
				seq: match.event.seq,
				time: match.event.time,
				text: `/purge${(match.event.data.args ?? "").trimEnd()}`,
			}),
			update: (context) => context.state,
			buildViewNode: (context) => context.state === undefined ? null : ({
				key: context.key,
				id: context.id,
				kind: "dsh-purge-command-input",
				target: "chat",
				anchorSeq: context.state.seq - 0.1,
				location: context.start?.location ?? { kind: "unresolved" },
				visibility: "visible",
				data: {
					commandId: context.state.commandId,
					text: context.state.text,
					time: context.state.time,
				},
			}),
		};

		function PurgeCommandInputView({ node }) {
			return h("div", {
				role: "group", "aria-label": "/purge", "data-command-input": "",
				style: { display: "flex", justifyContent: "flex-end", padding: "8px 24px" },
			}, h("div", {
				style: { whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxWidth: "100%",
					background: "var(--dsw-alias-bg-layer-2, #f3f4f6)", borderRadius: 12, padding: "10px 14px" },
			}, node.data.text));
		}

		function apply(ctx) {
			vmShellWorkbenchHost = ctx;
			const shellLifetime = new AbortController(); vmShellWorkbenchLifetime = shellLifetime;
			ctx.effect(() => () => { shellLifetime.abort(); if (vmShellWorkbenchHost === ctx) { vmShellWorkbenchHost = null; vmShellWorkbenchLifetime = null; } });
			ctx.slots.inject("conversation.session.header.utilities", () => ctx.slots.register({
				name: "conversation.session.header.utilities", id: "dsh-purge-vm-shell-workbench", order: 60,
			}, ShellWorkbenchButton));
			if (ctx.uiConversation && ctx.uiConversation.events && typeof ctx.uiConversation.events.register === "function") {
				ctx.uiConversation.events.register(purgeCommandInputDefinition);
				ctx.slots.inject("conversation.chat.node", () => ctx.slots.register({
					name: "conversation.chat.node", key: "dsh-purge-command-input",
				}, PurgeCommandInputView));
			}
			ctx.effect(() => ctx.locale.register(NS, { zh, en }), "dsh-purge: dictionaries");
			const t = ctx.locale.bind(NS);
			translate = t;
			ctx.slots.inject("shell.overlay", () => ctx.slots.register({
				name: "shell.overlay",
				id: "dsh-purge-dock",
				order: 50,
			}, () => h(react.Fragment, null, h(WelcomeNotice), h(PurgeLauncher), h(PurgeDock), h(HeroNewSessionMount), h(TabRowPurgeMount), h(EnvAdaptSendGate))));
			try {
				if (typeof ctx.inject === "function") {
					ctx.inject(["sessions", "uiWorkspace", "workspaces", "conversation"], (host) => installRewindUi(host));
				} else if (ctx.sessions) {
					installRewindUi(ctx);
				}
			} catch (e) {
				try {
					if (typeof ctx.inject === "function") {
						ctx.inject(["sessions", "uiWorkspace", "conversation"], (host) => installRewindUi(host));
					}
				} catch (e2) {
					try { console.warn("[dsh-purge] rewind ui skipped:", e2 || e); } catch { /* ignore */ }
				}
			}
		}

		exports.name = name;
		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	}
});
