import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
export function sessionResponse(url, options) {
  if (String(url).match(/\/tasks\/[^/]+\/updates(?:\/acknowledge)?$/)) return Response.json([]);
  if (!String(url).endsWith('/agent-session')) return;
  const taskId = options.headers['x-aics-task-id'];
  const projectId = decodeURIComponent(new URL(url).pathname.split('/')[3]);
  const result = spawnSync(process.env.FIXTURE_PYTHON, [fileURLToPath(new URL('./session_fixture.py', import.meta.url))], {
    input:JSON.stringify({projectId,taskId,payload:JSON.parse(options.body)}),encoding:'utf8',env:process.env,
  });
  assert.equal(result.status,0,result.stderr);
  return Response.json(JSON.parse(result.stdout));
}
