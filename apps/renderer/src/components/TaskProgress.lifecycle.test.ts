import { describe, expect, it, vi } from 'vitest';
import { createRenderer, defineComponent, h, nextTick, reactive, ref } from 'vue';
import * as Vue from 'vue';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc';
import { transpileModule, ScriptTarget } from 'typescript';
import TaskProgress from './TaskProgress.vue';

vi.mock('../features/motion/useMotion', () => ({
  useMotionPolicy: () => ({ enabled: ref(false) }),
  useMotion: () => ({ enabled: ref(false), play: vi.fn() }),
}));
vi.mock('./motion/AnimatedList.vue', () => ({ default: defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }) }));

// Node-mode Vitest supplies SSR templates. Compile the real client template
// against the existing Vue host so transition updates are actually exercised.
const filename = fileURLToPath(new URL('./TaskProgress.vue', import.meta.url));
const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename });
const script = compileScript(descriptor, { id: 'task-progress-test' });
const template = compileTemplate({ source: descriptor.template!.content, filename, id: 'task-progress-test',
  compilerOptions: { bindingMetadata: script.bindings } });
const clientCode = template.code.replace(/import \{([^}]+)\} from "vue"/g, (_, names: string) =>
  `const {${names.replace(/\s+as\s+/g, ':')}} = Vue`).replace('export function render', 'return function render');
TaskProgress.render = new Function('Vue', transpileModule(clientCode, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText)(Vue);

type Host = { children: Host[]; parent: Host | null; text: string; props: Record<string, unknown> };
const node = (): Host => ({ children: [], parent: null, text: '', props: {} });
const detach = (n: Host) => { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null; };
const renderer = createRenderer<Host, Host>({
  createElement: node, createComment: node, createText: text => ({ ...node(), text }),
  setText: (n, text) => { n.text = text; }, setElementText: (n, text) => { n.text = text; n.children = []; },
  patchProp: (n, key, _old, value) => { n.props[key] = value; },
  parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
  insert: (n, parent, anchor) => { detach(n); n.parent = parent; parent.children.splice(anchor ? parent.children.indexOf(anchor) : parent.children.length, 0, n); },
  remove: detach,
});
function find(root: Host, className: string): Host | undefined {
  if (String(root.props.class || '').split(' ').includes(className)) return root;
  for (const child of root.children) { const match = find(child, className); if (match) return match; }
}

describe('task progress lifecycle', () => {
  it('keeps the status label mounted when a background task fails and updates again', async () => {
    const state = reactive({ status: 'running', visible: true });
    const root = node(), errors: unknown[] = [];
    const app = renderer.createApp(defineComponent({ setup: () => () => state.visible
      ? h(TaskProgress, { info: {}, status: state.status }) : null }));
    app.config.errorHandler = error => errors.push(error);
    app.provide(Vue.ssrContextKey, { modules: new Set() });
    app.mount(root);
    try {
      const label = find(root, 'task-progress-label');
      expect(label).toBeDefined();
      for (const status of ['failed', 'failed', 'running', 'cancelled', 'succeeded']) {
        state.status = status;
        await nextTick();
        expect(errors).toEqual([]);
        expect(find(root, 'task-progress-label')).toBe(label);
        expect(label?.text).not.toBe('');
      }
      state.visible = false;
      await nextTick();
      expect(errors).toEqual([]);
    } finally { app.unmount(); }
  });
});
