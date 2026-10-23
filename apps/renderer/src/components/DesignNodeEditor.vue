<script setup lang="ts">
import { ref, watch } from 'vue';
import { designNodeText, type Shot } from '../features/designNodes';
const props = defineProps<{ data: Record<string, any>; busy?: boolean }>();
const emit = defineEmits<{ update: [patch: Record<string, any>] }>();
const colors = ref<string[]>([]), shots = ref<Shot[]>([]);
watch(() => [props.data.colors, props.data.shots], () => { colors.value = [...(props.data.colors || [])]; shots.value = (props.data.shots || []).map((s: Shot) => ({...s})); }, {immediate:true});
function save() { const data = {...props.data, colors:colors.value, shots:shots.value}; emit('update', {colors:[...colors.value], shots:shots.value.map(s=>({...s})), text:designNodeText(data), draft:false}); }
</script>
<template>
  <div class="design-node-editor nodrag nopan nowheel" @pointerdown.stop @click.stop @keydown.stop>
    <fieldset :disabled="busy">
      <template v-if="data.editor === 'palette'">
        <div v-for="(color,i) in colors" :key="i" class="color-row"><input v-model="colors[i]" type="color" :aria-label="`颜色 ${i+1}`" @change="save"><span>{{ color.toUpperCase() }}</span><button :disabled="colors.length <= 1" @click="colors.splice(i,1);save()">删除</button></div>
        <button :disabled="colors.length >= 8" @click="colors.push('#808080');save()">添加颜色</button>
        <small>连接到生成节点，作为主色、辅助色和点缀色。</small>
      </template>
      <template v-else>
        <div v-for="(shot,i) in shots" :key="i" class="shot-row">
          <header>镜头 {{ i+1 }} <button :disabled="i===0" @click="[shots[i-1],shots[i]]=[shots[i],shots[i-1]];save()">上移</button><button :disabled="shots.length<=1" @click="shots.splice(i,1);save()">删除</button></header>
          <textarea v-model="shot.description" aria-label="镜头画面描述" placeholder="描述这个镜头的画面" maxlength="1200" @change="save" />
          <label>时长（秒）<input v-model.number="shot.duration" type="number" min="1" max="30" @change="save"></label>
          <input v-model="shot.camera" aria-label="运镜" placeholder="运镜，例如缓慢推近" maxlength="150" @change="save">
        </div>
        <button :disabled="shots.length >= 12" @click="shots.push({description:'',duration:3,camera:''});save()">添加镜头</button>
        <small>合计 {{ shots.reduce((n,s)=>n+Number(s.duration||0),0) }} 秒。连接视频节点后按分镜生成一条视频；实际镜头遵循程度取决于模型。</small>
      </template>
    </fieldset>
  </div>
</template>
<style scoped>
.design-node-editor { padding:16px; max-height:540px; overflow:auto; width:100%; box-sizing:border-box; background:var(--theme-surface); }
fieldset { border:0; padding:0; margin:0; display:grid; gap:12px; min-width:0; }
.color-row, header, label { display:flex; align-items:center; gap:8px; }
button,input,textarea { color:var(--theme-text); background:var(--theme-input); border:1px solid var(--theme-border); border-radius:6px; padding:6px; font:inherit; }
button { cursor:pointer; } button:disabled { opacity:.4; cursor:default; }
input[type=color] { width:44px; height:32px; padding:2px; } input[type=number] { width:70px; }
.shot-row { display:grid; gap:8px; border-bottom:1px solid var(--theme-border); padding-bottom:12px; }
textarea { resize:vertical; min-height:70px; } small { color:var(--theme-text-muted); line-height:1.5; }
</style>
