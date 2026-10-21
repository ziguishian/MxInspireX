<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';

type Point = { x: number; y: number };
type Afterglow = Point & { id: number; strength: number };
const glow = ref<HTMLElement | null>(null);
const afterglows = ref<Afterglow[]>([]);
const haloRadius = 196;
const fadeDuration = 1800;
let surface: HTMLElement | null = null;
let pointer: Point | null = null;
let lightPosition: Point | null = null;
let pointerCell: Point | null = null;
let frame: number | null = null;
let lastFrameAt = 0;
let lastTrailAt = 0;
let trailId = 0;
let cellSize = 28;
let reducedMotion: MediaQueryList | null = null;

function leaveAfterglow(position: Point, strength = .4) {
  if (reducedMotion?.matches) return;
  // Retain the diffuse light and grid lines without a separate highlighted square.
  afterglows.value = [...afterglows.value, { ...position, id: ++trailId, strength }].slice(-20);
  lastTrailAt = performance.now();
}

function removeAfterglow(id: number) {
  afterglows.value = afterglows.value.filter(light => light.id !== id);
}

function afterglowStyle(light: Afterglow) {
  // Integer offsets keep the retained grid lines crisp while the halo follows smoothly.
  const left = Math.round(light.x - haloRadius);
  const top = Math.round(light.y - haloRadius);
  return {
    transform: `translate(${left}px, ${top}px)`,
    '--halo-grid-x': `${-left}px`,
    '--halo-grid-y': `${-top}px`,
    '--halo-strength': light.strength,
  };
}

function updateGlow(now: number) {
  frame = null;
  if (!glow.value || !pointer) return;
  // All halo layers share the actual background's origin.
  const bounds = glow.value.getBoundingClientRect();
  const x = pointer.x - bounds.left;
  const y = pointer.y - bounds.top;
  const cell = { x: Math.floor(x / cellSize) * cellSize, y: Math.floor(y / cellSize) * cellSize };
  if (pointerCell?.x !== cell.x || pointerCell?.y !== cell.y) {
    if (pointerCell && lightPosition && now - lastTrailAt >= 90) leaveAfterglow(lightPosition);
    pointerCell = cell;
  }
  const blend = reducedMotion?.matches ? 1 : 1 - Math.exp(-Math.min(now - lastFrameAt, 64) / 65);
  if (!lightPosition) lightPosition = { x, y };
  else {
    lightPosition.x += (x - lightPosition.x) * blend;
    lightPosition.y += (y - lightPosition.y) * blend;
  }
  lastFrameAt = now;
  glow.value.style.setProperty('--grid-pointer-x', `${lightPosition.x}px`);
  glow.value.style.setProperty('--grid-pointer-y', `${lightPosition.y}px`);
  glow.value.classList.add('is-active');
  if (Math.hypot(x - lightPosition.x, y - lightPosition.y) > .1) scheduleGlow();
}

function scheduleGlow() {
  if (pointer && frame === null) frame = window.requestAnimationFrame(updateGlow);
}

function movePointer(event: PointerEvent) {
  if (event.pointerType === 'touch') return;
  if (!pointer) lightPosition = null;
  pointer = { x: event.clientX, y: event.clientY };
  scheduleGlow();
}

function clearGlow() {
  if (pointer && lightPosition) leaveAfterglow(lightPosition, 1);
  pointer = null;
  pointerCell = null;
  if (frame !== null) window.cancelAnimationFrame(frame);
  frame = null;
  glow.value?.classList.remove('is-active');
}

function updateMotionPreference() {
  if (reducedMotion?.matches) afterglows.value = [];
}

onMounted(() => {
  surface = glow.value?.parentElement ?? null;
  if (!surface) return;
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  reducedMotion.addEventListener('change', updateMotionPreference);
  cellSize = parseFloat(getComputedStyle(surface).getPropertyValue('--workspace-grid-size')) || 28;
  surface.addEventListener('pointerenter', movePointer, { passive: true });
  surface.addEventListener('pointermove', movePointer, { passive: true });
  surface.addEventListener('pointerleave', clearGlow);
  surface.addEventListener('pointercancel', clearGlow);
  surface.addEventListener('scroll', scheduleGlow, { passive: true });
  window.addEventListener('resize', scheduleGlow);
  window.addEventListener('blur', clearGlow);
});

onUnmounted(() => {
  if (frame !== null) window.cancelAnimationFrame(frame);
  surface?.removeEventListener('pointerenter', movePointer);
  surface?.removeEventListener('pointermove', movePointer);
  surface?.removeEventListener('pointerleave', clearGlow);
  surface?.removeEventListener('pointercancel', clearGlow);
  surface?.removeEventListener('scroll', scheduleGlow);
  reducedMotion?.removeEventListener('change', updateMotionPreference);
  window.removeEventListener('resize', scheduleGlow);
  window.removeEventListener('blur', clearGlow);
});
</script>

<template>
  <div ref="glow" class="home-grid-glow" :style="{ '--halo-radius': `${haloRadius}px`, '--halo-fade-duration': `${fadeDuration}ms` }" aria-hidden="true">
    <span v-for="light in afterglows" :key="light.id" class="home-grid-afterglow" :style="afterglowStyle(light)" @animationend.self="removeAfterglow(light.id)" />
  </div>
</template>

<style scoped>
.home-grid-glow {
  --halo-line: color-mix(in srgb, var(--theme-accent) 48%, transparent);
  --halo-fill: color-mix(in srgb, var(--theme-accent) 7%, transparent);
  position: absolute;
  inset: 0;
  z-index: -1;
  overflow: hidden;
  pointer-events: none;
  mask-image: var(--workspace-grid-fade);
}
.home-grid-glow::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0;
  background-image:
    linear-gradient(var(--halo-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--halo-line) 1px, transparent 1px),
    radial-gradient(var(--halo-radius) circle at var(--grid-pointer-x, -200px) var(--grid-pointer-y, -200px), var(--halo-fill), transparent);
  background-size: var(--workspace-grid-size) var(--workspace-grid-size), var(--workspace-grid-size) var(--workspace-grid-size), 100% 100%;
  mask-image: radial-gradient(var(--halo-radius) circle at var(--grid-pointer-x, -200px) var(--grid-pointer-y, -200px), #000 0%, rgba(0, 0, 0, .65) 25%, transparent 100%);
}
.home-grid-glow.is-active::before { opacity: 1; }
.home-grid-afterglow {
  position: absolute;
  top: 0;
  left: 0;
  width: calc(var(--halo-radius) * 2);
  height: calc(var(--halo-radius) * 2);
  background-image:
    linear-gradient(var(--halo-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--halo-line) 1px, transparent 1px),
    radial-gradient(circle at center, var(--halo-fill), transparent);
  background-size: var(--workspace-grid-size) var(--workspace-grid-size), var(--workspace-grid-size) var(--workspace-grid-size), 100% 100%;
  background-position: var(--halo-grid-x) var(--halo-grid-y), var(--halo-grid-x) var(--halo-grid-y), center;
  mask-image: radial-gradient(circle closest-side, #000 0%, rgba(0, 0, 0, .65) 25%, transparent 100%);
  animation: grid-halo-fade var(--halo-fade-duration) cubic-bezier(.4, 0, .2, 1) both;
}
@keyframes grid-halo-fade {
  from { opacity: var(--halo-strength); }
  to { opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .home-grid-afterglow { display: none; animation: none; }
}
</style>
