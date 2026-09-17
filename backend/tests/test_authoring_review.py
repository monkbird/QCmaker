def test_importable_authoring_models():
    from backend.app.models.authoring import ScenarioCard, ReviewRequest
    assert ScenarioCard(project_id="p", region="浙江").project_id == "p"
    assert ReviewRequest(review_state="approved", reviewer_id="u", expected_revision=1).review_state == "approved"
