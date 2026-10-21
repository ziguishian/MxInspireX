<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { X } from 'lucide-vue-next';
import XiaojuAvatar from './XiaojuAvatar.vue';

const emit = defineEmits<{ close: [] }>();
let timer: ReturnType<typeof setTimeout>;
const colors = ['#d6ff4b', '#88b79d', '#f2c779', '#f2ede0'];
const particles = Array.from({ length: 36 }, (_, index) => ({
  '--x': `${Math.cos(index * 2.4) * (150 + index % 5 * 35)}px`,
  '--y': `${Math.sin(index * 2.4) * 120 + 200}px`,
  '--turn': `${index % 2 ? -260 : 300}deg`,
  '--delay': `${index % 6 * 35}ms`,
  '--color': colors[index % colors.length],
}));
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') emit('close'); }
onMounted(() => {
  timer = setTimeout(() => emit('close'), 6000);
  window.addEventListener('keydown', onKeydown);
});
onUnmounted(() => {
  clearTimeout(timer);
  window.removeEventListener('keydown', onKeydown);
});
</script>

<template>
  <div class="first-request-celebration">
    <div class="first-request-confetti" aria-hidden="true">
      <i v-for="(particle, index) in particles" :key="index" :style="particle" />
    </div>
    <section class="first-request-card" role="status" aria-live="polite" aria-atomic="true">
      <button type="button" class="first-request-close" aria-label="关闭首次请求彩蛋" @click="emit('close')"><X :size="16" /></button>
      <span class="first-request-avatar" aria-hidden="true"><XiaojuAvatar class="large" state="completed" /></span>
      <p class="first-request-eyebrow">你好，灵感搭档</p>
      <h2>第一份灵感，MxinspireX收到了</h2>
      <p>接下来，一起把想法变成作品。</p>
      <span class="first-request-signature"><span />我们的创作，从这里开始</span>
    </section>
  </div>
</template>

<style scoped>
.first-request-celebration { position: fixed; z-index: 120; top: clamp(88px, 15vh, 160px); left: 50%; width: min(390px, calc(100vw - 32px)); transform: translateX(-50%); pointer-events: none; }
.first-request-card { position: relative; display: grid; justify-items: center; padding: 30px 22px 25px; border: 1px solid #888888; border-radius: 24px; background: radial-gradient(ellipse at top, #3b3b3b, #1e1e1e 75%); color: #f3f3f3; box-shadow: 0 20px 80px #0005, 0 0 60px #cbcbcb20; text-align: center; pointer-events: auto; animation: first-request-arrive .5s ease-out both; }
.first-request-close { position: absolute; top: 12px; right: 12px; display: grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: 50%; background: transparent; color: #bebebe; cursor: pointer; }
.first-request-close:hover { background: #ffffff12; }
.first-request-close:focus-visible { outline: 2px solid #e9e9e9; outline-offset: 2px; }
.first-request-avatar { display: grid; place-items: center; width: 94px; height: 94px; border: 1px solid #9e9e9e70; border-radius: 50%; background: #e9e9e90a; box-shadow: 0 0 0 9px #e9e9e904; }
.first-request-eyebrow { margin: 22px 0 10px; color: #dadada; font-size: 11px; letter-spacing: .2em; }
.first-request-card h2 { margin: 0; font-size: clamp(18px, 4.8vw, 22px); line-height: 1.5; font-weight: 600; }
.first-request-card h2 + p { margin: 10px 0 24px; color: #bebebe; font-size: 13px; }
.first-request-signature { display: inline-flex; align-items: center; gap: 7px; color: #a0a0a0; font-size: 10px; }
.first-request-signature > span { width: 4px; height: 4px; border-radius: 50%; background: currentColor; }
.first-request-confetti { position: absolute; z-index: 1; top: 70px; left: 50%; pointer-events: none; }
.first-request-confetti i { position: absolute; width: 6px; height: 11px; border-radius: 2px; background: var(--color); opacity: 0; animation: first-request-burst 1.9s cubic-bezier(.16,.7,.4,1) var(--delay) both; }
.first-request-confetti i:nth-child(3n) { width: 7px; height: 7px; border-radius: 50%; }
@keyframes first-request-arrive { from { opacity: 0; transform: translateY(15px) scale(.96); } to { opacity: 1; transform: none; } }
@keyframes first-request-burst { 0% { opacity: 0; transform: translate(0, 0) rotate(0deg); } 10% { opacity: 1; } 75% { opacity: 1; } 100% { opacity: 0; transform: translate(var(--x), var(--y)) rotate(var(--turn)); } }
:global(html[data-theme="light"] .first-request-card) { border-color: #c4c4c4; background: radial-gradient(ellipse at top, #f1f1f1, #fbfbfb 75%); color: #373737; box-shadow: 0 20px 65px #3e3e3e22; }
:global(html[data-theme="light"] .first-request-close), :global(html[data-theme="light"] .first-request-card h2 + p) { color: #686868; }
:global(html[data-theme="light"] .first-request-eyebrow), :global(html[data-theme="light"] .first-request-signature) { color: #6f6f6f; }
@media (prefers-reduced-motion: reduce) { .first-request-confetti { display: none; } .first-request-card { animation: none; } }
</style>
