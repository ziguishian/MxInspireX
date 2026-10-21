<script setup lang="ts">
import { ref } from 'vue';
import { ChevronDown, Images, Trash2, BookOpen } from 'lucide-vue-next';
import PageHeader from '../components/shared/PageHeader.vue';
import EmptyState from '../components/shared/EmptyState.vue';
import { knowledgeLibraryServices, type KnowledgeDocument } from '../features/pageServices';

type KnowledgePart = {
  id: string;
  kind: 'page_preview' | 'embedded_image';
  locator: string;
  filename: string;
  mime: string;
  width?: number;
  height?: number;
  pageNumber?: number;
  slideNumber?: number;
  availability: 'available' | 'virtual' | 'unsupported' | 'omitted';
};

const {
  loadState, apiBaseUrl, globalKnowledgeDocs, isUploadingGlobalKnowledge, isReindexingGlobalKnowledge,
  uploadGlobalKnowledge, reindexGlobalKnowledge, deleteDocument,
} = knowledgeLibraryServices.use();
const globalKnowledgeFileInput = ref<HTMLInputElement | null>(null);
const expandedDocuments = ref<Record<string, boolean>>({});
const partsByDocument = ref<Record<string, KnowledgePart[]>>({});
const partTotals = ref<Record<string, number>>({});
const loadingParts = ref<Record<string, boolean>>({});
const partErrors = ref<Record<string, string>>({});

function triggerGlobalKnowledgeUpload() { globalKnowledgeFileInput.value?.click(); }
function documentStatus(document: KnowledgeDocument) {
  if (document.status === 'ready') return '已解析';
  if (document.status === 'partial') return '部分解析';
  return '仅保存原文件';
}
function partUrl(documentId: string, partId: string) {
  return `${apiBaseUrl}/api/knowledge/documents/${encodeURIComponent(documentId)}/parts/${encodeURIComponent(partId)}/content?variant=preview`;
}
async function toggleDocument(document: KnowledgeDocument) {
  expandedDocuments.value = { ...expandedDocuments.value, [document.id]: !expandedDocuments.value[document.id] };
  if (!expandedDocuments.value[document.id] || partsByDocument.value[document.id] || loadingParts.value[document.id]) return;
  loadingParts.value = { ...loadingParts.value, [document.id]: true };
  partErrors.value = { ...partErrors.value, [document.id]: '' };
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge/documents/${encodeURIComponent(document.id)}/parts?limit=100`);
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json() as { parts?: KnowledgePart[]; total?: number };
    partsByDocument.value = { ...partsByDocument.value, [document.id]: payload.parts ?? [] };
    partTotals.value = { ...partTotals.value, [document.id]: payload.total ?? payload.parts?.length ?? 0 };
  } catch (error) {
    partErrors.value = { ...partErrors.value, [document.id]: error instanceof Error ? error.message : '文档图片读取失败' };
  } finally {
    loadingParts.value = { ...loadingParts.value, [document.id]: false };
  }
}
</script>

<template>
  <div class="library-page">
    <PageHeader
      eyebrow="KNOWLEDGE BASE / LOCAL RAG"
      title="历史资料"
      description="保留上传文档的正文、页面与内嵌图片。需要时可在对话中显式引用；文档内容不会被当作 Agent 指令。"
    />
    <div class="knowledge-library-toolbar">
      <button class="primary-button" :disabled="isUploadingGlobalKnowledge" @click="triggerGlobalKnowledgeUpload">
        {{ isUploadingGlobalKnowledge ? '解析正文与图片中…' : '上传知识文档' }}
      </button>
      <button class="ghost-button" :disabled="!globalKnowledgeDocs.length || isReindexingGlobalKnowledge" @click="reindexGlobalKnowledge">
        {{ isReindexingGlobalKnowledge ? '重建中…' : '重建解析与索引' }}
      </button>
      <input
        ref="globalKnowledgeFileInput"
        class="sr-only"
        type="file"
        accept=".txt,.md,.markdown,.csv,.json,.html,.htm,.pdf,.docx,.pptx,.png,.jpg,.jpeg,.webp"
        @change="uploadGlobalKnowledge"
      />
      <span class="muted">独立于项目 · 本地解析 · 图片按需读取</span>
    </div>
    <p class="knowledge-scope-note">
      首页上传的资料只归当前项目使用；本页文档通过 @知识文档 显式引用。图片先作为隐藏子资源保存，实际用于创作时才进入项目资产库。
    </p>
    <EmptyState v-if="loadState.loading.value && !globalKnowledgeDocs.length">正在读取资料…</EmptyState>
    <EmptyState v-else-if="loadState.error.value">
      {{ loadState.error.value }}
      <template #action><button class="ghost-button" :disabled="loadState.loading.value" @click="loadState.retry">重新加载</button></template>
    </EmptyState>
    <EmptyState v-else-if="!globalKnowledgeDocs.length" :icon="BookOpen" title="把资料整理为设计参考">上传 DOCX、PPTX 或 PDF 后，可读取正文、内嵌图片与 PDF 页面。</EmptyState>
    <div v-if="globalKnowledgeDocs.length" class="knowledge-list">
      <div v-for="doc in globalKnowledgeDocs" :key="doc.id" class="knowledge-item-shell">
        <div class="knowledge-item">
          <span class="doc-icon">▤</span>
          <span class="knowledge-item-copy">
            <strong>{{ doc.title }}</strong>
            <small>
              {{ doc.pathRelative }}
              <template v-if="doc.chunkCount"> · {{ doc.chunkCount }} 个文本片段</template>
              <template v-if="doc.pageCount"> · {{ doc.pageCount }} 页</template>
              <template v-if="doc.imageCount"> · {{ doc.imageCount }} 张内嵌图片</template>
              <template v-if="doc.parser"> · {{ doc.parser }}</template>
            </small>
            <small v-if="doc.warning" class="knowledge-warning">{{ doc.warning }}</small>
          </span>
          <span class="doc-status" :data-status="doc.status">{{ documentStatus(doc) }}</span>
          <button
            v-if="doc.partCount"
            type="button"
            class="knowledge-expand-button"
            :aria-expanded="Boolean(expandedDocuments[doc.id])"
            :aria-label="`${expandedDocuments[doc.id] ? '收起' : '查看'} ${doc.title} 的页面和图片`"
            @click="toggleDocument(doc)"
          >
            <Images :size="14" />
            <span>{{ doc.partCount }}</span>
            <ChevronDown :size="13" :class="{ rotated: expandedDocuments[doc.id] }" />
          </button>
          <button type="button" class="library-delete-button" :aria-label="`删除知识文档 ${doc.title}`" title="删除知识文档" @click="deleteDocument(doc)">
            <Trash2 :size="14" />
          </button>
        </div>
        <div v-if="expandedDocuments[doc.id]" class="knowledge-parts-panel">
          <span v-if="loadingParts[doc.id]" class="muted">正在读取文档子资源…</span>
          <span v-else-if="partErrors[doc.id]" class="knowledge-warning">{{ partErrors[doc.id] }}</span>
          <span v-else-if="!partsByDocument[doc.id]?.length" class="muted">该文档没有可预览的页面或图片。</span>
          <template v-else>
            <a
              v-for="part in partsByDocument[doc.id]"
              :key="part.id"
              class="knowledge-part-card"
              :class="{ unavailable: part.availability === 'unsupported' || part.availability === 'omitted' }"
              :href="part.availability === 'unsupported' || part.availability === 'omitted' ? undefined : partUrl(doc.id, part.id)"
              target="_blank"
              rel="noreferrer"
            >
              <img
                v-if="part.availability !== 'unsupported' && part.availability !== 'omitted'"
                :src="partUrl(doc.id, part.id)"
                :alt="part.locator"
                loading="lazy"
              />
              <span v-else>无法预览</span>
              <small>{{ part.pageNumber ? `第 ${part.pageNumber} 页` : part.slideNumber ? `幻灯片 ${part.slideNumber}` : part.locator }}</small>
            </a>
            <span v-if="partTotals[doc.id] > partsByDocument[doc.id].length" class="knowledge-parts-more">
              当前显示前 {{ partsByDocument[doc.id].length }} / {{ partTotals[doc.id] }} 项
            </span>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
