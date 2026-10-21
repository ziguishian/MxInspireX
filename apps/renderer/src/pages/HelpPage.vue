<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next';
import { helpServices } from '../features/pageServices';
const { appVersion } = helpServices.use();
</script>

<template>
<div class="help-page">
          <article class="help-document">
            <div class="help-document-meta"><span>MXINSPIREX / GUIDE</span><span>版本 v{{ appVersion }}</span></div>
            <h3>从需求到方案，与设计 Agent 一起推进</h3>
            <p class="help-document-lead">MxinspireX 是由灵矩绘境研发的 AI 设计 Agent，将需求、参考资料与生成工具连接起来，协助完成视觉探索、方案生成与持续迭代。对话、设计资产与画布保留在同一个项目中，方便继续修改和整理交付。</p>
            <div class="help-section-grid">
              <section class="help-section"><span class="help-section-index">01</span><div><h4>开始任务</h4><p>在首页输入一句话需求，或上传图片、文档和表格。点击发送后，系统会创建项目并开始解析。</p></div></section>
              <section class="help-section"><span class="help-section-index">02</span><div><h4>让 Agent 调用工具</h4><p>Agent 会按目标选择知识检索、资产搜索、图像或视频生成，以及画布节点工具；每次调用都会保留来源和状态。</p></div></section>
              <section class="help-section"><span class="help-section-index">03</span><div><h4>继续编辑与引用</h4><p>点击画布里的媒体节点即可把资产引用带回对话，继续修改方案、补充约束或生成下一版结果。</p></div></section>
              <section class="help-section"><span class="help-section-index">04</span><div><h4>管理个人资料</h4><p>点击左下角头像查看概览，再点击卡片中的设置进入用户中心。可修改昵称、简介和预设头像，并查看本月与近 7 天 Token 使用情况，首页常驻显示累计 Token 与人民币费用预估。</p></div></section>
            </div>
            <section class="help-section help-section-wide"><span class="help-section-index">05</span><div><h4>模型与工作区</h4><p>左下角卡片会显示当前模型和可用状态；打开设置可以配置服务商、模型和外观。左侧首页按钮返回首页，项目、资产和参考库入口用于继续查找工作成果。</p></div></section>
            <div class="help-contact"><div class="help-contact-icon"><CircleHelp :size="17" /></div><div><span class="card-label">CONTACT / SUPPORT</span><strong>产品咨询与使用反馈</strong><p>欢迎通过邮件交流设计需求、合作意向或使用中遇到的问题。</p></div><a class="help-contact-link" href="mailto:ziguishian@foxmail.com">ziguishian@foxmail.com <span aria-hidden="true">↗</span></a></div>
          </article>
        </div>
</template>
