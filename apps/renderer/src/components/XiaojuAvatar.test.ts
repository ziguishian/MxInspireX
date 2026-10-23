import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it } from 'vitest';
import XiaojuAvatar from './XiaojuAvatar.vue';
import FirstRequestCelebration from './FirstRequestCelebration.vue';
import { createMascotSettings, mascotPresets, mascotSettingsKey, type MascotGeneration } from '../features/home/mascot';

const custom: MascotGeneration = { id: 'aa', prompt: '自定义角色', status: 'succeeded', model: 'image', imageUrl: '/api/mascot/generations/aa/image', error: '' };

describe('shared Agent avatar artwork', () => {
  it.each(mascotPresets)('uses $name for project messages and the celebration', async preset => {
    const mascot = createMascotSettings('http://localhost:8765');
    mascot.activePreset.value = preset.id;
    for (const component of [XiaojuAvatar, FirstRequestCelebration]) {
      const app = createSSRApp(component);
      app.provide(mascotSettingsKey, mascot);
      const html = await renderToString(app);
      expect(html).toContain(`assets/${preset.image}`);
      expect(html).toContain(`${preset.name} ·`);
      // Coordinates must reach the shared pseudo-element instead of painting the outer box.
      expect(html).toContain(`--xiaoju-frame-thinking:${preset.positions[1]}`);
      expect(html).not.toContain('background-image:');
      expect(html).not.toContain('mxinspirex-robot-states.png');
    }
  });

  it('uses the applied custom artwork for every task state and restores the default without applying a preview', async () => {
    const mascot = createMascotSettings('http://localhost:8765');
    mascot.active.value = custom;
    mascot.activePreset.value = null;
    mascot.latest.value = custom;
    for (const state of ['idle', 'thinking', 'generating', 'waiting', 'error', 'completed'] as const) {
      const app = createSSRApp(XiaojuAvatar, { state });
      app.provide(mascotSettingsKey, mascot);
      const html = await renderToString(app);
      expect(html).toContain('http://localhost:8765/api/mascot/generations/aa/image');
      expect(html).toContain(`data-state="${state}"`);
      expect(html).toContain('自定义形象 ·');
    }
    mascot.active.value = null;
    mascot.activePreset.value = 'robot';
    const app = createSSRApp(XiaojuAvatar);
    app.provide(mascotSettingsKey, mascot);
    const html = await renderToString(app);
    expect(html).toContain('assets/mascots/robot-soft.png');
    expect(html).not.toContain(custom.imageUrl);
    expect(html).toContain('点阵机器人 ·');
  });

  it('keeps the default avatar available without the app settings provider', async () => {
    const html = await renderToString(createSSRApp(XiaojuAvatar));
    expect(html).toContain('agent-avatar-sprite');
    expect(html).toContain('data-state="idle"');
    expect(html).toContain('assets/mascots/robot-soft.png');
  });
});
