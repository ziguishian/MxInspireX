globalThis.fetch = async (url, options) => {
  if (!String(url).includes('/agent-tools/generate_image')) throw new Error(`Unexpected request (including text model): ${url}`);
  const body = JSON.parse(options.body);
  if (body.arguments?.prompt !== ' 原样\n' && body.prompt !== ' 原样\n') throw new Error('Prompt changed: ' + options.body);
  return new Response(JSON.stringify({tool:'generate_image',status:'succeeded',assetId:'image-1',asset:{id:'image-1',kind:'image'},node:{id:'target',data:{kind:'image',assetId:'image-1'}}}), {status:200,headers:{'content-type':'application/json'}});
};
