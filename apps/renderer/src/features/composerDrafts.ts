import { toRaw } from 'vue';
export interface DraftBackend<T> { read(key: string): Promise<T | undefined>; write(key: string, value: T): Promise<void>; remove(key: string): Promise<void> }

/** IndexedDB cannot clone Vue proxies. Preserve File/Blob while unwrapping nested draft arrays. */
export function draftStorageValue<T>(value: T): T {
  const raw = toRaw(value);
  if (Array.isArray(raw)) return raw.map(item => draftStorageValue(item)) as T;
  if (raw && typeof raw === 'object' && Object.getPrototypeOf(raw) === Object.prototype) {
    return Object.fromEntries(Object.entries(raw).map(([key, item]) => [key, draftStorageValue(item)])) as T;
  }
  return raw;
}

/** IndexedDB preserves File/Blob attachments across reloads without base64. */
export function indexedDraftBackend<T>(): DraftBackend<T> {
  let database: Promise<IDBDatabase> | undefined;
  const open = () => database ||= new Promise((resolve, reject) => {
    const request = indexedDB.open('langju-composer-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { database = undefined; reject(request.error); };
  });
  async function transaction<R>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<R>): Promise<R> {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', mode);
      const request = operation(tx.objectStore('drafts'));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('无法保存本地草稿'));
    });
  }
  return { read: key => transaction('readonly', store => store.get(key)),
    write: async (key, value) => { await transaction('readwrite', store => store.put(draftStorageValue(value), key)); },
    remove: async key => { await transaction('readwrite', store => store.delete(key)); } };
}

/** Serialize writes per project so an older save cannot undo a send/delete. */
export class ComposerDraftStore<T> {
  private pending = new Map<string, Promise<void>>();
  private memory = new Map<string, T | undefined>();
  constructor(private backend: DraftBackend<T> = indexedDraftBackend<T>()) {}
  private enqueue(key: string, operation: () => Promise<void>) {
    const previous = this.pending.get(key) || Promise.resolve();
    const next = previous.catch(() => undefined).then(operation);
    this.pending.set(key, next);
    void next.finally(() => { if (this.pending.get(key) === next) this.pending.delete(key); }).catch(() => undefined);
    return next;
  }
  save(key: string, value: T) {
    this.memory.set(key, value);
    return this.enqueue(key, () => this.backend.write(key, value));
  }
  remove(key: string) {
    this.memory.set(key, undefined);
    return this.enqueue(key, () => this.backend.remove(key));
  }
  async load(key: string) {
    if (this.memory.has(key)) return this.memory.get(key);
    const value = await this.backend.read(key);
    // A user edit may have arrived while the disk read was outstanding.
    if (this.memory.has(key)) return this.memory.get(key);
    this.memory.set(key, value);
    return value;
  }
}
