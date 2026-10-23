<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next';
import { helpServices } from '../features/pageServices';
const { appVersion } = helpServices.use();
</script>

<template>
<div class="help-page">
          <article class="help-document">
            <div class="help-document-meta"><span>MXINSPIREX / GUIDE</span><span>版本 v{{ appVersion }}</span></div>
            <h3>快速开始</h3>
            <p class="help-document-lead">描述需求，补充参考，在画布中继续完善设计。</p>
            <div class="help-section-grid">
              <section class="help-section"><span class="help-section-index">01</span><div><h4>连接模型</h4><p>在设置 → 模型与连接中填写服务地址和 Key，同步模型列表。</p></div></section>
              <section class="help-section"><span class="help-section-index">02</span><div><h4>开始创作</h4><p>输入需求，可附上图片或文档。发送后会创建项目，保留对话和成果。</p></div></section>
              <section class="help-section"><span class="help-section-index">03</span><div><h4>修改与引用</h4><p>选中画布节点继续修改，连线可将上游内容作为生成参考。转矢量等工具见设置 → 能力组件。</p></div></section>
              <section class="help-section"><span class="help-section-index">04</span><div><h4>保存与交付</h4><p>在项目中继续创作，在资产库预览与下载成果。费用记录见设置 → 用量和计费。</p></div></section>
            </div>
            <div class="help-contact"><div class="help-contact-icon"><CircleHelp :size="17" /></div><div><span class="card-label">CONTACT / SUPPORT</span><strong>产品咨询与使用反馈</strong><p>欢迎通过邮件交流设计需求、合作意向或使用中遇到的问题。</p></div><a class="help-contact-link" href="mailto:ziguishian@foxmail.com">ziguishian@foxmail.com <span aria-hidden="true">↗</span></a></div>
          </article>
        </div>
</template>
