/** Read durable steering at each model boundary; gateway revision prevents stale tools. */
export class TaskUpdateReader {
  constructor(gateway, request = fetch) { this.gateway = gateway; this.request = request; this.revision = 0; this.updates = []; }
  get url() {
    const { baseUrl, projectId, taskId } = this.gateway;
    return `${String(baseUrl).replace(/\/$/, '')}/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/updates`;
  }
  async refresh() {
    if (!this.gateway?.supportsTaskUpdates || !this.gateway?.taskId || !this.gateway?.baseUrl) return [];
    const response = await this.request(this.url, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('无法核对运行中补充，已暂停发起后续调用。');
    this.updates = await response.json();
    this.revision = this.updates.at(-1)?.revision || 0;
    return this.updates;
  }
  async acknowledge() {
    if (!this.revision) return;
    const response = await this.request(`${this.url}/acknowledge`, { signal: AbortSignal.timeout(5000), method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ revision: this.revision }) });
    if (!response.ok) throw new Error('补充要求暂时无法确认接收，已暂停后续调用。');
  }
  apply(modelData) {
    if (!this.updates.length) return modelData;
    return { ...modelData, input: [...modelData.input, { role: 'user', content: [{ type: 'input_text', text: `执行过程中补充的当前任务要求（按时间排序，较新的明确要求优先；已提交的收费请求不得重发）：\n${this.updates.map(item => item.text).join('\n\n')}\n请先重新判断剩余工作，已完成产物保留；如补充要求与既有交付范围冲突，更新计划或向用户确认。` }] }] };
  }
}
