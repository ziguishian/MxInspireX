import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRenderer, defineComponent, h } from 'vue';
import { claimEntrance, useMotion } from './useMotion';

// A Vue host tests lifecycle/timing without introducing a browser simulator dependency.
type Host = { children: Host[]; parent: Host | null; text: string; props: Record<string, unknown> };
const node = (): Host => ({ children: [], parent: null, text: '', props: {} });
const renderer = createRenderer<Host, Host>({
  createElement: node, createComment: node,
  createText: text => ({ ...node(), text }),
  setText: (n, text) => { n.text = text; }, setElementText: (n, text) => { n.text = text; },
  patchProp: (n, key, _before, value) => { n.props[key] = value; },
  parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
  insert: (n, parent, anchor) => { n.parent = parent; parent.children.splice(anchor ? parent.children.indexOf(anchor) : parent.children.length, 0, n); },
  remove: n => { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); },
});
let query: { matches: boolean; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
let doc: { hidden: boolean; documentElement: { dataset: Record<string, string> }; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
let updates: (() => void)[], disconnects: ReturnType<typeof vi.fn>[];
const cleanups: (() => void)[] = [];
function mountMotion() {
  let motion!: ReturnType<typeof useMotion>;
  const app = renderer.createApp(defineComponent({ setup() { motion = useMotion(); return () => h('div'); } }));
  app.mount(node()); cleanups.push(() => app.unmount()); return motion;
}
function animatedElement() {
  const animation = { cancel: vi.fn(), onfinish: null, oncancel: null };
  const animate = vi.fn(() => animation as unknown as Animation);
  return { element: { animate } as unknown as Element, animate, animation };
}
beforeEach(() => {
  updates = []; disconnects = [];
  query = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  doc = { hidden: false, documentElement: { dataset: {} }, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  vi.stubGlobal('window', { matchMedia: vi.fn(() => query) }); vi.stubGlobal('document', doc);
  vi.stubGlobal('MutationObserver', class { disconnect = vi.fn(); observe = vi.fn(); constructor(update: () => void) { updates.push(update); disconnects.push(this.disconnect); } });
});
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('shared motion lifecycle', () => {
  it('shares one observer and releases listeners only when the final consumer leaves', () => {
    mountMotion(); mountMotion();
    expect(updates).toHaveLength(1); expect(query.addEventListener).toHaveBeenCalledTimes(1);
    cleanups.shift()!(); expect(disconnects[0]).not.toHaveBeenCalled();
    cleanups.shift()!(); expect(disconnects[0]).toHaveBeenCalledOnce();
    expect(query.removeEventListener).toHaveBeenCalledOnce(); expect(doc.removeEventListener).toHaveBeenCalledOnce();
    expect(doc.documentElement.dataset.motionPaused).toBeUndefined();
  });
  it.each(['app', 'os', 'hidden'])('stops running animations for %s and does not replay them when enabled', mode => {
    const motion = mountMotion(), item = animatedElement(); motion.play(item.element, []);
    if (mode === 'app') doc.documentElement.dataset.reduceAnimations = 'true';
    if (mode === 'os') query.matches = true;
    if (mode === 'hidden') doc.hidden = true;
    updates[0]!();
    expect(motion.enabled.value).toBe(false); expect(item.animation.cancel).toHaveBeenCalledOnce();
    motion.play(item.element, []); expect(item.animate).toHaveBeenCalledTimes(1);
    doc.documentElement.dataset.reduceAnimations = 'false'; query.matches = false; doc.hidden = false; updates[0]!();
    expect(motion.enabled.value).toBe(true); expect(item.animate).toHaveBeenCalledTimes(1);
  });
  it('cancels replaced animations and cancels remaining animations on navigation', () => {
    const motion = mountMotion(), item = animatedElement(); motion.play(item.element, []); motion.play(item.element, []);
    expect(item.animation.cancel).toHaveBeenCalledTimes(1);
    cleanups.shift()!(); expect(item.animation.cancel).toHaveBeenCalledTimes(2);
  });
  it('claims homepage entrances once per session', () => {
    expect(claimEntrance('test-home')).toBe(true); expect(claimEntrance('test-home')).toBe(false);
  });
});

