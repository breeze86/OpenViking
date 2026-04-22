# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""
Tree Builder for OpenViking.

Converts parsed document trees into OpenViking context objects with proper
L0/L1/L2 content and URI structure.

v5.0 Architecture:
1. Parser: parse + create directory structure in temp VikingFS
2. TreeBuilder: move to AGFS + enqueue to SemanticQueue + create Resources
3. SemanticProcessor: async generate L0/L1 + vectorize

IMPORTANT (v5.0 Architecture):
- Parser creates directory structure directly, no LLM calls
- TreeBuilder moves files and enqueues to SemanticQueue
- SemanticProcessor handles all semantic generation asynchronously
- Temporary directory approach eliminates memory pressure and enables concurrency
- Resource objects are lightweight (no content fields)
- Content splitting is handled by Parser, not TreeBuilder
"""

import logging
import re
from pathlib import PurePosixPath
from typing import Optional

from openviking.core.building_tree import BuildingTree
from openviking.core.context import Context
from openviking.parse.parsers.media.utils import get_media_base_uri, get_media_type
from openviking.server.identity import RequestContext
from openviking.storage.viking_fs import get_viking_fs
from openviking.utils import parse_code_hosting_url
from openviking_cli.utils.uri import VikingURI

logger = logging.getLogger(__name__)

_ALLOWED_SEGMENT_RE = re.compile(r"[^A-Za-z0-9!\-_.\*'()]")


class TreeBuilder:
    """
    Builds OpenViking context tree from parsed documents (v5.0).

    New v5.0 Architecture:
    - Parser creates directory structure in temp VikingFS (no LLM calls)
    - TreeBuilder moves to AGFS + enqueues to SemanticQueue + creates Resources
    - SemanticProcessor handles semantic generation asynchronously

    Process flow:
    1. Parser creates directory structure with files in temp VikingFS
    2. TreeBuilder.finalize_from_temp() moves to AGFS, enqueues to SemanticQueue, creates Resources
    3. SemanticProcessor generates .abstract.md and .overview.md asynchronously
    4. SemanticProcessor directly vectorizes and inserts to collection

    Key changes from v4.0:
    - Semantic generation moved from Parser to SemanticQueue
    - TreeBuilder enqueues directories for async processing
    - Direct vectorization in SemanticProcessor (no EmbeddingQueue)
    """

    def __init__(self):
        """Initialize TreeBuilder."""
        pass

    @staticmethod
    def _sanitize_name_segment(segment: str) -> str:
        sanitized = _ALLOWED_SEGMENT_RE.sub("_", segment)
        return sanitized or "_"

    @classmethod
    def _dedupe_name(
        cls,
        name: str,
        used_names: set[str],
        *,
        is_dir: bool,
    ) -> str:
        if is_dir:
            base_name = cls._sanitize_name_segment(name)
            candidate = base_name
            index = 1
            while candidate in used_names:
                candidate = f"{base_name}_{index}"
                index += 1
            used_names.add(candidate)
            return candidate

        path = PurePosixPath(name)
        suffixes = "".join(path.suffixes)
        stem = name[: -len(suffixes)] if suffixes else name
        safe_stem = cls._sanitize_name_segment(stem)
        safe_suffix = "".join(cls._sanitize_name_segment(suffix) for suffix in path.suffixes)
        candidate = f"{safe_stem}{safe_suffix}"
        index = 1
        while candidate in used_names:
            candidate = f"{safe_stem}_{index}{safe_suffix}"
            index += 1
        used_names.add(candidate)
        return candidate

    async def _normalize_temp_tree(self, root_uri: str, ctx: RequestContext) -> str:
        viking_fs = get_viking_fs()

        async def _walk(uri: str, current_root_uri: str) -> str:
            entries = await viking_fs.ls(uri, ctx=ctx)
            visible_entries = [
                entry for entry in entries if entry.get("name") not in ("", ".", "..")
            ]

            used_names: set[str] = set()
            current_uri = uri
            renamed_dirs: list[str] = []
            for entry in visible_entries:
                original_name = entry["name"]
                target_name = self._dedupe_name(
                    original_name,
                    used_names,
                    is_dir=bool(entry.get("isDir")),
                )
                if target_name == original_name:
                    continue
                old_uri = entry.get("uri", f"{current_uri.rstrip('/')}/{original_name}")
                new_uri = f"{current_uri.rstrip('/')}/{target_name}"
                await viking_fs.mv(old_uri, new_uri, ctx=ctx)
                entry["name"] = target_name
                entry["uri"] = new_uri
                if old_uri == current_root_uri:
                    current_root_uri = new_uri
                if entry.get("isDir"):
                    renamed_dirs.append(new_uri)

            for entry in visible_entries:
                if entry.get("isDir"):
                    child_uri = entry.get("uri", f"{uri.rstrip('/')}/{entry['name']}")
                    current_root_uri = await _walk(child_uri, current_root_uri)

            return current_root_uri

        return await _walk(root_uri, root_uri)

    def _get_base_uri(
        self, scope: str, source_path: Optional[str] = None, source_format: Optional[str] = None
    ) -> str:
        """Get base URI for scope, with special handling for media files."""
        # Check if it's a media file first
        if scope == "resources":
            media_type = get_media_type(source_path, source_format)
            if media_type:
                return get_media_base_uri(media_type)
            return "viking://resources"
        if scope == "user":
            # user resources go to memories (no separate resources dir)
            return "viking://user"
        # Agent scope
        return "viking://agent"

    async def _resolve_unique_uri(self, uri: str, max_attempts: int = 100) -> str:
        """Return a URI that does not collide with an existing resource.

        If *uri* is free, return it unchanged.  Otherwise append ``_1``,
        ``_2``, ... until a free name is found.
        """
        viking_fs = get_viking_fs()

        async def _exists(u: str) -> bool:
            try:
                await viking_fs.stat(u)
                return True
            except Exception:
                return False

        if not await _exists(uri):
            return uri

        for i in range(1, max_attempts + 1):
            candidate = f"{uri}_{i}"
            if not await _exists(candidate):
                return candidate

        raise FileExistsError(f"Cannot resolve unique name for {uri} after {max_attempts} attempts")

    # ============================================================================
    # v5.0 Methods (temporary directory + SemanticQueue architecture)
    # ============================================================================

    async def finalize_from_temp(
        self,
        temp_dir_path: str,
        ctx: RequestContext,
        scope: str = "resources",
        to_uri: Optional[str] = None,
        parent_uri: Optional[str] = None,
        source_path: Optional[str] = None,
        source_format: Optional[str] = None,
    ) -> "BuildingTree":
        """
        Finalize processing by moving from temp to AGFS.

        Args:
            to_uri: Exact target URI (must not exist)
            parent_uri: Target parent URI (must exist)
        """

        viking_fs = get_viking_fs()
        temp_uri = temp_dir_path

        def is_resources_root(uri: Optional[str]) -> bool:
            return (uri or "").rstrip("/") == "viking://resources"

        # 1. Find document root directory
        entries = await viking_fs.ls(temp_uri, ctx=ctx)
        doc_dirs = [e for e in entries if e.get("isDir") and e["name"] not in [".", ".."]]

        if len(doc_dirs) != 1:
            logger.error(
                f"[TreeBuilder] Expected 1 document directory in {temp_uri}, found {len(doc_dirs)}"
            )
            raise ValueError(
                f"[TreeBuilder] Expected 1 document directory in {temp_uri}, found {len(doc_dirs)}"
            )

        original_name = doc_dirs[0]["name"]
        temp_doc_uri = f"{temp_uri}/{original_name}"  # use original name to find temp dir
        sanitized_root_name = self._sanitize_name_segment(original_name)
        if sanitized_root_name != original_name:
            new_temp_doc_uri = f"{temp_uri}/{sanitized_root_name}"
            await viking_fs.mv(temp_doc_uri, new_temp_doc_uri, ctx=ctx)
            temp_doc_uri = new_temp_doc_uri
        temp_doc_uri = await self._normalize_temp_tree(temp_doc_uri, ctx)
        doc_name = temp_doc_uri.rstrip("/").split("/")[-1]

        # Check if source_path is a GitHub/GitLab URL and extract org/repo
        final_doc_name = doc_name
        if source_path and source_format == "repository":
            parsed_org_repo = parse_code_hosting_url(source_path)
            if parsed_org_repo:
                final_doc_name = parsed_org_repo

        # 2. Determine base_uri and final document name with org/repo for GitHub/GitLab
        auto_base_uri = self._get_base_uri(scope, source_path, source_format)
        base_uri = parent_uri or auto_base_uri
        use_to_as_parent = is_resources_root(to_uri)
        # 3. Determine candidate_uri
        if to_uri and not use_to_as_parent:
            candidate_uri = to_uri
        else:
            effective_parent_uri = parent_uri or to_uri if use_to_as_parent else parent_uri
            if effective_parent_uri:
                effective_parent_uri = effective_parent_uri.rstrip("/")
                # Parent URI must exist and be a directory
                try:
                    stat_result = await viking_fs.stat(effective_parent_uri, ctx=ctx)
                except Exception as e:
                    raise FileNotFoundError(
                        f"Parent URI does not exist: {effective_parent_uri}"
                    ) from e
                if not stat_result.get("isDir"):
                    raise ValueError(f"Parent URI is not a directory: {effective_parent_uri}")
                base_uri = effective_parent_uri
            candidate_uri = VikingURI(base_uri).join(final_doc_name).uri

        if to_uri and not use_to_as_parent:
            final_uri = candidate_uri
        elif use_to_as_parent:
            # Treat an explicit resources root target as "import under this
            # directory" while preserving the child URI so downstream logic can
            # incrementally update viking://resources/<child> when it exists.
            final_uri = candidate_uri
        else:
            final_uri = await self._resolve_unique_uri(candidate_uri)

        tree = BuildingTree(
            source_path=source_path,
            source_format=source_format,
        )
        tree._root_uri = final_uri
        if not to_uri or use_to_as_parent:
            tree._candidate_uri = candidate_uri

        # Create a minimal Context object for the root so that tree.root is not None
        root_context = Context(uri=final_uri, temp_uri=temp_doc_uri)
        tree.add_context(root_context)

        return tree
