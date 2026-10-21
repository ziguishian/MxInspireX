// EvoLink can route successive requests to different upstream resources.
// Replay local content, never a server-owned item reference. Canonical Session
// records remain intact; callId pairs and all visible messages/tools survive.
export function portableResponsesRequest(request, endpoint) {
  if (endpoint.provider !== 'evolink' || endpoint.api !== 'responses') return request;
  const input = (request.input || []).flatMap(item => {
    if (item.type === 'reasoning') {
      // Opaque reasoning is tied to the upstream resource too. Its public
      // summary is optional context, not a tool or a user's requirement.
      const summary = (item.content || []).map(part => part.text || '').filter(Boolean).join('\n');
      return summary ? [{type:'message', role:'assistant', content:[{type:'output_text', text:summary}]}] : [];
    }
    if (!['message','function_call','function_call_result'].includes(item.type)) return [item];
    const {id, ...copy} = item;
    if (copy.providerData) {
      const {id: providerId, ...data} = copy.providerData;
      copy.providerData = data;
    }
    return [copy];
  });
  return {...request, input, previousResponseId:undefined, conversationId:undefined,
    modelSettings:{...request.modelSettings, store:false}};
}
