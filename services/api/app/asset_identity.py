"""Convert displayed asset mentions to storage IDs without widening their scope."""


def asset_id(value):
    if not isinstance(value, str):
        return value
    value = value.strip()
    for prefix in ('@asset:', 'asset:'):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def selected_asset_id(value, context):
    """Resolve an exact selected-memory id/key to its underlying asset id.

    Design plans are model-authored and may copy the stable memory key shown by
    conversation_memory_read instead of the storage asset id.  Only aliases in
    the task's selected memory are accepted here, so resolving one does not
    widen the task's canvas or asset scope.
    """
    selected = (context.get('conversationMemory') or {}).get('selected', []) if isinstance(context, dict) else []
    for record in selected:
        if not isinstance(record, dict) or not record.get('assetId'):
            continue
        if value in {record.get('id'), record.get('key')}:
            return asset_id(record['assetId'])
    return asset_id(value)
