# 报告与 SDK 修复候选

状态：PRE-F2、SDK-F1 的 VM 源码候选；未部署日常环境，未推送 GitHub。验证汇总见 `report-sdk-results.json`。前序快照/规则、证据和生命周期修复继续保留，完整工作区与普通模式 R3 尚未合格。

## 报告证据

`store-core.js` 原先仅凭“校正”备注，宣称得分在最终复核中下调，并附带固定 16180/16090。现仅说明记录含校正备注，显示本项目当前有效得分，明确历史分值与独立核实不能由备注推定。现有计分算法保留；合法记录的 16180 仍显示。校正列表复用既有 `effPoints`，与默认得分和倍率计算一致；未把备注变成已确认漏洞或复核通过。

合成用例涵盖 0 分空项目、7 分、合法 16180、项目隔离、未显式覆盖默认分、倍率和历史持久化 0。新增 0 分输入原本被 API 拒绝，该对照只检查已有数据库的读取，不改变准入规则。

## SDK 来源

`tools.js` 的加载器只接受 VM 两个批准安装根：

- `/home/purge/tools/harness-improved-runtime`
- `/home/purge/tools/harness-original-capabilities`

运行入口/DSH_BASE 只能从这两处选择，不能新增路径；已选安装缺失或无效时直接 `SDK_NOT_READY`，不会改试另一版本。cwd、插件祖先、DSH_HOME、profile、系统可执行目录不作为可信根。

加载前校验批准根、普通安装 manifest、本地 SDK 包真实目录及 manifest，再校验解析入口位于该 SDK 包真实目录内。由此拒绝 Node 祖先包回退、祖先包 main 反指批准根、外部 symlink 和越界 main，并在评估模块前失败。[Node 模块解析说明](https://nodejs.org/download/release/v24.20.0/docs/api/modules.html) 说明 bare package 查找会向祖先 node_modules 搜索，故只检查最终入口在大安装目录内仍不足。

批准目录仍是可维护的信任根；本修复不是包发布者签名验证、所有传递依赖的完整性证明、抗批准目录被改写的保证，也不扩大为 Mac 版 SDK 兼容性承诺。异常时需修复受管 VM 安装，不应以项目目录绕过失败。

## 复核和界限

独立 Codex 复核指出两个候选遗留问题：校正列表默认分显示 0、祖先包 metadata 反指批准根。均先记录失败探针，再修复回归。复核主体、范围与实际 VM SDK 工厂验证分开记录，未调用 Claude/DeepSeek 外部复核 API。

本轮没有扫描私人项目、启动利用、调用模型或执行合成 SDK tool 的 execute。宿主桥接问题仅形成 `bridge-boundary-plan.md`，HOST-F1/F3 尚未修复。后续需在独立宿主桥接候选中完成，之后才安排 Chrome/Harness 原生模型链、恢复点及发布；95 条真实项目发现仍待核实。
