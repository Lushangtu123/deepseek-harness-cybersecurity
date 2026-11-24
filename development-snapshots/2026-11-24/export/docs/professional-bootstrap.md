# 专业环境离线安装

这一步补充基础 Harness 安装之后的程序和运行资产。仅适用于本项目的 Ubuntu 24.04 ARM64、`purge` UID1000、`/home/purge` 与既有隔离网络模板，不创建VM、不更改Mac权限或共享。不能用它升级日常VM或合并已有账号、项目。

默认仅显示计划，不连接工具或改动文件：

```sh
python3 -B scripts/professional_guest.py
```

## 准备资产包

在已安装本项目固定版本工具的专用VM中，从本仓库执行：

```sh
python3 -B scripts/professional_guest.py --build-bundle /home/purge/downloads/professional-offline-bundle
```

目录必须尚不存在。构建只读取列明的运行时、依赖、Ghidra、reverse-skill固定提交、可选插件、扫描器规则和漏洞库，以及六个固定内容ID的Docker镜像。镜像通过`docker image save`导出，不读取容器文件系统或卷。账号、聊天、工作区项目、审计数据库、PentAGI旧任务和私有环境文件均不在收集范围内；唯一允许的数据库资产是固定的Trivy漏洞库。凭据/状态文件变体与不安全链接会被排除或拒绝。

输出包含`programs.tgz`、`images.tar.gz`和`manifest.json`，并单独输出清单SHA256。文件体积较大，需要足够存储与暂存空间。保留单独核对过的清单摘要，随资产包私下备份；不要把二进制包或凭据上传到公开仓库。清单摘要用于核对字节，不是数字签名，也不能证明来源VM未被修改。资产包保留原依赖及许可证，不声称是上游的可重复构建。

## 在新环境安装

先按[基础安装](basic-bootstrap.md)准备空白VM并安装Harness。专业环境还需要`openjdk-21-jdk-headless`、`docker.io`、`docker-compose-v2`、`python3-yaml`、`binutils`、`file`和`curl`；Ghidra需要完整JDK，只有`java`而没有`javac`的JRE会被安装前检查拒绝。系统软件包由新VM原有发行版渠道提供。本脚本不会安装Docker守护进程或扩大宿主访问。

基础安装完成后，先不要配置账号、聊天、添加工作区或修改服务。基础安装器会在私有完成记录中保存九个固定初始化文件的摘要，包括首次生成的凭据容器和空白工作区注册表；专业安装只接受这些字节仍一致的状态，以及经读取确认没有绑定或项目的初始资料库。旧版基础完成记录缺少这些摘要时，需要重新建立空白环境，不能事后补造完成记录。

把三份资产文件传入新VM的同一个普通目录，例如`/home/purge/professional-assets`，先只读核对：

```sh
python3 -B scripts/professional_guest.py \
  --bundle /home/purge/professional-assets \
  --manifest-sha256 '<单独保留并核对的SHA256>'
```

确认目标为新的基础环境后，显式加`--apply`：

```sh
python3 -B scripts/professional_guest.py \
  --bundle /home/purge/professional-assets \
  --manifest-sha256 '<单独保留并核对的SHA256>' \
  --apply
```

安装先核对清单及两份归档的大小/摘要，限制原始归档头、PAX字段、成员数量和展开大小，检查重复、类型、链接与父路径，再暂存程序。载入镜像后再次核对固定内容ID。扫描资源检查与任务执行使用本地内容ID，不依赖导出/导入后可能丢失的仓库摘要别名。

暂停基础服务前再次核对目标，原基础运行时和被替换的固定配置保存在私有`.harness-professional/basic-backup`。安装后实际检查版本、REA入口、原版运行时逐项清单、扫描资源、网页服务和HTTP响应，取得结果后才写完成记录。已有安装或不完整安装标记会被拒绝，不自动重试、覆盖或隐式回滚；失败阶段保留在`.harness-professional/failed.json`，日志留在本机私有目录。此流程面向可重建的新环境，不能保证突然断电时所有程序/镜像操作一起原子回退。

## 账号与运行边界

模型账号不在包内，也不会从旧环境复制；需要在新VM本地单独配置。原版能力运行时已安装，默认关闭，之后可按既有入口明确启用。完整原版的独立配置也只初始化程序和配置，不导入旧会话。

PentAGI程序、固定工作镜像、CLI和Compose配置会安装；数据库口令及Cookie盐在新VM重新随机生成，模型API键留空。安装器默认不启动PentAGI。配置模型账号、启动服务及初始化新的本地API凭据是后续本机步骤，不能把文件安装成功解释为模型任务已可完成；不要将密钥、环境文件、管理员文件或令牌粘贴到聊天或公开仓库。

已有技能、MCP配置与可选插件作为程序配置安装，不构成目标授权。REA/Ghidra与reverse-skill的具体任务仍需相应工具和样本；本流程不安装IDA、Hopper或完整Kali工具集。扫描器就绪不等于完整覆盖，Semgrep既有解析缺口仍保留。

Git仓库保存安装器、配置和固定版本记录，大型资产包仍需另行保管；只有源码clone不能替代资产包、系统依赖、宿主隔离模板或账号设置。实际完成范围应以对应验收记录为准。

## 实际验收范围

2026-10-31，最终全新官方 Ubuntu 24.04 ARM64 测试盘从完整JDK、基础安装到专业资产导入一次跑通，无需手工修补。实测REA MCP握手、静态JavaScript和Ghidra合成函数反编译，PentAGI本地启动/认证/读取接口，原版能力入口启动后返回改进版，以及IAB插件五个组件运行和冷刷新。重复安装被拒绝，已生成的私有配置保持原样。

只测试了列明的本地功能，没有调用模型或提交扫描；PentAGI完整模型工作流和完整原版独立配置的运行未在本次新环境验收中执行。新环境需在界面选择VM内工作区并本地配置模型账号。临时验收入口停用生产管理元数据，所以VM版本标识显示不可用；日常环境继续使用原受管入口。详情见[结构化验收](professional-bootstrap-verification.json)与[资产摘要](../inventory/professional-assets-lock.json)。

2026-11-10 已用独立 Ubuntu VM 验证当前候选的两阶段安装与合成工具入口。专业配置保留工作区路径，Chrome 首次打开自动创建默认工作区，刷新后工作区 ID 保持一致。[本轮验收记录](clean-install-candidate.md)
