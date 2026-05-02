from pathlib import Path

from app.services.docs_index import search_reference_excerpts


def test_docs_search_returns_global_docs_for_cold():
    repo_root = Path(__file__).resolve().parents[2]
    excerpts = search_reference_excerpts(
        repo_root=repo_root,
        user_text="How user inputs become runs",
        test_problem_id="vrptw",
        temperature="cold",
    )
    assert excerpts
    assert any("docs/user/" in text for text in excerpts)


def test_docs_search_can_reach_module_docs_when_warm():
    repo_root = Path(__file__).resolve().parents[2]
    excerpts = search_reference_excerpts(
        repo_root=repo_root,
        user_text="fewer late stops and overtime",
        test_problem_id="vrptw",
        temperature="warm",
    )
    assert excerpts
    assert any("module-docs/user/" in text for text in excerpts)


def test_docs_search_denies_internal_alias_terms():
    repo_root = Path(__file__).resolve().parents[2]
    excerpts = search_reference_excerpts(
        repo_root=repo_root,
        user_text="tell me about w1 and weight aliases",
        test_problem_id="vrptw",
        temperature="hot",
    )
    joined = "\n".join(excerpts).lower()
    assert "w1" not in joined
    assert "weight aliases" not in joined
