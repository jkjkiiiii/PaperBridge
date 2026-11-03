import asyncio
import httpx
import pytest
import server.llm as module


@pytest.mark.parametrize('error,expected,calls', [
    (httpx.ReadTimeout('slow'), '等待模型生成超过 180 秒', 1),
    (httpx.ReadError('disconnected'), '不会自动重复提交', 1),
    (httpx.WriteTimeout('partial write'), '不会自动重复提交', 1),
    (httpx.ConnectTimeout('offline'), '无法连接模型服务', 3),
])
def test_inference_failures_do_not_duplicate_uncertain_requests(tmp_path, monkeypatch, error, expected, calls):
    attempts = []
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs['timeout'].read == 180
            assert kwargs['timeout'].connect == 10
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            attempts.append(1)
            raise error
    async def sleep(_): pass
    monkeypatch.setattr(module.httpx, 'AsyncClient', FakeClient)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    with pytest.raises(module.ModelError, match=expected):
        asyncio.run(module.ModelClient(tmp_path).generate('translate_align', {'source_units': []}, cache=False))
    assert len(attempts) == calls
