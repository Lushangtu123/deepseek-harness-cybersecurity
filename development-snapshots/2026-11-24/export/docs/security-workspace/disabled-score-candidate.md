# 停用得分点计分修复候选

状态：本步骤验收与最终外部复核完成，仍为未日常部署的源码候选。仅处理停用无code自建点仍计入攻击链阶段分，以及停用点在共享rule下占用cap/dedup位置；不修改链路分页、面板文案、宿主桥接或日常配置。

共享evaluateScoreBoard在enabledOnly=true时，按数据库point_id读取enabled，避免多个null code的状态丢失；为每条准备行附disabled布尔标记，先确定disabledIds再执行竞争。applyScoreCaps跳过disabled行的dedup和cap占位，仍返回所有记录与各自disabled标记，保留原self_created含义，避免把停用伪装成自建或封顶。

面板也使用enabledOnly，单点counted/earned不含停用记录；报告与攻击链使用同一状态标记。启用状态每次求值重新读取，正常API停用/重启用不删除命中。显式enabledOnly=false保持原先包含全部记录的辅助计算语义；生产三处均启用过滤。不承诺跨进程并发写入时多个独立API视图的原子快照一致性。

只复用node:sqlite既有prepare().all()与Map，无新依赖、迁移或规则上限改变。[Node SQLite官方说明](https://nodejs.org/api/sqlite.html)给出了同一基础读取API；实际兼容性另以本机和VM回归验证。

测试使用临时SQLite和惰性字符串，覆盖无code、多个不同默认分、开关恢复、共享rule的cap/dedup和不同插入顺序、倍率高分、记录保留、显式全记录模式以及自建/停用排除互斥。共享rule的元数据配置仅是明确的合成夹具；没有声称日常内置目录已存在共享rule对。

此前倍率/默认分/计数修复保留。500条攻击链范围、cap文案与原始/有效分展示建议继续待办；HOST-F1/F3、普通R3、完整工作区、原生模型链与95条真实项目发现未因本轮完成。候选不等于整体发布合格。

复核：Claude安全拒绝；首轮Flash完整材料触及输出上限无正文，不计通过。使用相同完整用户材料的共享入口/调用方两域V4.1 Flash high复核均返回stop，主代理核对后两条P2关闭。disabled是新增行标记，disabledIds是既有返回字段；无表假db和全停用rule无caps条目的观察未被确认为生产回归。局部无阻断不等于全产品合格。
