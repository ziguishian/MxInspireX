<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { projectLibraryServices } from '../features/pageServices';
import LibraryPageLayout from '../components/shared/LibraryPageLayout.vue';
import { nodePreviewSize } from '../nodeSizing';
const { apiBaseUrl } = projectLibraryServices.use();
const router = useRouter();
const workflows = ref<any[]>([]), search = ref(''), error = ref(''), opening = ref('');
const filtered = computed(() => workflows.value.filter(w => w.name.toLowerCase().includes(search.value.toLowerCase())));
function bounds(board: any) {
  const nodes = board.nodes;
  const x = Math.min(...nodes.map((n:any) => n.position.x)) - 40, y = Math.min(...nodes.map((n:any) => n.position.y)) - 40;
  return `${x} ${y} ${Math.max(...nodes.map((n:any) => n.position.x + nodePreviewSize(n.data).width)) - x + 40} ${Math.max(...nodes.map((n:any) => n.position.y + nodePreviewSize(n.data).height)) - y + 40}`;
}
function point(board:any, id:string, output:boolean) { const n=board.nodes.find((n:any)=>n.id===id); const size=nodePreviewSize(n.data); return {x:n.position.x+(output?size.width:0),y:n.position.y+size.height/2}; }
onMounted(async () => { try { const r=await fetch(`${apiBaseUrl}/api/workflows`); if(!r.ok) throw Error('工作流读取失败，请检查本地服务是否已更新'); workflows.value=await r.json(); } catch(e) { error.value=(e as Error).message; } });
async function open(id:string) {
  if(opening.value)return; opening.value=id; error.value='';
  try { const r=await fetch(`${apiBaseUrl}/api/workflows/${id}/open`,{method:'POST'}); if(!r.ok) throw Error('工作流打开失败'); const data=await r.json(); await router.push(`/projects/${data.project.id}`); }
  catch(e){ error.value=(e as Error).message; } finally{opening.value='';}
}
</script>
<template>
  <LibraryPageLayout v-model:search="search" title="我的工作流" eyebrow="WORKFLOWS" description="复用节点与连线，每次打开创建独立工作副本。" search-label="搜索工作流">
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="workflow-grid">
      <button v-for="item in filtered" :key="item.id" class="workflow-card" :disabled="!!opening" @click="open(item.id)">
        <svg :viewBox="bounds(item.canvas)" role="img" :aria-label="`${item.name}完整工作流缩略图`">
          <line v-for="edge in item.canvas.edges" :key="edge.id" :x1="point(item.canvas,edge.source,true).x" :y1="point(item.canvas,edge.source,true).y" :x2="point(item.canvas,edge.target,false).x" :y2="point(item.canvas,edge.target,false).y" stroke="var(--theme-text-muted)" stroke-width="3" />
          <g v-for="node in item.canvas.nodes" :key="node.id"><rect :x="node.position.x" :y="node.position.y" :width="nodePreviewSize(node.data).width" :height="nodePreviewSize(node.data).height" rx="12" fill="var(--theme-surface)" stroke="var(--theme-text-muted)" stroke-width="2"/><image v-if="node.data.workflowAsset?.mime?.startsWith('image/')" :href="`${apiBaseUrl}/api/workflows/${item.id}/assets/${node.id}`" :x="node.position.x" :y="node.position.y+36" :width="nodePreviewSize(node.data).width" :height="Math.max(1,nodePreviewSize(node.data).height-36)" preserveAspectRatio="xMidYMid meet" /><text :x="node.position.x+12" :y="node.position.y+28" fill="var(--theme-text)" font-size="18">{{ (node.data.title || node.data.kind).slice(0,16) }}</text></g>
        </svg><strong>{{ item.name }}</strong><small>{{ opening===item.id?'正在打开…':`${item.canvas.nodes.length} 个节点` }}</small>
      </button>
    </div>
    <p v-if="!workflows.length && !error">在画布左上角点击“保存工作流”，即可保存到这里。</p>
  </LibraryPageLayout>
</template>
<style scoped>
.workflow-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}
.workflow-card{display:grid;gap:8px;text-align:left;padding:16px;border:1px solid var(--theme-border);border-radius:16px;background:var(--theme-surface);color:var(--theme-text);cursor:pointer}
.workflow-card svg{width:100%;height:180px;background:var(--theme-bg);border-radius:10px}.workflow-card small{color:var(--theme-text-muted)}
</style>
