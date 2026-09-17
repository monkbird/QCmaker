def test_search_status_contract_has_distinct_states():
    from backend.app.models.authoring import SearchResponse
    result = SearchResponse(status='not_configured')
    assert result.status == "not_configured"
    assert result.results == []
