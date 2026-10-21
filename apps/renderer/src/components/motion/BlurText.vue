<script setup lang="ts">
// Vue Bits BlurText treatment, adapted to whole Chinese phrases and native Web Animations.
import { onMounted, ref } from 'vue';
import { claimEntrance, motionTiming, useMotion } from '../../features/motion/useMotion';
const props = withDefaults(defineProps<{ text: string; as?: string; onceKey?: string }>(), { as: 'span' });
const root = ref<HTMLElement | null>(null);
const { play } = useMotion();
onMounted(() => {
  if (props.onceKey && !claimEntrance(props.onceKey)) return;
  play(root.value, [{ opacity: .4, filter:'blur(5px)', translate:'0 6px' }, { opacity:1, filter:'blur(0px)', translate:'0 0' }], { duration:motionTiming.entrance });
});
</script>
<template><component :is="as" ref="root">{{ text }}</component></template>
