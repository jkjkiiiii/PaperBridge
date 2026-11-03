"""Read-only display snapshots, deliberately separate from export validation."""
from copy import deepcopy
from .documents import split_units


def committed_preview(project):
    snapshot = deepcopy(project)
    pending = []
    for item in snapshot['paragraphs']:
        if item.get('deleted'):
            continue
        status = item.get('status', 'untranslated')
        dirty = status not in ('ready', 'untranslated') or item.get('draftZh', '') != item.get('zh', '')
        if not dirty:
            continue
        pending.append({'id': item['id'], 'status': status, 'error': item.get('error', '')})
        if status in ('needs_alignment', 'conflict'):
            previous = next((h for h in reversed(item.get('history', []))
                if h.get('status') in ('ready', 'untranslated') and not h.get('deleted')
                and h.get('draftZh', '') == h.get('zh', '')), None)
            if previous:
                for key in ('en', 'zh', 'units', 'targetUnits', 'groups', 'stylePolicy'):
                    if key in previous: item[key] = deepcopy(previous[key])
            else:
                item['en'] = item.get('originalEn', '')
                item['zh'] = ''
                item['units'] = split_units(item['en'], item['id'] + '_')
                item['targetUnits'] = []
                item['groups'] = []
        # en/zh are the committed pair for normal draft/model processing states.
        # Never present draftZh as though it already had matching English.
        item['draftZh'] = item.get('zh', '')
        item['status'] = 'ready' if item.get('zh') else 'untranslated'
        item['groups'] = []
        item['units'] = []
        item['originalUnits'] = []
        item['targetUnits'] = []
    return snapshot, pending
