import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { fitModelCamera } from './cadViewer';
import { canvasNodeKind } from '../nodeSizing';
import { assetPreviewKind } from './assetPreview';

describe('CAD preview', () => {
  it('fits every corner of a large off-centre model into narrow and wide viewports', () => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(80, 8, 50)); mesh.position.set(500, -200, 50);
    for (const aspect of [.5, 2]) for (const view of ['iso', 'front', 'top', 'right'] as const) {
      const camera = new THREE.PerspectiveCamera(35);
      expect(fitModelCamera(camera, mesh, aspect, view).toArray()).toEqual([500, -200, 50]);
      camera.updateMatrixWorld();
      for (const x of [460, 540]) for (const y of [-204, -196]) for (const z of [25, 75]) {
        const point = new THREE.Vector3(x, y, z).project(camera);
        expect(Math.abs(point.x)).toBeLessThan(1); expect(Math.abs(point.y)).toBeLessThan(1);
        expect(point.z).toBeGreaterThan(-1); expect(point.z).toBeLessThan(1);
      }
    }
  });
  it('rejects an empty model and identifies CAD manifests separately from meshes', () => {
    expect(() => fitModelCamera(new THREE.PerspectiveCamera(), new THREE.Group(), 1)).toThrow();
    expect(canvasNodeKind({ kind: 'cad', asset: { pathRelative: 'model.cad.json' } })).toBe('cad');
    expect(assetPreviewKind({ id: 'a', projectId: 'p', kind: 'cad', pathRelative: 'model.cad.json', byteSize: 20 })).toBe('cad');
  });
});
