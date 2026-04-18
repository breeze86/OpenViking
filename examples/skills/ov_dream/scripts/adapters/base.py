"""Base adapter for bot session integration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generator, Optional
import os


@dataclass
class Message:
    """Represents a message from the bot session."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str  # ISO 8601 format


@dataclass
class Session:
    """Represents a bot session."""
    session_id: str
    cwd: str
    created_at: str


class BaseAdapter(ABC):
    """Abstract base class for bot session adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Adapter name (e.g., 'openclaw', 'opencode')."""
        pass

    @abstractmethod
    def get_active_session(self) -> Optional[Session]:
        """Get the current active session.

        Returns:
            Session object or None if no active session.
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_session_path(self, session_id: str) -> str:
        """Get the full path to a session file.

        Args:
            session_id: The session ID.

        Returns:
            Full path to the session file.
        """
        pass

    def get_state_dir(self) -> str:
        """Get the directory for storing sync state.

        Returns:
            Path to state directory.
        """
        state_dir = os.path.expanduser("~/.openclaw/memory")
        os.makedirs(state_dir, exist_ok=True)
        return state_dir

    def get_state_file(self) -> str:
        """Get the path to the sync state file.

        Returns:
            Path to sync-state.json.
        """
        return os.path.join(self.get_state_dir(), "ov_dream_sync.json")

    def load_sync_state(self) -> dict:
        """Load sync state from file.

        Returns:
            Dict with last_synced_timestamp, last_session_id, last_commit_at.
        """
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
        """Save sync state to file.

        Args:
            state: Dict with sync state.
        """
        import json
        state_file = self.get_state_file()
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)