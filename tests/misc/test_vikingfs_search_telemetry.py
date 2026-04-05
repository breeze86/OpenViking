# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Telemetry timing tests for VikingFS.search."""

import contextvars
from unittest.mock import MagicMock

import pytest

from openviking.server.identity import RequestContext, Role
from openviking.storage.viking_fs import VikingFS
from openviking.telemetry.backends.memory import MemoryOperationTelemetry
from openviking.telemetry.context import bind_telemetry
from openviking_cli.retrieve.types import ContextType, QueryPlan, QueryResult, TypedQuery
from openviking_cli.session.user_id import UserIdentifier


def _ctx() -> RequestContext:
    return RequestContext(user=UserIdentifier("acc1", "user1", "agent1"), role=Role.USER)


def _make_viking_fs() -> VikingFS:
    fs = VikingFS.__new__(VikingFS)
    fs.agfs = MagicMock()
    fs.query_embedder = MagicMock(name="embedder")
    fs.rerank_config = None
    fs.vector_store = MagicMock(name="vector_store")
    fs._bound_ctx = contextvars.ContextVar("vikingfs_bound_ctx_test_search", default=None)
    fs._ensure_access = MagicMock()
    fs._get_vector_store = MagicMock(return_value=fs.vector_store)
    fs._get_embedder = MagicMock(return_value=fs.query_embedder)
    fs._infer_context_type = MagicMock(return_value=ContextType.RESOURCE)
    fs._ctx_or_default = MagicMock(return_value=_ctx())
    return fs


@pytest.mark.asyncio
async def test_search_records_vlm_duration(monkeypatch) -> None:
    fs = _make_viking_fs()
    request_ctx = _ctx()

    async def _fake_analyze(self, **kwargs):
        return QueryPlan(
            queries=[
                TypedQuery(
                    query="guide",
                    context_type=ContextType.RESOURCE,
                    intent="",
                    priority=1,
                )
            ],
            session_context="ctx",
            reasoning="ok",
        )

    class FakeRetriever:
        def __init__(self, storage, embedder, rerank_config):
            pass

        async def retrieve(self, typed_query, ctx, limit, score_threshold, scope_dsl):
            return QueryResult(
                query=typed_query,
                matched_contexts=[],
                searched_directories=["viking://resources/docs"],
            )

    perf_values = iter([0.0, 0.001, 0.002, 0.003])
    monkeypatch.setattr(
        "openviking.telemetry.operation.time.perf_counter",
        lambda: next(perf_values),
    )
    monkeypatch.setattr(
        "openviking.retrieve.intent_analyzer.IntentAnalyzer.analyze",
        _fake_analyze,
    )
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.HierarchicalRetriever",
        FakeRetriever,
    )

    telemetry = MemoryOperationTelemetry(operation="search.search", enabled=True)
    with bind_telemetry(telemetry):
        await fs.search(
            "guide",
            target_uri="viking://resources/docs",
            session_info={
                "latest_archive_overview": "recent context",
                "current_messages": [],
            },
            limit=3,
            ctx=request_ctx,
        )

    summary = telemetry.finish().summary
    assert summary["search"] == {"vlm": {"duration_ms": 1.0}}
