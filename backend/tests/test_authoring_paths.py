from backend.app.services.qc_paths import chapter_path, build_chapter_id


def test_problem_solving_path_has_eleven_stable_chapters():
    path = chapter_path("problem_solving", "self_defined", "T/CAQ 10201-2020")
    assert len(path) == 11
    assert path[0].chapter_id == build_chapter_id("T/CAQ 10201-2020", "self_defined", "overview")
    assert path[-1].slug == "summary"
