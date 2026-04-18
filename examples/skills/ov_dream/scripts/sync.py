"""Synchronization logic for uploading bot sessions to OpenViking."""

import asyncio
import os
from typing import Generator, Optional

from adapters.base import Message
from adapters.openclaw import OpenClawAdapter


class SyncEngine:
    """Handles session synchronization to OpenViking."""

    def __init__(
        self,
        adapter: OpenClawAdapter,
        ov_base_url: str = "http://127.0.0.1:1933",
        commit_threshold: int = 2000
    ):
        self.adapter = adapter
        self.ov_base_url = ov_base_url
        self.commit_threshold = commit_threshold
        self._token_count = 0

    async def sync_session(
        self,
        session_id: Optional[str] = None,
        force_commit: bool = False
    ) -> dict:
        """Sync messages from the active session to OpenViking.

        Args:
            session_id: Specific session to sync. If None, uses active session.
            force_commit: If True, force commit even if below threshold.

        Returns:
            Dict with sync results (messages_synced, commit_triggered, etc.)
        """
        # Get session
        if session_id:
            active_session = self.adapter.get_active_session()
            if not active_session or active_session.session_id != session_id:
                return {"error": f"Session {session_id} not found"}
            target_session_id = session_id
        else:
            active_session = self.adapter.get_active_session()
            if not active_session:
                return {"error": "No active session found"}
            target_session_id = active_session.session_id

        # Load sync state
        state = self.adapter.load_sync_state()

        # Check if session changed
        last_session_id = state.get("last_session_id")
        last_timestamp = state.get("last_synced_timestamp")

        # If session changed, reset the timestamp filter
        if last_session_id != target_session_id:
            last_timestamp = None

        # Parse new messages
        new_messages = list(self.adapter.parse_messages(
            target_session_id,
            after_timestamp=last_timestamp
        ))

        if not new_messages:
            return {
                "session_id": target_session_id,
                "messages_synced": 0,
                "commit_triggered": False,
                "message": "No new messages to sync"
            }

        # Add messages to OpenViking
        messages_added = await self._add_messages(target_session_id, new_messages)

        # Update state
        latest_timestamp = new_messages[-1].timestamp if new_messages else last_timestamp
        state["last_synced_timestamp"] = latest_timestamp
        state["last_session_id"] = target_session_id
        self.adapter.save_sync_state(state)

        # Check if should commit
        should_commit = force_commit or self._token_count >= self.commit_threshold
        commit_result = None

        if should_commit:
            commit_result = await self._commit_session(target_session_id)
            state["last_commit_at"] = commit_result.get("committed_at")
            state["last_synced_timestamp"] = latest_timestamp
            self.adapter.save_sync_state(state)
            self._token_count = 0

        return {
            "session_id": target_session_id,
            "messages_synced": messages_added,
            "commit_triggered": should_commit,
            "commit_result": commit_result,
            "token_count": self._token_count
        }

    async def _add_messages(self, session_id: str, messages: list[Message]) -> int:
        """Add messages to OpenViking via API.

        Args:
            session_id: The session ID.
            messages: List of messages to add.

        Returns:
            Number of messages added.
        """
        import aiohttp

        url = f"{self.ov_base_url}/api/v1/sessions/{session_id}/messages"

        async with aiohttp.ClientSession() as session:
            for msg in messages:
                payload = {
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.timestamp
                }
                try:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            self._token_count += len(msg.content) // 4  # rough token estimate
                        else:
                            print(f"Failed to add message: {resp.status}")
                except Exception as e:
                    print(f"Error adding message: {e}")

        return len(messages)

    async def _commit_session(self, session_id: str) -> dict:
        """Commit session to trigger memory extraction.

        Args:
            session_id: The session ID.

        Returns:
            Commit result dict.
        """
        import aiohttp
        from datetime import datetime

        url = f"{self.ov_base_url}/api/v1/sessions/{session_id}/commit"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json={"telemetry": False}) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return {
                            "success": True,
                            "committed_at": datetime.utcnow().isoformat() + "Z",
                            "memories_extracted": result.get("memories_extracted", 0)
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Commit failed: {resp.status}"
                        }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e)
                }


async def run_sync(adapter_name: str = "openclaw") -> dict:
    """Run sync for the specified adapter.

    Args:
        adapter_name: Name of the adapter to use.

    Returns:
        Sync result dict.
    """
    if adapter_name == "openclaw":
        adapter = OpenClawAdapter()
    else:
        raise ValueError(f"Unknown adapter: {adapter_name}")

    engine = SyncEngine(adapter)
    return await engine.sync_session()


if __name__ == "__main__":
    result = asyncio.run(run_sync())
    print(result)