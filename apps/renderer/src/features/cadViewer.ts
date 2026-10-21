import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export type CadView = 'iso' | 'front' | 'top' | 'right';
export function fitModelCamera(camera: THREE.PerspectiveCamera, object: THREE.Object3D, aspect: number, view: CadView = 'iso') {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) throw new Error('模型没有可显示的几何体');
  const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 1e-5);
  const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
  const distance = radius / Math.sin(Math.min(halfFov, Math.atan(Math.tan(halfFov) * aspect))) * 1.15;
  const direction = new THREE.Vector3(...({ iso: [1, .8, 1], front: [0, 0, 1], top: [0, 1, 0], right: [1, 0, 0] }[view] as [number, number, number])).normalize();
  camera.aspect = aspect; camera.near = Math.max(radius / 1000, 1e-7); camera.far = distance + radius * 20;
  camera.up.set(0, view === 'top' ? 0 : 1, view === 'top' ? -1 : 0);
  camera.position.copy(center).addScaledVector(direction, distance); camera.lookAt(center); camera.updateProjectionMatrix();
  return center;
}

export function disposeModel(object: THREE.Object3D) {
  object.traverse(child => {
    const mesh = child as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const material of materials) {
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose();
      material.dispose();
    }
  });
}

export async function loadGlb(url: string, signal?: AbortSignal) {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('模型文件无法读取');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 100 * 1024 * 1024) throw new Error('模型文件过大');
  const gltf = await new GLTFLoader().parseAsync(bytes, '');
  if (signal?.aborted) { disposeModel(gltf.scene); throw new DOMException('已取消', 'AbortError'); }
  return gltf.scene;
}

export async function probeCad(url: string) {
  let renderer: THREE.WebGLRenderer | undefined, model: THREE.Object3D | undefined;
  try {
    model = await loadGlb(url, AbortSignal.timeout(30000));
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(640, 480); renderer.setPixelRatio(1);
    const scene = new THREE.Scene(); scene.background = new THREE.Color('#f0f2f5');
    scene.add(new THREE.HemisphereLight(0xffffff, 0x505566, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 2); light.position.set(3, 5, 4); scene.add(light, model);
    const camera = new THREE.PerspectiveCamera(35, 4 / 3);
    const frames = (['iso', 'front', 'top'] as CadView[]).map(view => {
      fitModelCamera(camera, model!, 4 / 3, view); renderer!.render(scene, camera);
      return renderer!.domElement.toDataURL('image/jpeg', .8);
    });
    return { passed: true, errors: [], frames, code: 'cad_preview_valid' };
  } catch (error) {
    return { passed: false, errors: [error instanceof Error ? error.message : 'CAD 预览失败'], frames: [], code: 'cad_preview_failed' };
  } finally { if (model) disposeModel(model); renderer?.dispose(); renderer?.forceContextLoss(); }
}
