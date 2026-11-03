from copy import deepcopy
from server import layout_cache


def test_complete_state_and_modes_invalidate_response():
    snapshot={'revision':1,'paragraphs':[{'en':'before','groups':[]}]}
    baseline=layout_cache.key(b'source',snapshot,'en',False,False)
    layout_cache.put(baseline,{'pages':[{'regions':[]}], 'revision':1})
    cached=layout_cache.get(baseline);cached['pages'][0]['regions'].append('outside mutation')
    assert layout_cache.get(baseline)['pages'][0]['regions']==[]
    assert layout_cache.get(baseline)['responseCacheHit']
    changed=deepcopy(snapshot);changed['paragraphs'][0]['groups']=['new mapping']
    alternatives=[layout_cache.key(b'changed',snapshot,'en',False,False),
                  layout_cache.key(b'source',changed,'en',False,False),
                  layout_cache.key(b'source',snapshot,'zh',False,False),
                  layout_cache.key(b'source',snapshot,'en',True,False),
                  layout_cache.key(b'source',snapshot,'en',False,True)]
    assert all(k!=baseline for k in alternatives)


def test_cache_is_bounded():
    for i in range(layout_cache.LIMIT+1):layout_cache.put('bounded-'+str(i),{'n':i})
    assert layout_cache.get('bounded-0') is None
    assert layout_cache.get('bounded-'+str(layout_cache.LIMIT))['n']==layout_cache.LIMIT
