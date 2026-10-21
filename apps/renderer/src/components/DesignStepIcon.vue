<script setup lang="ts">
import { computed, type Component } from 'vue';
import { BookOpen, Bot, Box, CalendarClock, CalendarPlus, CalendarCog, CheckCheck, CircleStop, CircleX, ClipboardList, CodeXml, Crop, Download, Eye, FileCheck2, FileSearch, FileText, FolderOpen, GitBranch, Globe, History, Image, Images, Inbox, LayoutPanelLeft, Link2, MessageCircleQuestion, MessageSquareText, Mic, Music2, Paperclip, PencilLine, ReceiptText, RotateCw, Scissors, Search, Settings2, SquarePlus, Undo2, Video, Wrench } from 'lucide-vue-next';
import type { DesignStep } from '../designPresentation';

const props = defineProps<{ step: DesignStep }>();
const toolIcons: Record<string, Component> = {
  design_plan: ClipboardList,
  search: Search,
  web_search: Globe,
  web_read: FileSearch,
  knowledge_search: BookOpen,
  asset_search: Images,
  asset_inspect: Eye,
  context_read: FolderOpen,
  conversation_read: History,
  list_models: Settings2,
  generate_text: FileText,
  generate_image: Image,
  generate_video: Video,
  generate_audio: Music2,
  generate_3d: Box,
  generate_cad: Box,
  image_edit: Crop,
  media_edit: Scissors,
  transcribe_audio: Mic,
  schedule_list: CalendarClock,
  schedule_create: CalendarPlus,
  schedule_update: CalendarCog,
  canvas_read: LayoutPanelLeft,
  canvas_create_html: CodeXml,
  canvas_create_media: Images,
  canvas_create_node: SquarePlus,
  canvas_create_text: FileText,
  canvas_update_node: PencilLine,
  canvas_link_nodes: Link2,
  canvas_versions: History,
  canvas_restore_node: Undo2,
  export_deliverable: Download,
  delivery_verify: FileCheck2,
  budget_check: ReceiptText,
  repair_control: Wrench,
  request_clarification: MessageCircleQuestion,
  report_progress: MessageSquareText,
};
const phaseIcons: Record<string, Component> = {
  queued: Inbox,
  running: Bot,
  agent: Bot,
  attachments: Paperclip,
  retrieval: Search,
  generation: CodeXml,
  media: Images,
  model: FileCheck2,
  route: GitBranch,
  route_failed: GitBranch,
  escalation: GitBranch,
  retry: RotateCw,
  recovered: RotateCw,
  succeeded: CheckCheck,
  failed: CircleX,
  cancelled: CircleStop,
};
// Keep the function recognizable while its status changes.
const icon = computed(() => props.step.tool ? toolIcons[props.step.tool] || Wrench
  : props.step.kind === 'summary' ? MessageSquareText : phaseIcons[props.step.phase || ''] || Bot);
</script>

<template>
  <component :is="icon" class="design-step-icon" :size="14" :stroke-width="1.6" aria-hidden="true" />
</template>
