<script setup lang="ts">
// Vue Bits AnimatedList interaction, using Vue's keyed FLIP transitions and normal tab order.
import { onMounted, ref, type ComponentPublicInstance } from 'vue';
import { useMotion } from '../../features/motion/useMotion';
withDefaults(defineProps<{ as?: string }>(), { as:'div' });
const group = ref<ComponentPublicInstance | null>(null);
const { enabled, play } = useMotion();
onMounted(() => {
  const root = group.value?.$el as HTMLElement | undefined;
  Array.from(root?.children ?? []).forEach((child, index) => {
    play(child, [{ opacity:0, translate:'0 8px' }, { opacity:1, translate:'0 0' }], { delay:Math.min(index * 25, 90) });
  });
});
</script>
<template><TransitionGroup ref="group" :tag="as" name="mx-list" :css="enabled" class="mx-animated-list"><slot /></TransitionGroup></template>
