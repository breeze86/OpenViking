---
name: ov_dream
description: |
  OpenViking memory sync skill for bot conversations.
  Use when:
  (1) User wants to enable automatic memory sync with "start ov"
  (2) Cron triggers sync with "ov dream"
  (3) User wants to recall memories with "ov recall <query>"
  This skill syncs bot conversations to OpenViking and triggers memory extraction.
---

# OV Dream

OpenViking memory sync skill that continuously uploads bot conversations to OpenViking for memory extraction.

## Commands

### 1. Enable (start ov)

Enable periodic sync via cron job.

```bash
start ov
```

Creates a cron job that runs every 10 minutes to sync the current session.

**Result:**
```json
{
  "status": "enabled",
  "message": "OV Dream cron job enabled (every 10 minutes)",
  "sync_interval": 600
}
```

### 2. Sync (ov dream)

Sync current session messages to OpenViking.

```bash
ov dream
```

**Flow:**
1. Read current active session file
2. Parse new messages (incremental, based on timestamp)
3. Add messages to OpenViking session
4. When token count exceeds threshold (default 2000), trigger commit
5. Update sync state

**Result:**
```json
{
  "session_id": "39c0eae3-...",
  "messages_synced": 5,
  "commit_triggered": true,
  "commit_result": {
    "success": true,
    "memories_extracted": {"profile": 0, "preferences": 2, "entities": 1}
  }
}
```

### 3. Recall (ov recall)

Search memories from OpenViking.

```bash
ov recall what did I say about python
```

**Parameters:**
- `query`: Search query (required)
- `limit`: Max results (default: 5)

**Result:**
```json
{
  "status": "success",
  "query": "what did I say about python",
  "results": [
    {"uri": "viking://user/dreams/...", "content": "...", "score": 0.95}
  ]
}
```

## How It Works

### Session File Format

OpenClaw sessions are stored at:
```
~/.openclaw/agents/main/sessions/{session_id}.jsonl
```

Each line is a JSON event:
```json
{"type": "message", "timestamp": "2026-04-15T21:00:00Z",
 "message": {"role": "user", "content": [{"type": "text", "text": "Hello"}]}}
```

### Sync State

Sync state is stored at:
```
~/.openclaw/memory/ov_dream_sync.json
```

```json
{
  "last_synced_timestamp": "2026-04-15T21:00:00Z",
  "last_session_id": "39c0eae3-...",
  "last_commit_at": "2026-04-15T21:10:00Z"
}
```

### Deduplication

- Uses `timestamp` field as message unique identifier
- Only syncs messages after `last_synced_timestamp`
- When session changes, resets timestamp filter

## Configuration

Edit `scripts/config.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `ov_base_url` | `http://127.0.0.1:1933` | OpenViking server URL |
| `commit_threshold` | `2000` | Token threshold to trigger commit |
| `target_uri` | `viking://user/dreams/` | Default search scope |

## Requirements

- OpenViking server running at configured URL
- Write access to `~/.openclaw/cron/jobs.json` (for enable)
- Write access to `~/.openclaw/memory/` (for sync state)