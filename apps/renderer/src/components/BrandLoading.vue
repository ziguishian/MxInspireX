<script setup lang="ts">
import { useId } from 'vue';
import { useMotionPolicy } from '../features/motion/useMotion';
withDefaults(defineProps<{ label?: string; fullscreen?: boolean }>(), { label: '正在加载…', fullscreen: false });
const { enabled } = useMotionPolicy();
const outlineId = `loading-outline-${useId()}`;
const logo = `${import.meta.env.BASE_URL}assets/mxinspirex-app-icon-dark.png`;
const mask = `url("${import.meta.env.BASE_URL}assets/mxinspirex-app-icon-dark.png")`;
</script>

<template>
  <div class="brand-loading" :class="{ 'brand-loading--fullscreen': fullscreen, 'is-animated': enabled }" role="status" :aria-label="label">
    <div class="brand-loading-mark" :style="{ '--brand-mask': mask }" aria-hidden="true">
      <svg class="brand-loading-outline" viewBox="0 0 200 200" focusable="false">
        <defs>
          <filter :id="outlineId" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
            <feMorphology in="SourceAlpha" operator="dilate" radius=".65" result="expanded" />
            <feComposite in="expanded" in2="SourceAlpha" operator="out" result="edge" />
            <feFlood flood-color="#909090" flood-opacity=".65" />
            <feComposite in2="edge" operator="in" />
          </filter>
        </defs>
        <image :href="logo" width="200" height="200" :filter="`url(#${outlineId})`" />
      </svg>
      <div class="brand-loading-liquid">
        <svg viewBox="0 0 200 200" focusable="false">
          <g class="brand-loading-rise">
            <path class="brand-loading-wave back" d="M-200 0 Q-175 -9 -150 0 T-100 0 T-50 0 T0 0 T50 0 T100 0 T150 0 T200 0 T250 0 T300 0 T350 0 T400 0 V240 H-200Z" />
            <path class="brand-loading-wave front" d="M-200 0 Q-175 -7 -150 0 T-100 0 T-50 0 T0 0 T50 0 T100 0 T150 0 T200 0 T250 0 T300 0 T350 0 T400 0 V240 H-200Z" />
          </g>
        </svg>
      </div>
    </div>
    <span class="brand-loading-label">{{ label }}</span>
  </div>
</template>

<style scoped>
.brand-loading { display: grid; justify-items: center; align-content: center; gap: 4px; padding: 24px; color: var(--theme-text-muted, #888); }
.brand-loading--fullscreen { min-height: 100dvh; background: var(--theme-bg, #181818); box-sizing: border-box; }
.brand-loading-mark { position: relative; width: 128px; height: 128px; --liquid-color: #fff; }
.brand-loading-outline { position: absolute; inset: 0; width: 100%; height: 100%; }
.brand-loading-liquid { position: absolute; inset: 0; mask: var(--brand-mask) center / 100% 100% no-repeat; -webkit-mask: var(--brand-mask) center / 100% 100% no-repeat; }
.brand-loading-liquid svg { width: 100%; height: 100%; overflow: hidden; }
.brand-loading-rise { transform: translateY(100px); }
.brand-loading-wave { fill: var(--liquid-color); }
.back { opacity: .4; }
.brand-loading-label { font-size: 12px; }
.is-animated .brand-loading-rise { animation: liquid-rise 4s linear infinite; }
.is-animated .front { animation: liquid-wave 1.8s linear infinite; }
.is-animated .back { animation: liquid-wave 2.6s linear infinite reverse; }
@keyframes liquid-wave { to { transform: translateX(100px); } }
@keyframes liquid-rise { 0%, 8% { transform: translateY(154px); opacity: 1; } 80%, 90% { transform: translateY(42px); opacity: 1; } 100% { transform: translateY(42px); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .brand-loading * { animation: none !important; } }
</style>
