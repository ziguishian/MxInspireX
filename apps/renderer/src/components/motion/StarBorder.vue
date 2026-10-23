<script setup lang="ts">
// Adapted from Vue Bits StarBorder (David Haz). See docs/vue-bits-motion.md and public/licenses/vue-bits.txt.
import { useMotionPolicy } from '../../features/motion/useMotion';
defineProps<{ flowing?: boolean }>();
const { enabled } = useMotionPolicy();
</script>

<template><span class="mx-star-border" :class="{ 'is-motion-enabled': enabled, 'is-flowing': flowing }" aria-hidden="true"><template v-if="!flowing"><i class="mx-star-bottom" /><i class="mx-star-top" /></template></span></template>

<style scoped>
.mx-star-border { position:absolute; inset:-1px; z-index:2; overflow:hidden; padding:1px; border-radius:inherit; pointer-events:none; opacity:0; background:var(--mx-neon-spectrum); -webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0); mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0); -webkit-mask-composite:xor; mask-composite:exclude; transition:opacity var(--ui-motion-standard) var(--ui-motion-ease); }
.mx-star-border i { position:absolute; width:300%; height:70%; border-radius:50%; opacity:.85; animation:mx-star-bottom 6s linear infinite alternate; animation-play-state:paused; }
.mx-star-bottom { bottom:-10px; right:-250%; background:radial-gradient(ellipse,#73e8ef 0%,#b399ff 12%,transparent 36%); }
.mx-star-border .mx-star-top { top:-10px; left:-250%; background:radial-gradient(ellipse,#efa5d4 0%,#9baaff 12%,transparent 36%); animation-name:mx-star-top; }
.composer-hero:focus-within > .mx-star-border { opacity:.92; }
.composer-hero:focus-within > .mx-star-border.is-motion-enabled i { animation-play-state:running; }
@keyframes mx-star-bottom { from { transform:translateX(0); } to { transform:translateX(-100%); } }
@keyframes mx-star-top { from { transform:translateX(0); } to { transform:translateX(100%); } }
@property --mx-flow-angle { syntax:'<angle>'; initial-value:0deg; inherits:false; }
.mx-star-border.is-flowing {
  background:var(--mx-flow-base, #b7cbd226);
  transition:opacity 320ms ease;
}
.mx-star-border.is-flowing::before {
  content:''; position:absolute; inset:0;
  background:conic-gradient(from var(--mx-flow-angle), transparent 0deg 225deg, var(--mx-flow-tail, #8db6c73d) 275deg, var(--mx-flow-tip, #e4f4f9c7) 310deg, transparent 335deg 360deg);
  animation:mx-edge-flow 7s linear infinite;
  animation-play-state:paused;
  opacity:0;
}
.composer-hero:focus-within > .mx-star-border.is-flowing { opacity:1; }
.composer-hero:focus-within > .mx-star-border.is-flowing.is-motion-enabled::before { opacity:1; animation-play-state:running; }
@keyframes mx-edge-flow { to { --mx-flow-angle:360deg; } }
@media(prefers-reduced-motion:reduce) { .mx-star-border { transition:none; }.mx-star-border i { animation:none; } }
[data-reduce-animations=true] .mx-star-border { transition:none; }
[data-reduce-animations=true] .mx-star-border i { animation:none; }
</style>
