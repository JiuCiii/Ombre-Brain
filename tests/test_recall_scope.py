"""Regression tests for strict scope isolation and recall counters."""

import pytest


@pytest.mark.asyncio
async def test_scope_filter_is_strict(bucket_mgr):
    global_id = await bucket_mgr.create(
        content="shared keyword",
        domain=["test"],
        name="shared keyword",
        scope="global",
    )
    project_id = await bucket_mgr.create(
        content="shared keyword",
        domain=["test"],
        name="shared keyword",
        scope="project:ombre",
    )

    results = await bucket_mgr.search("shared keyword", scope_filter="project:ombre")
    assert [result["id"] for result in results] == [project_id]
    assert global_id not in {result["id"] for result in results}
    assert await bucket_mgr.search("shared keyword", scope_filter="project:missing") == []


@pytest.mark.asyncio
async def test_match_and_recall_do_not_increase_heat(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="counter test", domain=["test"])

    await bucket_mgr.record_match(bucket_id)
    await bucket_mgr.record_recall(bucket_id)
    bucket = await bucket_mgr.get(bucket_id)
    assert bucket["metadata"]["matched_count"] == 1
    assert bucket["metadata"]["recalled_count"] == 1
    assert bucket["metadata"]["confirmed_count"] == 0
    assert bucket["metadata"]["activation_count"] == 0

    await bucket_mgr.touch(bucket_id)
    bucket = await bucket_mgr.get(bucket_id)
    assert bucket["metadata"]["confirmed_count"] == 1
    assert bucket["metadata"]["activation_count"] == 1


@pytest.mark.asyncio
async def test_scope_update_is_audited(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="move scope", domain=["test"])

    assert await bucket_mgr.update(bucket_id, scope="project:ombre")
    bucket = await bucket_mgr.get(bucket_id)
    assert bucket["metadata"]["scope"] == "project:ombre"
    assert bucket_mgr.history(bucket_id)[0]["action"] == "update"
