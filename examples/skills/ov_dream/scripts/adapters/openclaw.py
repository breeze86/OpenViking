"""OpenClaw adapter for session integration."""

import json
import os
from datetime import datetime
from typing import Generator, Optional

from .base import BaseAdapter, Message, Session


class OpenClawAdapter(BaseAdapter):
    """Adapter for OpenClaw bot sessions."""

    SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")

    @property
    def name(self) -> str:
        return "openclaw"

    def get_active_session(self) -> Optional[Session]:
        """Get the current active session.

        Returns the most recent session file that doesn't have .reset. suffix.
        """
        if not os.path.exists(self.SESSIONS_DIR):
            return None

        sessions = []
        for f in os.listdir(self.SESSIONS_DIR):
            # Skip reset files and checkpoint files
            if ".reset." in f or ".checkpoint." in f:
                continue
            if not f.endswith(".jsonl"):
                continue

            # Extract session ID from filename
            session_id = f.replace(".jsonl", "")
            filepath = os.path.join(self.SESSIONS_DIR, f)
            mtime = os.path.getmtime(filepath)
            sessions.append((session_id, mtime, filepath))

        if not sessions:
            return None

        # Sort by modification time, most recent first
        sessions.sort(key=lambda x: x[1], reverse=True)
        session_id, _, filepath = sessions[0]

        # Read session metadata from first line
        with open(filepath, 'r') as f:
            first_line = f.readline()
            if not first_line:
                return None
            try:
                data = json.loads(first_line)
                if data.get("type") == "session":
                    return Session(
                        session_id=session_id,
                        cwd=data.get("cwd", ""),
                        created_at=data.get("timestamp", "")
                    )
            except json.JSONDecodeError:
                pass

        return Session(session_id=session_id, cwd="", created_at="")

    def parse_messages(
        self,
        session_id: str,
        after_timestamp: Optional[str] = None
    ) -> Generator[Message, None, None]:
        """Parse messages from a session file.

        Args:
            session_id: The session ID to read from.
            after_timestamp: Only return messages after this timestamp.

        Yields:
            Message objects.
        """
        filepath = self.get_session_path(session_id)
        if not os.path.exists(filepath):
            return

        after_dt = None
        if after_timestamp:
            try:
                after_dt = datetime.fromisoformat(after_timestamp.replace('Z', '+00:00'))
            except ValueError:
                pass

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only process message type
                if data.get("type") != "message":
                    continue

                msg = data.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                # Extract content
                content_parts = msg.get("content", [])
                content = ""
                if isinstance(content_parts, list):
                    for part in content_parts:
                        if part.get("type") == "text":
                            content += part.get("text", "")
                elif isinstance(content_parts, str):
                    content = content_parts

                if not content:
                    continue

                # Check timestamp filter
                msg_timestamp = data.get("timestamp", "")
                if after_dt and msg_timestamp:
                    try:
                        msg_dt = datetime.fromisoformat(msg_timestamp.replace('Z', '+00:00'))
                        if msg_dt <= after_dt:
                            continue
                    except ValueError:
                        pass

                yield Message(
                    role=role,
                    content=content,
                    timestamp=msg_timestamp
                )

    def get_session_path(self, session_id: str) -> str:
        """Get the full path to a session file.

        Args:
            session_id: The session ID.

        Returns:
            Full path to the session file.
        """
        return os.path.join(self.SESSIONS_DIR, f"{session_id}.jsonl")

    def get_state_dir(self) -> str:
        """Get the directory for storing sync state."""
        state_dir = os.path.expanduser("~/.openclaw/memory")
        os.makedirs(state_dir, exist_ok=True)
        return state_dir

    def get_state_file(self) -> str:
        """Get the path to the sync state file."""
        return os.path.join(self.get_state_dir(), "ov_dream_sync.json")

    def load_sync_state(self) -> dict:
        """Load sync state from file."""
        import json
        state_file = self.get_state_file()
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
        return {
            "last_synced_timestamp": None,
            "last_session_id": None,
            "last_commit_at": None
        }

    def save_sync_state(self, state: dict) -> None:
        """Save sync state to file."""
        import json
        state_file = self.get_state_file()
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)