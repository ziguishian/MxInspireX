<script setup lang="ts">
import { Award, X } from 'lucide-vue-next';

defineProps<{ title: string; description: string; imageGenerationCount: number }>();
const emit = defineEmits<{ close: [] }>();

const colors = ['#d6ff4b', '#f3d27a', '#8bc7a6', '#f7f3e7'];
const particles = Array.from({ length: 42 }, (_, index) => ({
  '--x': `${Math.cos(index * 2.18) * (145 + index % 6 * 28)}px`,
  '--y': `${Math.sin(index * 2.18) * 118 + 185}px`,
  '--turn': `${index % 2 ? -240 : 320}deg`,
  '--delay': `${index % 7 * 35}ms`,
  '--color': colors[index % colors.length],
}));
</script>

<template>
  <div class="achievement-celebration">
    <div class="achievement-confetti" aria-hidden="true"><i v-for="(particle, index) in particles" :key="index" :style="particle" /></div>
    <section class="achievement-card" role="dialog" aria-modal="true" aria-labelledby="achievement-title">
      <button type="button" class="achievement-close" aria-label="收下成就" @click="emit('close')"><X :size="16" /></button>
      <span class="achievement-icon" aria-hidden="true"><Award :size="34" :stroke-width="1.5" /></span>
      <p class="achievement-eyebrow">ACHIEVEMENT UNLOCKED</p>
      <strong class="achievement-number">100</strong>
      <h2 id="achievement-title">{{ title }}</h2>
      <p>{{ description }}</p>
      <small>第 100 张不是终点，是视觉语言开始成形。</small>
      <button type="button" class="achievement-claim" @click="emit('close')">收下成就</button>
    </section>
  </div>
</template>

<style scoped>
.achievement-celebration { position:fixed; z-index:130; inset:0; display:grid; place-items:center; padding:24px; background:#05080680; backdrop-filter:blur(5px); }
.achievement-card { position:relative; z-index:2; display:grid; justify-items:center; width:min(420px, calc(100vw - 32px)); padding:32px 30px 28px; border:1px solid #acacac; border-radius:28px; overflow:hidden; background:radial-gradient(circle at 50% 0, #494949, #1e1e1e 62%, #151515); color:#f6f6f6; box-shadow:0 30px 100px #0009, 0 0 80px #dadada20; text-align:center; animation:achievement-arrive .52s cubic-bezier(.2,.8,.2,1) both; }
.achievement-card::before { content:''; position:absolute; inset:0; background:linear-gradient(120deg, transparent 15%, #efefef50 48%, transparent 58%); transform:translateX(-120%); animation:achievement-shine 1.1s .25s ease-out both; pointer-events:none; }
.achievement-close { position:absolute; z-index:2; top:13px; right:13px; display:grid; place-items:center; width:32px; height:32px; border:0; border-radius:50%; background:transparent; color:#c0c0c0; cursor:pointer; }
.achievement-close:hover { background:#ffffff12; }
.achievement-icon { display:grid; place-items:center; width:70px; height:70px; border:1px solid #e9e9e980; border-radius:50%; color:#e9e9e9; background:#e9e9e90d; box-shadow:0 0 0 10px #e9e9e905; }
.achievement-eyebrow { margin:22px 0 5px; color:#dcdcdc; font-size:10px; letter-spacing:.22em; }
.achievement-number { color:#f7f7f7; font-size:clamp(52px, 12vw, 72px); line-height:1; font-weight:700; letter-spacing:-.06em; text-shadow:0 0 28px #e9e9e936; }
.achievement-card h2 { margin:7px 0 8px; font-size:23px; font-weight:600; }
.achievement-card h2 + p { margin:0; color:#cecece; font-size:13px; line-height:1.7; }
.achievement-card small { margin-top:7px; color:#9b9b9b; font-size:11px; line-height:1.6; }
.achievement-claim { margin-top:23px; padding:10px 22px; border:1px solid #e9e9e988; border-radius:999px; background:#e9e9e9; color:#1d1d1d; font:inherit; font-size:12px; font-weight:650; cursor:pointer; }
.achievement-claim:hover { filter:brightness(1.06); }
.achievement-confetti { position:fixed; z-index:1; top:42%; left:50%; pointer-events:none; }
.achievement-confetti i { position:absolute; width:7px; height:12px; border-radius:2px; background:var(--color); opacity:0; animation:achievement-burst 2.1s cubic-bezier(.16,.7,.4,1) var(--delay) both; }
.achievement-confetti i:nth-child(3n) { width:8px; height:8px; border-radius:50%; }
@keyframes achievement-arrive { from { opacity:0; transform:translateY(18px) scale(.94); } to { opacity:1; transform:none; } }
@keyframes achievement-shine { to { transform:translateX(130%); } }
@keyframes achievement-burst { 0% { opacity:0; transform:translate(0,0) rotate(0); } 12%,72% { opacity:1; } 100% { opacity:0; transform:translate(var(--x),var(--y)) rotate(var(--turn)); } }
:global(html[data-theme="light"] .achievement-celebration) { background:#f2f2f299; }
:global(html[data-theme="light"] .achievement-card) { border-color:#b3b3b3; background:radial-gradient(circle at 50% 0, #eeeeee, #fbfbfb 68%); color:#373737; box-shadow:0 30px 90px #3a3a3a35; }
:global(html[data-theme="light"] .achievement-card h2 + p) { color:#646464; }
:global(html[data-theme="light"] .achievement-card small) { color:#7b7b7b; }
@media (prefers-reduced-motion:reduce) { .achievement-card, .achievement-card::before { animation:none; } .achievement-confetti { display:none; } }
</style>
