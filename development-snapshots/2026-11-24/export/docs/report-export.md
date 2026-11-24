# VM 报告交付包

> 当前版本、恢复点和完成状态统一见[当前状态](current-status.md)。本文的历史验收段落只描述当时结果。

v24 的安全交付导出是 CLI 工具；面板原有“下载报告”仍只下载 Markdown，不会自动打包图片。

在 VM 的 Shell 工作台中使用：

```sh
DSH_HOME=/home/purge/.dsh-improved \
  /home/purge/.local/node/bin/node \
  /home/purge/tools/dsh-purge-personal-1.1.77-personal.1/scripts/export-engagement-report.mjs \
  --engagement <面板项目ID> --out /home/purge/workspace/report-deliveries
```

将项目ID替换成要交付的项目。`--out` 是父目录，每次成功都会返回新的 `report-随机值/bundle/report.md` 路径。分享时携带整个 `bundle` 目录，其中有正文、实际引用附件和 `manifest.json`；不要只取 Markdown。旧包与原有文件不会被替换。

输出必须在 Redteam 数据根之外，也不能是该根的祖先。附件缺失、被改动、缺登记 SHA256 或不是普通文件时会报错；核对原始证据，必要时通过正常的证据登记流程重新登记。不要直接修改数据库摘要使错误消失。

发布前失败只清理本次临时容器。若提示“交付包已发布，请检查现有包后再操作”，先按返回路径检查，不把错误视为未写入，也不盲目重复操作。意外终止可能留下未发布的 `.staging`；仅有 `bundle/manifest.json` 也不能代替对正文/图片和清单的核对。

清单记录正文和附件大小、SHA256，可用于核对交付字节；它不是签名、不证明截图真实性。文字脱敏不等于图片像素脱敏，分享前仍需查看图片。无自动上传或模型调用；这次变更不改变 VM 或宿主权限。
