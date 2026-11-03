"""Measure fixed-text alignment repairs without retranslating or changing routes."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_translation_cost_experiment import ExperimentClient, instrument_http
import httpx
from server.app import context_for
from server.state import Store, save_json, units_with_offsets, validate_links
from server.translation_router import TranslationRouter
from server.usage_cost import reconcile_usage, markdown_report


async def run(args):
    out = args.output_dir.resolve()
    if (out / 'usage-ledger.json').exists():
        raise ValueError('Choose a new output directory to preserve earlier measurements')
    store = Store(ROOT / '.data/projects')
    project = store.get(args.project)
    settings = deepcopy(project['retranslation']['settings'])
    client = ExperimentClient(ROOT / '.data', settings)
    router = TranslationRouter(client, ROOT / '.data')
    ledger = {'context': {'scope': 'Fixed-text alignment repair only; no MT or rewriting'},
              'requests': [], 'translationRequests': []}
    original_http = instrument_http(ledger, out / 'usage-ledger.json', 'api.deepseek.com')
    candidates, results = [], []
    try:
        for pid in args.paragraph:
            item = store.paragraph(project, pid)
            if item['draftZh'] != item['zh'] or item.get('deleted') or item['status'] == 'running':
                raise ValueError('Paragraph has pending edits or is running')
            response = await router.align_text({
                'paragraph_id': pid, 'source_units': item['units'],
                'protected_tokens': item['protected'], 'context': context_for(project, item),
                'translationPolicy': item.get('translationPolicy', 'translate'),
            }, item['zh'], settings=settings, cache=False)
            targets = units_with_offsets(response['data']['target_units'])
            assert ''.join(t['text'] for t in targets) == item['zh']
            links = [{'source_ids': t['source_ids'], 'target_ids': [t['id']]}
                     for t in response['data']['target_units']]
            groups = validate_links(item['units'], targets, links, item['groups'])
            candidate = deepcopy(item)
            candidate.update(targetUnits=targets, groups=groups,
                             modelMeta={**item.get('modelMeta', {}), **response['meta']})
            candidates.append((item, candidate))
            results.append({'paragraphId': pid, 'beforeTargetCount': len(item['targetUnits']),
                'afterTargetCount': len(targets), 'groups': groups, **response['meta'],
                'fixedEnglishUnchanged': candidate['en'] == item['en'],
                'fixedChineseUnchanged': candidate['zh'] == item['zh']})
    finally:
        httpx.AsyncClient = original_http
        save_json(out / 'usage-ledger.json', ledger)
    report = reconcile_usage(ledger)
    save_json(out / 'cost-report.json', report)
    (out / 'cost-report.md').write_text(markdown_report(report), 'utf-8')
    save_json(out / 'alignment-results.json', results)
    if args.apply:
        if any(r['alignmentMethod'] != 'llm' for r in results):
            raise ValueError('Unresolved alignment; no project changes applied')
        live = store.get(args.project)
        for before, after in candidates:
            current = store.paragraph(live, before['id'])
            if current != before:
                raise ValueError('Project changed during repair; no changes applied')
            after['history'].append(store.snapshot(before))
            after.update(redo=[], revision=before['revision'] + 1)
            live['paragraphs'][live['paragraphs'].index(current)] = after
            store.event(live, after, 'repair_alignment', {'model': after['modelMeta']})
        assert store.export(live) == store.export(project)
        store.save(live)
    print(json.dumps({'results': [{'paragraphId': r['paragraphId'],
        'mapping': [g['kind'] for g in r['groups']], 'method': r['alignmentMethod'],
        'notes': r['alignmentNotes']} for r in results],
        'tokens': report['totals'], 'rmb': report['rmbAtPublishedRates'],
        'applied': args.apply}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--paragraph', action='append', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args()))
