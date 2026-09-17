import pytest

def test_provider_failure_is_not_reported_as_empty(monkeypatch):
    from backend.app.services import search as module
    monkeypatch.setattr(module, 'get_settings', lambda: type('S', (), {'TAVILY_API_KEY':'k'})())
    class Broken:
        def __init__(self, **kwargs): pass
        def search(self, *args, **kwargs): raise OSError('offline')
    monkeypatch.setattr(module, 'TavilyClient', Broken)
    with pytest.raises(RuntimeError): module._search_sync('x', 1)
