import { test } from 'vitest';
import assert from 'node:assert/strict';
import { assertReleaseNotRunning, runningReleaseProcesses } from './package-guard.mjs';

test('blocks replacing a running app or its surviving sidecar, including spaces in paths', () => {
  const root = '/tmp/Design App/dist/release';
  const list = `123 ${root}/朗居设计Agent.app/Contents/MacOS/LangjuAgent\n124 ${root}/朗居设计Agent.app/Contents/Resources/app/services/api/sidecar/aics-api/aics-api`;
  assert.deepEqual(runningReleaseProcesses(root, list).map(p => p.pid), [123, 124]);
  assert.throws(() => assertReleaseNotRunning(root, () => list), /先退出应用/);
  assert.throws(() => assertReleaseNotRunning(root, () => list.split('\n')[1]), /124/);
});

test('allows independent development processes and refuses an unreadable process list', () => {
  assert.doesNotThrow(() => assertReleaseNotRunning('/tmp/project/dist/release', () => '123 /tmp/project/dist/dev/LangjuAgent\n124 /tmp/project/dist/release-other/App'));
  assert.throws(() => assertReleaseNotRunning('/tmp/project/dist/release', () => { throw new Error('permission'); }), /已停止覆盖/);
});
