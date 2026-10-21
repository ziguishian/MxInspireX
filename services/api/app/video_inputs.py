"""Normalize video inputs before scoping, billing, or provider submission."""
import re


def video_options(params=None):
    if params is not None and not isinstance(params, dict):
        raise ValueError('视频 params 必须是参数对象')
    options = dict(params or {})
    durations = []
    for key in ('duration', 'duration_seconds', 'seconds'):
        value = options.pop(key, None)
        if value is None:
            continue
        if isinstance(value, bool) or not re.fullmatch(r'[1-9]\d*', str(value)):
            raise ValueError('视频时长必须是正整数秒')
        durations.append(int(value))
    if len(set(durations)) > 1:
        raise ValueError('视频时长参数冲突，请指定一个时长')
    if durations:
        options['duration'] = durations[0]
    return options


def video_inputs(source_asset_id=None, source_asset_ids=None, last_frame_asset_id=None, params=None):
    options = video_options(params)
    if {'source_asset', 'last_frame_asset', 'frame_images'} & options.keys():
        raise ValueError('首尾帧请使用项目图像资产 ID，不接受路径或原始 frame_images')
    ids = [] if source_asset_ids is None else source_asset_ids
    if not isinstance(ids, list) or any(not isinstance(value, str) or not value.strip() for value in ids):
        raise ValueError('source_asset_ids 必须为图像资产 ID 列表')
    if len(ids) > 2:
        raise ValueError('视频最多支持两张图像：第一张为首帧，第二张为尾帧')
    first = source_asset_id or (ids[0] if ids else None)
    tails = [value for value in (last_frame_asset_id, options.pop('last_frame_asset_id', None), options.pop('end_frame_asset_id', None), ids[1] if len(ids) == 2 else None) if value is not None]
    if any(not isinstance(value, str) or not value.strip() for value in [first, *tails] if value is not None):
        raise ValueError('首尾帧必须指定有效的图像资产 ID')
    if (ids and first != ids[0]) or len(set(tails)) > 1:
        raise ValueError('首尾帧参数冲突，请明确两张图片的顺序')
    last = tails[0] if tails else None
    if last and not first:
        raise ValueError('指定尾帧时必须同时指定首帧图片')
    return first, last, options
