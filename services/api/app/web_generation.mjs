// Media tools are available for page composition only in the conversation entry.
// Explicit exclusions and model capabilities are still checked by toolEnabled.
export function webMediaAllowed(constraints, kinds, outputKind) {
  return constraints?.taskSurface !== 'canvas_node' && kinds.has('html')
    && ['image', 'video', 'audio', 'text'].includes(outputKind);
}

export const webDesignInstructions = [
  '网页先围绕用户用途组织信息层级、版式、色彩、字体、媒体位置与交互状态，直接实现，不另加确认或润色模型。默认1440px桌面布局并加入 viewport=device-width 和响应式断点；移动端可重排，不能因画布缩略图而写死手机布局。尊重用户指定风格及局部修改范围。',
  '网页默认通过 canvas_create_html(style_framework=bootstrap) 使用离线 Bootstrap 5.3.8 的网格、表单、按钮、折叠、标签页、弹窗等组件，再用内联 CSS 定制字体层级、留白、配色、卡片和减少动画模式。用户指定其他实现时可用 none 和自包含代码；禁止依赖外部 CDN、网络字体或未加载的组件。Bootstrap 示例：.container/.row/.col-md-6；切换按钮 data-bs-toggle="tab" data-bs-target="#pane" 与 .tab-pane；折叠按钮 data-bs-toggle="collapse" data-bs-target="#details" 与 .collapse。ID 必须真实对应且唯一。',
  '网页按内容需要组合图像、文字、视频、音频，不能机械地全部生成。文案优先由主 Agent 直接编写；只有需要独立长文等才 generate_text。先复用本轮明确相关的真实素材；确实缺少媒体时才调用对应生成工具，图像不默认透明：照片或背景图保留完整画面，抠图主体才指定透明。视频/音频只在用户要求或页面用途确实需要时生成，遵守指定参数及不生成媒体等否定要求。',
  '网页需要新素材时，先一次性保存 design_plan：HTML 为最终交付，内部素材标 supporting=true；HTML 项用 dependsOn 和 inputs(source=deliverable, role=content) 引用素材项。已有素材用真实 asset ID，不重复生成。待依赖成功后，将真实返回的 asset://ID 嵌入 img、video、audio、source 或 CSS url；失败或未知计费继续走原任务恢复，不伪造素材、不自动重复收费生成。编辑时保留仍相关的 mediaAssetIds/imageAssetIds。仅已有素材的简单网页无需为流程增加计划。',
  '网页必须实现用户需要的页面交互：筛选改变实际列表并显示空状态与重置，标签页和菜单切换真实内容，表单用 label、输入校验和可见反馈，按钮绑定实际动作。没有后端时表单明确显示本地演示结果，不能宣称已发送或保存到服务器。音视频使用真实媒体及 controls、合理预加载，默认不自动播放有声内容。实现键盘操作、焦点和响应式状态；不放无行为的 # 链接、假播放器或假成功反馈。所有内容在隔离预览及离线导出后可用，不调用宿主应用接口，不虚构登录、支付或数据库服务。',
];
