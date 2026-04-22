#!/usr/bin/env python3
# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Tests for TreeBuilder._resolve_unique_uri — duplicate filename auto-rename."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _make_viking_fs_mock(existing_uris: set[str]):
    """Create a mock VikingFS whose stat() raises for non-existing URIs."""
    fs = MagicMock()

    async def _stat(uri, **kwargs):
        if uri in existing_uris:
            return {"name": uri.split("/")[-1], "isDir": True}
        raise FileNotFoundError(f"Not found: {uri}")

    fs.stat = AsyncMock(side_effect=_stat)
    return fs


class TestResolveUniqueUri:
    @pytest.mark.asyncio
    async def test_no_conflict(self):
        """When the URI is free, return it unchanged."""
        from openviking.parse.tree_builder import TreeBuilder

        fs = _make_viking_fs_mock(set())
        builder = TreeBuilder()

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            result = await builder._resolve_unique_uri("viking://resources/report")

        assert result == "viking://resources/report"

    @pytest.mark.asyncio
    async def test_single_conflict(self):
        """When base name exists, should return name_1."""
        from openviking.parse.tree_builder import TreeBuilder

        existing = {"viking://resources/report"}
        fs = _make_viking_fs_mock(existing)
        builder = TreeBuilder()

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            result = await builder._resolve_unique_uri("viking://resources/report")

        assert result == "viking://resources/report_1"

    @pytest.mark.asyncio
    async def test_multiple_conflicts(self):
        """When _1 and _2 also exist, should return _3."""
        from openviking.parse.tree_builder import TreeBuilder

        existing = {
            "viking://resources/report",
            "viking://resources/report_1",
            "viking://resources/report_2",
        }
        fs = _make_viking_fs_mock(existing)
        builder = TreeBuilder()

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            result = await builder._resolve_unique_uri("viking://resources/report")

        assert result == "viking://resources/report_3"

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        """When all candidate names are taken, raise FileExistsError."""
        from openviking.parse.tree_builder import TreeBuilder

        existing = {"viking://resources/report"} | {
            f"viking://resources/report_{i}" for i in range(1, 6)
        }
        fs = _make_viking_fs_mock(existing)
        builder = TreeBuilder()

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            with pytest.raises(FileExistsError, match="Cannot resolve unique name"):
                await builder._resolve_unique_uri("viking://resources/report", max_attempts=5)

    @pytest.mark.asyncio
    async def test_gap_in_sequence(self):
        """If _1 exists but _2 does not, should return _2 (not skip to _3)."""
        from openviking.parse.tree_builder import TreeBuilder

        existing = {
            "viking://resources/report",
            "viking://resources/report_1",
        }
        fs = _make_viking_fs_mock(existing)
        builder = TreeBuilder()

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            result = await builder._resolve_unique_uri("viking://resources/report")

        assert result == "viking://resources/report_2"


class TestFinalizeFromTemp:
    @staticmethod
    def _make_fs(entries, existing_uris: set[str]):
        fs = MagicMock()
        moved = []

        async def _ls(uri, **kwargs):
            return entries[uri]

        async def _stat(uri, **kwargs):
            if uri in existing_uris:
                return {"name": uri.split("/")[-1], "isDir": True}
            raise FileNotFoundError(f"Not found: {uri}")

        async def _mv(old_uri, new_uri, **kwargs):
            moved.append((old_uri, new_uri))
            for base_uri, listing in list(entries.items()):
                for entry in listing:
                    entry_uri = entry.get("uri", f"{base_uri.rstrip('/')}/{entry['name']}")
                    if entry_uri == old_uri:
                        old_name = entry["name"]
                        new_name = new_uri.rstrip("/").split("/")[-1]
                        entry["name"] = new_name
                        entry["uri"] = new_uri
                        if entry.get("isDir"):
                            child_entries = entries.pop(old_uri, [])
                            entries[new_uri] = child_entries
                            for child in child_entries:
                                child_uri = child.get(
                                    "uri", f"{old_uri.rstrip('/')}/{child['name']}"
                                )
                                child["uri"] = child_uri.replace(old_uri, new_uri, 1)
                        elif old_name != new_name:
                            entry["uri"] = new_uri
                        return
            raise FileNotFoundError(old_uri)

        fs.ls = AsyncMock(side_effect=_ls)
        fs.stat = AsyncMock(side_effect=_stat)
        fs.mv = AsyncMock(side_effect=_mv)
        fs._moved = moved
        return fs

    @pytest.mark.asyncio
    async def test_resources_root_to_behaves_like_parent(self):
        from openviking.parse.tree_builder import TreeBuilder
        from openviking.server.identity import RequestContext, Role
        from openviking_cli.session.user_id import UserIdentifier

        entries = {
            "viking://temp/import": [{"name": "tt_b", "isDir": True}],
            "viking://temp/import/tt_b": [],
        }
        fs = self._make_fs(entries, {"viking://resources"})
        builder = TreeBuilder()
        ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            tree = await builder.finalize_from_temp(
                temp_dir_path="viking://temp/import",
                ctx=ctx,
                scope="resources",
                to_uri="viking://resources",
            )

        assert tree.root.uri == "viking://resources/tt_b"
        assert tree.root.temp_uri == "viking://temp/import/tt_b"
        assert tree._candidate_uri == "viking://resources/tt_b"

    @pytest.mark.asyncio
    async def test_resources_root_to_with_trailing_slash_uses_child_incremental_target(self):
        from openviking.parse.tree_builder import TreeBuilder
        from openviking.server.identity import RequestContext, Role
        from openviking_cli.session.user_id import UserIdentifier

        entries = {
            "viking://temp/import": [{"name": "tt_b", "isDir": True}],
            "viking://temp/import/tt_b": [],
        }
        fs = self._make_fs(entries, {"viking://resources", "viking://resources/tt_b"})
        builder = TreeBuilder()
        ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            tree = await builder.finalize_from_temp(
                temp_dir_path="viking://temp/import",
                ctx=ctx,
                scope="resources",
                to_uri="viking://resources/",
            )

        assert tree.root.uri == "viking://resources/tt_b"
        assert tree.root.temp_uri == "viking://temp/import/tt_b"
        assert tree._candidate_uri == "viking://resources/tt_b"

    @pytest.mark.asyncio
    async def test_resources_root_to_keeps_single_file_wrapper_directory(self):
        from openviking.parse.tree_builder import TreeBuilder
        from openviking.server.identity import RequestContext, Role
        from openviking_cli.session.user_id import UserIdentifier

        entries = {
            "viking://temp/import": [{"name": "aa", "isDir": True}],
            "viking://temp/import/aa": [{"name": "aa.md", "isDir": False}],
        }
        fs = self._make_fs(entries, {"viking://resources"})
        builder = TreeBuilder()
        ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            tree = await builder.finalize_from_temp(
                temp_dir_path="viking://temp/import",
                ctx=ctx,
                scope="resources",
                to_uri="viking://resources",
            )

        assert tree.root.uri == "viking://resources/aa"
        assert tree.root.temp_uri == "viking://temp/import/aa"
        assert tree._candidate_uri == "viking://resources/aa"

    @pytest.mark.asyncio
    async def test_finalize_from_temp_sanitizes_any_type_tree_names(self):
        from openviking.parse.tree_builder import TreeBuilder
        from openviking.server.identity import RequestContext, Role
        from openviking_cli.session.user_id import UserIdentifier

        entries = {
            "viking://temp/import": [{"name": "bad root?@", "isDir": True}],
            "viking://temp/import/bad root?@": [
                {"name": "bad file?.md", "isDir": False},
                {"name": "bad dir", "isDir": True},
            ],
            "viking://temp/import/bad root?@/bad dir": [
                {"name": "nested@file?.md", "isDir": False},
            ],
        }
        fs = self._make_fs(entries, set())
        builder = TreeBuilder()
        ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            tree = await builder.finalize_from_temp(
                temp_dir_path="viking://temp/import",
                ctx=ctx,
                scope="resources",
            )

        assert tree.root.uri == "viking://resources/bad_root__"
        assert tree.root.temp_uri == "viking://temp/import/bad_root__"
        assert ("viking://temp/import/bad root?@", "viking://temp/import/bad_root__") in fs._moved
        assert (
            "viking://temp/import/bad_root__/bad file?.md",
            "viking://temp/import/bad_root__/bad_file_.md",
        ) in fs._moved
        assert (
            "viking://temp/import/bad_root__/bad dir",
            "viking://temp/import/bad_root__/bad_dir",
        ) in fs._moved

    @pytest.mark.asyncio
    async def test_finalize_from_temp_deduplicates_sanitized_sibling_names(self):
        from openviking.parse.tree_builder import TreeBuilder
        from openviking.server.identity import RequestContext, Role
        from openviking_cli.session.user_id import UserIdentifier

        entries = {
            "viking://temp/import": [{"name": "root", "isDir": True}],
            "viking://temp/import/root": [
                {"name": "a?.md", "isDir": False},
                {"name": "a_.md", "isDir": False},
                {"name": "same dir?", "isDir": True},
                {"name": "same_dir_", "isDir": True},
            ],
            "viking://temp/import/root/same dir?": [],
            "viking://temp/import/root/same_dir_": [],
        }
        fs = self._make_fs(entries, set())
        builder = TreeBuilder()
        ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)

        with patch("openviking.parse.tree_builder.get_viking_fs", return_value=fs):
            tree = await builder.finalize_from_temp(
                temp_dir_path="viking://temp/import",
                ctx=ctx,
                scope="resources",
            )

        assert tree.root.uri == "viking://resources/root"
        assert ("viking://temp/import/root/a?.md", "viking://temp/import/root/a_.md") in fs._moved
        assert ("viking://temp/import/root/a_.md", "viking://temp/import/root/a__1.md") in fs._moved
        assert (
            "viking://temp/import/root/same dir?",
            "viking://temp/import/root/same_dir_",
        ) in fs._moved
        assert (
            "viking://temp/import/root/same_dir_",
            "viking://temp/import/root/same_dir__1",
        ) in fs._moved
