# Agent 发布检查

执行 `npm run verify:agent-release`。`npm run package:win`、`package:mac`、`package:all` 和 `package:lite` 的前置脚本自动运行同一检查；任一阶段失败即阻止后续打包。不要使用 `--ignore-scripts` 绕过，也不要直接调用底层打包脚本替代发布入口。

需要 Node 依赖、Electron，以及安装 API 依赖的 `services/api/.venv`；特殊 Python 路径用 `AICS_TEST_PYTHON` 指定。检查按序执行类型检查、全量 Vitest、画布/任务核对的 Python 回归、真实 API 持久化、七类节点输入框、恢复按钮、综合画布交互。

每次在 `.tmp/agent-release-<时间戳>/` 创建独立 SQLite 工作区、pytest 临时目录、API 日志和 `report.json`。API 使用随机本地端口，结束后关闭；不连接用户工作区。测试使用模拟 Provider/组件生成事件，不消耗真实模型额度，也不上传发布包。真实 Electron 与数据库链路通过，不代表某一供应商当时在线或所有模型能力均通过。

正式发布前还需人工在独立项目验证已配置供应商的真实图像、视频等生成与安装包升级；检查返回资产、计费回执、引用来源、断流取回。未知收费请求不得自动重发。

节点输入框的单项交付摘要直接使用实时连线与去重后的图片 ID；断线、重新连线和上游变化同步更新。不增加确认步骤，也不估算未取得的价格。任务核对面板只允许已结束且有未保存原任务编号的请求取回结果；运行、排队、取消任务禁用入口，重复点击只执行一次。工具回执的 `submitted=false` 仅表示该工具未提交，不表示整个任务没有文本调用或费用。
