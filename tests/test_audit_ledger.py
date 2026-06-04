"""Regression tests for the memory safety foundation."""

import os

import pytest


@pytest.mark.asyncio
async def test_create_and_update_are_audited(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="original",
        domain=["test"],
        name="audit-test",
    )
    assert await bucket_mgr.update(
        bucket_id,
        content="updated",
        _audit_action="merge",
        _audit_actor="test",
        _audit_reason="merge regression",
    )

    history = bucket_mgr.history(bucket_id)
    assert [event["action"] for event in history[:2]] == ["merge", "create"]
    assert history[0]["actor"] == "test"
    assert history[0]["reason"] == "merge regression"
    assert "original" in history[0]["before"]["raw_text"]
    assert "updated" in history[0]["after"]["raw_text"]
    created = await bucket_mgr.get(bucket_id)
    assert created["metadata"]["source_type"] == "unknown"
    assert created["metadata"]["memory_kind"] == "memory"


@pytest.mark.asyncio
async def test_delete_is_soft_and_restore_recovers_original_path(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="recover me",
        domain=["test"],
        name="restore-test",
    )
    original_path = bucket_mgr._find_bucket_file(bucket_id)
    assert original_path

    assert await bucket_mgr.delete(bucket_id, actor="test", reason="delete regression")
    assert bucket_mgr._find_bucket_file(bucket_id) is None
    assert not os.path.exists(original_path)
    assert bucket_mgr.audit.trash_path(bucket_id).exists()

    assert await bucket_mgr.restore(bucket_id, actor="test", reason="restore regression")
    assert bucket_mgr._find_bucket_file(bucket_id) == original_path
    restored = await bucket_mgr.get(bucket_id)
    assert restored["content"] == "recover me"

    history = bucket_mgr.history(bucket_id)
    assert [event["action"] for event in history[:3]] == ["restore", "delete", "create"]


@pytest.mark.asyncio
async def test_restore_refuses_to_overwrite_live_bucket(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="still live", domain=["test"])

    assert await bucket_mgr.restore(bucket_id) is False
    assert (await bucket_mgr.get(bucket_id))["content"] == "still live"


@pytest.mark.asyncio
async def test_archive_is_audited(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="archive me", domain=["test"])

    assert await bucket_mgr.archive(bucket_id)
    history = bucket_mgr.history(bucket_id)
    assert [event["action"] for event in history[:2]] == ["archive", "create"]
    assert history[0]["after"]["relative_path"].startswith("archive")


@pytest.mark.asyncio
async def test_restore_revision_rolls_back_content(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="version one", domain=["test"])
    create_event = bucket_mgr.history(bucket_id)[0]["event_id"]
    assert await bucket_mgr.update(bucket_id, content="version two")

    assert await bucket_mgr.restore_revision(bucket_id, create_event, actor="test")
    assert (await bucket_mgr.get(bucket_id))["content"] == "version one"
    assert bucket_mgr.history(bucket_id)[0]["action"] == "rollback"


@pytest.mark.asyncio
async def test_list_deleted_only_contains_current_trash(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="trash listing", domain=["test"])

    assert await bucket_mgr.delete(bucket_id, actor="test")
    deleted = await bucket_mgr.list_deleted()
    assert [item["id"] for item in deleted] == [bucket_id]
    assert deleted[0]["content"] == "trash listing"

    assert await bucket_mgr.restore(bucket_id, actor="test")
    assert await bucket_mgr.list_deleted() == []
