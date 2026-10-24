import {expect, it} from 'vitest';
import {webMediaAllowed} from '../app/web_generation.mjs';
import {directSingleArtifact} from '../app/execution_efficiency.mjs';

it('opens page media composition only for conversation HTML', () => {
  for (const kind of ['image','video','audio','text']) {
    expect(webMediaAllowed({}, new Set(['html']), kind)).toBe(true);
    expect(webMediaAllowed({taskSurface:'canvas_node'}, new Set(['html']), kind)).toBe(false);
    expect(webMediaAllowed({}, new Set(['image']), kind)).toBe(false);
  }
  expect(webMediaAllowed({}, new Set(['html']), 'cad')).toBe(false);
  expect(directSingleArtifact({executionPolicyVersion:3,singleDeliveryTarget:{kind:'html',count:1}})).toBe(false);
});
