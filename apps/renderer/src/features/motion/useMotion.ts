import { computed, onMounted, onScopeDispose, ref, watch } from 'vue';

const reduced = ref(true);
const visible = ref(true);
let consumers = 0;
let stopObserving: (() => void) | undefined;
const played = new Set<string>();

/** One observer shared by all cards; app preference and OS preference both win. */
export function useMotionPolicy() {
  const mounted = ref(false);
  onMounted(() => {
    if (++consumers === 1) {
      const query = window.matchMedia('(prefers-reduced-motion: reduce)');
      const update = () => {
        reduced.value = query.matches || document.documentElement.dataset.reduceAnimations === 'true';
        visible.value = !document.hidden;
        document.documentElement.dataset.motionPaused = String(document.hidden);
      };
      const observer = new MutationObserver(update);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-animations'] });
      query.addEventListener('change', update);
      document.addEventListener('visibilitychange', update);
      update();
      stopObserving = () => {
        observer.disconnect();
        query.removeEventListener('change', update);
        document.removeEventListener('visibilitychange', update);
        delete document.documentElement.dataset.motionPaused;
      };
    }
    mounted.value = true;
  });
  onScopeDispose(() => {
    if (mounted.value && --consumers === 0) { stopObserving?.(); stopObserving = undefined; }
  });
  return { enabled: computed(() => mounted.value && !reduced.value && visible.value) };
}

export function claimEntrance(key: string) {
  if (played.has(key)) return false;
  played.add(key);
  return true;
}

export const motionTiming = { quick: 140, standard: 220, entrance: 400, ease: 'cubic-bezier(.22,.68,0,1)' };

/** Native animations have no retained inline transforms and are cancelled on navigation. */
export function useMotion() {
  const { enabled } = useMotionPolicy();
  const animations = new Map<Element, Animation>();
  const cancel = () => { animations.forEach(animation => animation.cancel()); animations.clear(); };
  watch(enabled, value => { if (!value) cancel(); }, { flush: 'sync' });
  onScopeDispose(cancel);
  function play(element: Element | null | undefined, frames: Keyframe[], options: KeyframeAnimationOptions = {}) {
    if (!element || !enabled.value || typeof element.animate !== 'function') return;
    animations.get(element)?.cancel();
    const animation = element.animate(frames, { duration: motionTiming.standard, easing: motionTiming.ease, ...options });
    animations.set(element, animation);
    animation.onfinish = animation.oncancel = () => { if (animations.get(element) === animation) animations.delete(element); };
    return animation;
  }
  return { enabled, play, cancel };
}
