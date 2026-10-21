<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { disposeModel, fitModelCamera, loadGlb, type CadView } from '../features/cadViewer';
const props = defineProps<{ label?: string; assetUrl?: string; assetFormat?: string }>();
const emit = defineEmits<{ loaded: []; error: [message: string] }>();
const host = ref<HTMLDivElement | null>(null), loading = ref(false), error = ref('');
let renderer: THREE.WebGLRenderer | undefined, scene: THREE.Scene, camera: THREE.PerspectiveCamera, controls: OrbitControls;
let model: THREE.Object3D | undefined, resize: ResizeObserver | undefined, controller: AbortController | undefined;
let view: CadView = 'iso';
const draw = () => { if (renderer && scene && camera) renderer.render(scene, camera); };
function fit(next: CadView = view) {
  view = next;
  if (!model || !host.value) return;
  const target = fitModelCamera(camera, model, Math.max(host.value.clientWidth, 1) / Math.max(host.value.clientHeight, 1), view);
  controls.target.copy(target); controls.update(); draw();
}
async function load() {
  if (!renderer) return;
  controller?.abort(); const request = new AbortController(); controller = request;
  if (model) { scene.remove(model); disposeModel(model); model = undefined; }
  error.value = ''; loading.value = Boolean(props.assetUrl); draw();
  if (!props.assetUrl) return;
  try {
    let object: THREE.Object3D;
    const format = props.assetFormat?.toLowerCase() || 'glb';
    if (['glb', 'gltf'].includes(format)) object = await loadGlb(props.assetUrl, request.signal);
    else {
      const response = await fetch(props.assetUrl, { signal: request.signal });
      if (!response.ok) throw new Error('模型文件无法读取');
      if (format === 'stl') {
        const { STLLoader } = await import('three/examples/jsm/loaders/STLLoader.js');
        object = new THREE.Mesh(new STLLoader().parse(await response.arrayBuffer()), new THREE.MeshStandardMaterial({ color: 0x8099b5 }));
      } else if (format === 'obj') {
        const { OBJLoader } = await import('three/examples/jsm/loaders/OBJLoader.js'); object = new OBJLoader().parse(await response.text());
      } else if (format === 'fbx') {
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js'); object = new FBXLoader().parse(await response.arrayBuffer(), '');
      } else throw new Error('暂不支持此预览格式');
    }
    if (request.signal.aborted) { disposeModel(object); return; }
    model = object; scene.add(object); fit(); emit('loaded');
  } catch (reason) { if (!request.signal.aborted) { error.value = reason instanceof Error ? reason.message : '模型加载失败'; emit('error', error.value); } }
  finally { if (!request.signal.aborted) loading.value = false; }
}
onMounted(() => {
  if (!host.value) return;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    host.value.append(renderer.domElement);
    scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(35, 1);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x505566, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 2); light.position.set(3, 5, 4); scene.add(light);
    controls = new OrbitControls(camera, renderer.domElement); controls.addEventListener('change', draw);
    resize = new ResizeObserver(() => { if (host.value && renderer) { renderer.setSize(host.value.clientWidth, host.value.clientHeight); fit(); } }); resize.observe(host.value);
    void load();
  } catch { error.value = '无法启动 3D 预览，请检查图形加速'; emit('error', error.value); }
});
watch(() => [props.assetUrl, props.assetFormat], load);
onBeforeUnmount(() => { controller?.abort(); resize?.disconnect(); controls?.dispose(); if (model) disposeModel(model); renderer?.dispose(); renderer?.forceContextLoss(); });
</script>
<template>
  <div class="cad-model-viewer nodrag nopan nowheel" @pointerdown.stop @click.stop @wheel.stop>
    <div ref="host" class="cad-model-viewport" :aria-label="label || '模型预览'" />
    <div v-if="loading || error || !assetUrl" class="cad-viewer-status" role="status">{{ error || (loading ? '正在加载模型…' : '模型尚未生成') }}</div>
    <div v-if="assetUrl && !error && !loading" class="cad-viewer-controls">
      <button v-for="(label, key) in { iso: '立体', front: '正面', top: '顶面', right: '右面' }" :key="key" type="button" @click="fit(key)">{{ label }}</button>
    </div>
  </div>
</template>
<style scoped>
.cad-model-viewer{position:relative;width:100%;height:100%;min-height:150px;background:#f2f2f2;color:#323232;border-radius:inherit;overflow:hidden}
.cad-model-viewport{position:absolute;inset:0}.cad-model-viewport :deep(canvas){display:block;width:100%;height:100%}
.cad-viewer-status{position:absolute;inset:0;display:grid;place-items:center;padding:18px;font-size:12px;text-align:center}
.cad-viewer-controls{position:absolute;bottom:8px;left:8px;display:flex;gap:4px}.cad-viewer-controls button{font:inherit;font-size:11px;border:1px solid #d2d2d2;border-radius:5px;background:#ffffffdf;color:#323232;padding:4px 8px;cursor:pointer}
</style>
