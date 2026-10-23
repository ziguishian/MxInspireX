"""Editable, local design constraints stored as ordinary text nodes."""
import re


def design_node_data(editor, data=None):
    data = data or {}
    if editor == 'palette':
        colors = data.get('colors', ['#F58220', '#181818', '#FFFFFF'])
        if not isinstance(colors, list) or not 1 <= len(colors) <= 8 or any(not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors):
            raise ValueError('色板需要 1–8 个有效的 HEX 颜色')
        return {'editor': editor, 'colors': colors, 'text': f'配色约束：{"、".join(colors)}。按顺序作为主色、辅助色与点缀色。', 'draft': False}
    shots = data.get('shots', [{'description': '', 'duration': 3, 'camera': ''}])
    if not isinstance(shots, list) or not 1 <= len(shots) <= 12:
        raise ValueError('分镜需要 1–12 个镜头')
    clean = []
    for shot in shots:
        if not isinstance(shot, dict): raise ValueError('镜头格式错误')
        duration = shot.get('duration', 3)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 30 or int(duration) != duration:
            raise ValueError('每个镜头时长应为 1–30 的整数秒')
        description, camera = shot.get('description', ''), shot.get('camera', '')
        if not isinstance(description, str) or len(description) > 1200 or not isinstance(camera, str) or len(camera) > 150:
            raise ValueError('镜头描述或运镜过长')
        clean.append({'description': description, 'duration': duration, 'camera': camera})
    text = '视频分镜（按顺序在同一条视频中执行）：\n' + '\n'.join(f'{i+1}. {s["duration"]}秒；{s["description"]}；运镜：{s["camera"] or "自然平稳"}' for i, s in enumerate(clean))
    return {'editor': editor, 'shots': clean, 'text': text, 'draft': False}
