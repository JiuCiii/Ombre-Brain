"""Regression tests for safe merge and Dream proposal workflows."""

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

import pytest

from proposal_store import ProposalStore


def test_proposal_store_lifecycle(tmp_path):
    store = ProposalStore(str(tmp_path / "buckets"))
    proposal_id = store.create(
        "dream_insight",
        "possible insight",
        {"content": "possible insight"},
        scope="project:ombre",
    )

    assert store.get(proposal_id)["status"] == "pending"
    assert store.list(scope="project:ombre")[0]["proposal_id"] == proposal_id
    assert store.resolve(proposal_id, "rejected", "test", "not yet")
    assert store.get(proposal_id)["status"] == "rejected"
    assert not store.resolve(proposal_id, "approved", "test")


def test_rejected_merge_keeps_payload_for_review(tmp_path):
    store = ProposalStore(str(tmp_path / "buckets"))
    proposal_id = store.create(
        "merge",
        "merge a into b",
        {"source_bucket_id": "a", "target_bucket_id": "b"},
    )

    assert store.resolve(proposal_id, "rejected", "test", "distinct events")
    rejected = store.get(proposal_id)
    assert rejected["status"] == "rejected"
    assert rejected["payload"]["source_bucket_id"] == "a"


@pytest.mark.asyncio
async def test_safe_merge_requires_approval(test_config, tmp_path, monkeypatch):
    import server
    from bucket_manager import BucketManager

    buckets_dir = str(tmp_path / "buckets")
    config = test_config | {
        "buckets_dir": buckets_dir,
        "merge_mode": "proposal",
        "merge_threshold": 0,
    }
    bucket_mgr = BucketManager(config)
    target_id = await bucket_mgr.create(
        content="original target",
        domain=["test"],
        name="same topic",
        scope="project:ombre",
    )
    dehydrator = MagicMock()
    dehydrator.merge = AsyncMock(return_value="approved merged content")
    embedding = MagicMock()
    embedding.generate_and_store = AsyncMock(return_value=True)
    embedding.delete_embedding = MagicMock()
    proposals = ProposalStore(buckets_dir)

    monkeypatch.setattr(server, "config", config)
    monkeypatch.setattr(server, "bucket_mgr", bucket_mgr)
    monkeypatch.setattr(server, "dehydrator", dehydrator)
    monkeypatch.setattr(server, "embedding_engine", embedding)
    monkeypatch.setattr(server, "proposal_store", proposals)

    result, merged = await server._merge_or_create(
        content="new source",
        tags=["new"],
        importance=6,
        domain=["test"],
        valence=0.5,
        arousal=0.3,
        name="same topic",
        source_type="hold",
        scope="project:ombre",
    )

    pending = proposals.list(scope="project:ombre")
    assert merged is False
    assert "待审核合并" in result
    assert len(pending) == 1
    assert (await bucket_mgr.get(target_id))["content"] == "original target"
    source_id = pending[0]["payload"]["source_bucket_id"]
    assert (await bucket_mgr.get(source_id))["content"] == "new source"
    shown = await server.review_proposals(proposal_id=pending[0]["proposal_id"], action="show")
    assert "original target" in shown
    assert "new source" in shown
    assert "approved merged content" in shown

    success, _ = await server._apply_proposal(pending[0]["proposal_id"], reviewer="test")
    assert success
    assert (await bucket_mgr.get(target_id))["content"] == "approved merged content"
    assert await bucket_mgr.get(source_id) is None
    assert proposals.get(pending[0]["proposal_id"])["status"] == "approved"


@pytest.mark.asyncio
async def test_feel_is_never_a_merge_target(test_config, tmp_path, monkeypatch):
    import server
    from bucket_manager import BucketManager

    buckets_dir = str(tmp_path / "buckets")
    config = test_config | {
        "buckets_dir": buckets_dir,
        "merge_mode": "proposal",
        "merge_threshold": 0,
    }
    bucket_mgr = BucketManager(config)
    feel_id = await bucket_mgr.create(
        content="same topic",
        domain=[],
        name="same topic",
        bucket_type="feel",
    )
    dehydrator = MagicMock()
    dehydrator.merge = AsyncMock(return_value="should not merge")
    embedding = MagicMock()
    embedding.generate_and_store = AsyncMock(return_value=True)
    proposals = ProposalStore(buckets_dir)
    monkeypatch.setattr(server, "config", config)
    monkeypatch.setattr(server, "bucket_mgr", bucket_mgr)
    monkeypatch.setattr(server, "dehydrator", dehydrator)
    monkeypatch.setattr(server, "embedding_engine", embedding)
    monkeypatch.setattr(server, "proposal_store", proposals)

    new_id, merged = await server._merge_or_create(
        content="same topic",
        tags=[],
        importance=5,
        domain=[],
        valence=0.5,
        arousal=0.3,
        name="same topic",
    )

    assert merged is False
    assert new_id != feel_id
    assert proposals.list() == []


@pytest.mark.asyncio
async def test_approved_dream_insight_becomes_inference(test_config, tmp_path, monkeypatch):
    import server
    from bucket_manager import BucketManager

    buckets_dir = str(tmp_path / "buckets")
    config = test_config | {"buckets_dir": buckets_dir}
    bucket_mgr = BucketManager(config)
    proposals = ProposalStore(buckets_dir)
    embedding = MagicMock()
    embedding.generate_and_store = AsyncMock(return_value=True)

    monkeypatch.setattr(server, "bucket_mgr", bucket_mgr)
    monkeypatch.setattr(server, "proposal_store", proposals)
    monkeypatch.setattr(server, "embedding_engine", embedding)

    proposal_id = proposals.create(
        "dream_insight",
        "tentative inference",
        {
            "content": "tentative inference",
            "source_bucket_ids": ["source-a"],
            "valid_until": "2099-01-01T00:00:00",
        },
        scope="project:ombre",
    )
    success, _ = await server._apply_proposal(proposal_id, reviewer="test")

    assert success
    buckets = await bucket_mgr.list_all()
    assert len(buckets) == 1
    meta = buckets[0]["metadata"]
    assert meta["memory_kind"] == "inference"
    assert meta["source_type"] == "dream_approved"
    assert meta["scope"] == "project:ombre"
    assert meta["valid_until"] == "2099-01-01T00:00:00"


@pytest.mark.asyncio
async def test_expired_inference_is_not_recalled(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="expired inference",
        domain=["test"],
        memory_kind="inference",
        valid_until=(datetime.now() - timedelta(days=1)).isoformat(),
    )

    assert await bucket_mgr.get(bucket_id) is not None
    assert bucket_id not in {bucket["id"] for bucket in await bucket_mgr.list_all()}
    assert bucket_id in {
        bucket["id"] for bucket in await bucket_mgr.list_all(include_expired=True)
    }
