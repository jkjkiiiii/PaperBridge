"""Small content-addressed cache for immutable native-page responses."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
import threading

_CACHE = OrderedDict()
_LOCK = threading.Lock()
LIMIT = 12


def key(source, snapshot, language, original, diff):
    digest=sha256(b'native-response-v1')
    digest.update(sha256(source).digest())
    digest.update(json.dumps([snapshot,language,original,diff],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
    return digest.hexdigest()


def get(identity):
    with _LOCK:
        value=_CACHE.get(identity)
        if value is None:return None
        _CACHE.move_to_end(identity)
        result=deepcopy(value)
    result['responseCacheHit']=True
    return result


def put(identity,value):
    with _LOCK:
        _CACHE[identity]=deepcopy(value)
        _CACHE.move_to_end(identity)
        while len(_CACHE)>LIMIT:_CACHE.popitem(last=False)
