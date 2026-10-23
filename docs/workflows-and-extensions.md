# 工作流、节点与能力规范 v1

## 使用

画布左上角 Home 右侧保存工作流，输入名字后保存到独立「工作流」页面。缩略图展示整张拓扑；打开生成独立项目副本，模板不变。模板会复制节点素材，不依赖源项目仍然存在。保存不包含运行结果、服务凭据或历史任务。

双击画布搜索「文件夹」添加输入节点，在节点内部上传图片 / TXT / Markdown / HTML 文件夹。文件列表保存在同一个节点内，将其输出连接到操作节点，即对整批逐项执行；普通输入作为共用参考。一次仅允许一个批次，避免隐式笛卡尔积。右上角绿色播放图标运行整个工作流，运行次数可直接编辑，数字右侧箭头增减，范围 1–20，表示整个批次重复次数。每次运行最多 200 个步骤，串行执行。文件夹内素材随工作流模板独立复制，打开模板时恢复；下游单节点生成入口提示改用工作流运行，避免遗漏批量引用。

生成节点需填写提示词；空白图片节点也可右键设为转矢量或抠图步骤，连接一个上游图片即可。其余没有提示词的节点只作为输入。按连线拓扑执行，循环连线拒绝运行。每项创建输入快照和新的输出节点，不覆盖原作品。失败或受理未知时停止后续，不自动重发。停止按钮阻止新步骤；已受理模型请求仍可能完成和计费。当前版本调度由打开的画布负责，退出画布后停止追加步骤，已提交任务仍由后端保存。重新打开不会自动继续收费任务。

## 两层扩展契约

**能力**实现处理过程；**节点**声明界面和端口并绑定能力。一个能力可由多个节点复用。契约实现见 `services/api/app/capability_contracts.py`。第三方集成在源码中显式注册，不支持下载任意 Python/JS 文件后直接执行。

能力清单字段：`schemaVersion: "1.0"`、命名空间 `id`（如 `example.vectorize`）、`version`、`name`、`description`、`execution`（local/provider）、`inputs`、`outputs`、JSON Schema `parameters`、`permissions`。端口字段：`id`、`label`、`type`（image/text/video/audio/model3d/cad/palette/storyboard/file）、`multiple`、`required`。

节点清单字段：`schemaVersion`、`id`、`name`、`capability`、`inputBindings`、`outputBindings`。映射值必须是能力端口 ID。节点持久化只保存清单 ID、版本、参数、资产 ID、位置和连线；不保存执行代码或密钥。

注册流程：实例化 `CapabilityRegistry`，调用 `register(manifest, handler)`，再 `register_node(nodeManifest)`。宿主在启动模块显式加载受信任插件并为节点接入 Vue 视图和执行入口；不由清单中的路径、URL、命令自动导入插件。现有内置节点仍使用原入口，注册 API 是开发接入接口，不代表热安装市场已实现。

处理器签名：`handler(*, context, inputs, parameters)`。context 由宿主提供受限资产读写、projectId、runId、stepId、取消信号、回执存储。处理器返回 `{status, outputs, receipt, error}`；outputs 引用已保存资产，不能覆盖输入文件。状态为 succeeded/failed/cancelled/unconfirmed。错误含 code、message、submitted；未知受理不得自动重试。

宿主必须验证参数 JSON Schema、端口类型与必填项、权限、节点版本和输入快照，再调用处理器。permissions 是需求声明，不授予系统权限。文件访问由宿主资产服务代理，网络能力仅接受显式配置的 Provider；密钥只能在后端获取。第三方 Python 插件与宿主同权限，仅安装经过审查的代码；未经信任的代码需要独立沙箱，本版本不提供该隔离保证。

幂等键由 runId / round / itemId / nodeId 组成。同一键只允许一次受理；重连查询原任务，不重发生成。更新插件需声明兼容版本及迁移函数；找不到能力时保留未知节点并阻止执行，不能静默换成其他模型。

开发验证至少包含：端口不匹配、缺配置、取消、重复提交、Provider 断流、保存重启、原输入不变。模型调用不得在加载清单或预览节点时发生。
