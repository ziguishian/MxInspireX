// Observe public tool identity/activity only; never forward argument text or reasoning.
export class HtmlGenerationProgress {
  constructor({ begin, notify }) { this.begin = begin; this.notify = notify; this.calls = new Map(); this.items = new Map(); this.last = 0; }
  reset() { this.calls.clear(); this.items.clear(); this.last = 0; }
  async handle(data) {
    if (data?.type === 'response_started') { this.reset(); return; }
    const raw = data?.type === 'model' ? data.event : data;
    let active;
    if (raw?.type === 'response.output_item.added' && raw.item?.type === 'function_call') {
      const item = raw.item;
      this.items.set(item.id, { id: item.call_id, name: item.name });
      active = this.items.get(item.id);
    } else if (raw?.type === 'response.function_call_arguments.delta') active = this.items.get(raw.item_id);
    else if (raw?.choices?.length) {
      for (const delta of raw.choices[0]?.delta?.tool_calls || []) {
        const call = this.calls.get(delta.index) || { id: '', name: '' };
        if (delta.id) call.id = delta.id;
        call.name += delta.function?.name || '';
        this.calls.set(delta.index, call);
        if (call.name === 'canvas_create_html' && call.id) {
          await this.begin(call.id);
          active = call;
        }
      }
    }
    if (active?.name !== 'canvas_create_html' || !active.id) return;
    await this.begin(active.id);
    if (Date.now() - this.last >= 4000) {
      this.notify({ type: 'event', phase: 'generation', message: '正在生成网页…' });
      this.last = Date.now();
    }
  }
}
