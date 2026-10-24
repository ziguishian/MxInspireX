"""Server-owned boundary for literal canvas submissions (legacy tasks unchanged)."""
from contextvars import ContextVar

literal_prompt = ContextVar('literal_node_prompt', default=False)


def is_literal(context):
    return context.get('taskSurface') == 'canvas_node' and isinstance(context.get('nodePrompt'), dict) and context['nodePrompt'].get('version') == 1


def bind_literal(context, name, arguments):
    if not is_literal(context):
        return arguments
    canvas = context.get('canvasParams') or {}
    kind = 'image' if canvas.get('kind') == 'upload' else canvas.get('kind')
    if name != 'generate_' + str(kind):
        return arguments
    args = dict(arguments)
    args['prompt'] = context['nodePrompt']['submitted']
    args['params'] = {k: v for k, v in canvas.items() if k not in {
        'kind', 'model', 'canvasNodeId', 'source_asset_id', 'source_asset_ids',
        'last_frame_asset_id', 'reference_node_ids', 'reference_asset_ids', 'originalPrompt', 'style', 'camera', 'camera_motion'}}
    if canvas.get('model'):
        args['model'] = canvas['model']
    for key in ('source_asset_id', 'source_asset_ids', 'last_frame_asset_id'):
        if key in canvas:
            args[key] = canvas[key]
    args['canvas_node_id'] = canvas.get('canvasNodeId')
    args.pop('reference_analysis', None)
    args.pop('negative_prompt', None)
    media = (context.get('mediaProvider') or {}).get(kind) or {}
    if media.get('baseUrl'):
        args['params']['baseUrl'] = media['baseUrl']
    return args
