// Run ready, independent work together. Resource conflicts determine ordering,
// never a configured number of image or tool slots.
const reads = new Set(['skill_list','skill_read','report_progress','search','knowledge_search','document_read','document_part_inspect','asset_search','asset_inspect','conversation_read','context_read','canvas_read','canvas_versions','schedule_list','list_models','web_read','delivery_verify','budget_check','repair_control']);
export const generationTools = ['generate_image','generate_video','generate_audio','generate_3d','generate_cad','generate_text','canvas_create_text','canvas_create_html'];
const creators = new Set(generationTools);
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
export function createToolScheduler() {
  let mutation = Promise.resolve(), search = Promise.resolve();
  const pendingCreations = new Set(), resources = new Map();
  return {
    run(name, args, operation, dependencies = []) {
      if (name === 'web_search') {
        const result = search.then(operation); search = result.catch(() => {}); return result;
      }
      if (reads.has(name)) return Promise.resolve().then(operation);
      if (!creators.has(name)) {
        const result = Promise.allSettled([mutation, ...pendingCreations]).then(operation);
        mutation = result.catch(() => {}); return result;
      }
      const keys = [`request:${name}:${canonical(args)}`, ...(args.canvas_node_id ? [`node:${args.canvas_node_id}`] : []), ...(args.deliverable_ids || []).map(id => `delivery:${id}`)];
      const predecessors = [...keys, ...dependencies.map(id => `delivery:${id}`)].map(key => resources.get(key)).filter(Boolean);
      const result = Promise.allSettled([mutation, ...predecessors]).then(operation);
      pendingCreations.add(result);
      keys.forEach(key => resources.set(key, result));
      const release = () => { pendingCreations.delete(result); keys.forEach(key => { if (resources.get(key) === result) resources.delete(key); }); };
      result.then(release, release);
      return result;
    },
  };
}
