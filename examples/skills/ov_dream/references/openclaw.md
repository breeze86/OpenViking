# OpenClaw Adapter

This document describes how the OV Dream skill integrates with OpenClaw.

## Session Storage

OpenClaw stores session data in:
```
~/.openclaw/agents/main/sessions/
```

### File Naming Convention

| File Type | Pattern | Example |
|-----------|---------|---------|
| Active Session | `{session_id}.jsonl` | `39c0eae3-3184-4887-b380-f32288c30504.jsonl` |
| Checkpoint | `{session_id}.checkpoint.{uuid}.jsonl` | `39c0eae3....checkpoint.abc123.jsonl` |
| Reset | `{session_id}.jsonl.reset.{timestamp}` | `39c0eae3....jsonl.reset.2026-04-15T13-09-44.623Z` |

### Active Session Detection

The adapter considers a session "active" if:
1. Filename ends with `.jsonl`
2. Does NOT contain `.checkpoint.`
3. Does NOT contain `.reset.`

## Session File Format

Each line is a JSON event:

```json
// Session start event
{
  "type": "session",
  "version": 3,
  "id": "39c0eae3-3184-4887-b380-f32288c30504",
  "timestamp": "2026-04-15T13:09:45.554Z",
  "cwd": "/Users/bytedance/clawd"
}

// Model change event
{
  "type": "model_change",
  "id": "95d64c99",
  "parentId": null,
  "timestamp": "2026-04-15T13:09:45.577Z",
  "provider": "volcengine",
  "modelId": "doubao-seed-2-0-mini-260215"
}

// Message event (user)
{
  "type": "message",
  "id": "02c11704",
  "parentId": "76cdcffe",
  "timestamp": "2026-04-15T13:09:45.609Z",
  "message": {
    "role": "user",
    "content": [
      {"type": "text", "text": "你的session文件是存在哪里"}
    ]
  }
}

// Message event (assistant)
{
  "type": "message",
  "id": "02c11705",
  "parentId": "02c11704",
  "timestamp": "2026-04-15T13:09:46.123Z",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "text", "text": "Session 文件存放在 ~/.openclaw/agents/main/sessions/ 目录下"}
    ],
    "thinking": "...",
    "tool_calls": [...]
  }
}
```

## Message Extraction

The adapter extracts messages from session files:

1. Filter events with `type == "message"`
2. Extract `message.role` (user/assistant)
3. Extract content from `message.content` array (join all text parts)
4. Use event `timestamp` for deduplication

## Sync State Location

Sync state is stored at:
```
~/.openclaw/memory/ov_dream_sync.json
```

This is shared with the openviking-memory plugin to avoid conflicts.

## Cron Integration

The skill reads/writes cron jobs at:
```
~/.openclaw/cron/jobs.json
```

Example enabled state:
```json
{
  "version": 1,
  "jobs": [
    {
      "id": "ov-dream-sync",
      "message": "ov dream",
      "every_seconds": 600
    }
  ]
}
```

## Relationship with openviking-memory Plugin

The OV Dream skill is designed to work alongside the openviking-memory plugin:

| Feature | openviking-memory Plugin | OV Dream Skill |
|---------|-------------------------|----------------|
| Sync Trigger | `afterTurn` hook | Cron (10 min) |
| Sync Scope | Incremental (each turn) | Batch (all new messages) |
| Commit Trigger | Token threshold | Token threshold |
| Use Case | Real-time sync | Periodic batch sync |

Both can run simultaneously - they use the same sync state file to avoid duplicate syncs.