# VM 命中位置候选发布与原生验收

目标：仅部署已通过的166程序候选；保留165程序回退，Chrome完整Harness界面及真实模型工具验收；规则、Mac权限、Kali和真实95待验证发现保持原范围。

## 阶段
1. 基线、空闲检查、候选归档与回退预检 — complete
2. 事务式部署、重启和认证健康 — complete
3. 独立合成项目的正式Chrome界面验收与真实模型调用 — complete
4. 原项目保护、资源清理、源码与交付记录更新 — complete

## 错误
预检回执曾把 GuessMainPID 的 yes 误作主PID；已改为精确匹配 MainPID 行，当前PID443319，未改变服务。

旁路collector有未转义正则括号导致SyntaxError，未执行RPC；改用字符串前缀判断并先做node --check。

## 边界
不安装研究规则、不自动接通离线多参数复核器、不放行R3、不commit/push。所有合成命中保持待验证。
