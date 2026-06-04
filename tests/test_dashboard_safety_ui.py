"""Static contract checks for the Dashboard safety workflows."""

from pathlib import Path


def test_dashboard_contains_review_and_recovery_workflows():
    html = (Path(__file__).resolve().parent.parent / "dashboard.html").read_text(encoding="utf-8")

    assert 'data-tab="review"' in html
    assert "/api/proposals?status=pending" in html
    assert "/api/proposals/review" in html
    assert "/api/trash/" in html
    assert "/history" in html
    assert "/rollback" in html
    assert "确认批准并执行此提案" in html
    assert "确认将该记忆回滚" in html
