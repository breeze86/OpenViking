# OV Dream Skill Design - OpenViking Memory Sync

## Context

创建 **ov_dream** skill：一个跨平台的 skill 包，可被各种 bot（OpenClaw, OpenCode, ClaudeCode 等）安装使用，将 bot 对话持续同步到 OpenViking 并提取记忆。

**核心需求**：
- 读取 bot 的会话文件
- 上传对话到 OpenViking（add message + session commit）
- 触发记忆提取（由 OpenViking 内部处理）
- 适配不同 bot 的会话存储格式

**实现顺序**：先实现 OpenClaw 支持 → 再扩展其他 bot

---

## Three Operation Modes

### Mode 1: 启用 Cron (Enable)

**触发条件**：
- 用户手动：`"start ov"`、`"启用 dream"`、`"启动记忆同步"`

**执行流程**：
1. 检查 cron jobs 是否存在 dream 任务
2. 不存在则创建 10 分钟周期 cron 任务
3. 返回启用状态和下次同步时间

**Cron 配置**：
```json
// ~/.openclaw/cron/jobs.json
{
  "jobs": [{
    "id": "ov-dream-sync",
    "message": "ov dream",  // 触发 skill 执行同步
    "every_seconds": 600    // 10 分钟
  }]
}
```

### Mode 2: 同步 (Dream)

**触发条件**：
- Cron 触发：`"ov dream"`（每 10 分钟）
- 用户手动：`"ov dream"`、`"同步记忆"`

**执行流程**：
1. 读取当前活跃 session 文件
2. 读取上次同步位置（时间戳或行号）
3. 解析新增消息，调用 OV API 添加
4. 当已发送消息 token 超阈值，触发 commit
5. 更新同步位置

**去重策略**：
- 使用 `timestamp` 字段作为消息唯一标识
- 本地记录 `last_synced_timestamp`

**Commit 阈值**：
- 默认 2000 tokens（可配置）
- 超过阈值调用 `POST /api/v1/sessions/{id}/commit`

### Mode 3: 召回 (Recall)

**触发条件**：
- 用户手动：`"ov recall xxx"`（xxx 是查询内容）

**执行流程**：
1. 解析用户查询（提取 "ov recall" 后面的内容）
2. 调用 OV find API 搜索记忆
3. 返回相关记忆内容

**实现**:
```python
async def recall(query: str, limit: int = 5) -> dict:
    """Search memories in OpenViking.

    Args:
        query: Search query.
        limit: Max results to return.

    Returns:
        Dict with search results.
    """
    url = f"{OV_BASE_URL}/api/v1/search/find"
    payload = {
        "query": query,
        "target_uri": "viking://user/dreams/",
        "limit": limit
    }
    # ... API call
```

---

## Session Format Analysis

### OpenClaw Session 文件格式

**位置**: `~/.openclaw/agents/main/sessions/{session_id}.jsonl`

**每行是一个 JSON 事件**:
```json
// Session 开始
{"type": "session", "version": 3, "id": "39c0eae3-...", "timestamp": "2026-04-15T13:09:45.554Z", "cwd": "/Users/bytedance/clawd"}

// 消息
{"type": "message", "id": "02c11704", "timestamp": "2026-04-15T13:09:45.609Z",
 "message": {"role": "user", "content": [{"type": "text", "text": "你的session文件是存在哪里"}]}}
```

**活跃 Session 判断**:
- 文件名不包含 `.reset.` 或 `.checkpoint.`
- 取最近修改的文件

### Sync State 存储

| Item | Path |
|------|------|
| **状态文件** | `~/.openclaw/memory/ov_dream_sync.json` |
| **格式** | `{"last_synced_timestamp": "...", "last_session_id": "...", "last_commit_at": "..."}` |

### 去重策略

- 使用 `timestamp` 字段作为消息唯一标识
- 只同步 `after_timestamp` 之后的新消息
- Session 切换时重置 timestamp 过滤

---

## Architecture

```
ov_dream skill
├── SKILL.md                    # Skill 定义（3 种模式说明）
├── references/
│   ├── openclaw.md            # OpenClaw 适配器说明
│   ├── opencode.md            # OpenCode 适配器（待实现）
│   └── claude-code.md         # ClaudeCode 适配器（待实现）
├── scripts/
│   ├── dream.py               # 主入口，处理 3 种模式
│   ├── sync.py                # 同步逻辑（SyncEngine）
│   ├── adapters/              # 适配器
│   │   ├── __init__.py
│   │   ├── base.py            # BaseAdapter 抽象类
│   │   └── openclaw.py        # OpenClawAdapter 实现
│   └── config.json            # 配置
└── state/
    └── sync-state.json        # 同步状态
```

### 核心类设计

```python
# adapters/base.py
@dataclass
class Message:
    role: str      # "user" or "assistant"
    content: str
    timestamp: str  # ISO 8601

@dataclass
class Session:
    session_id: str
    cwd: str
    created_at: str

class BaseAdapter(ABC):
    @property
    def name(self) -> str: ...

    def get_active_session(self) -> Optional[Session]: ...

    def parse_messages(self, session_id: str, after_timestamp: Optional[str]) -> Generator[Message]: ...

    def get_session_path(self, session_id: str) -> str: ...

    # 状态管理
    def load_sync_state(self) -> dict: ...
    def save_sync_state(self, state: dict) -> None: ...
```

```python
# sync.py
class SyncEngine:
    def __init__(self, adapter, ov_base_url, commit_threshold=2000):
        ...

    async def sync_session(self, session_id=None, force_commit=False) -> dict:
        # 1. 获取 active session
        # 2. 解析新消息（增量）
        # 3. 调用 OV API add_message
        # 4. Token 计数，达标则 commit
        # 5. 保存同步状态
```

```python
# dream.py (主入口)
async def main():
    # 解析命令: start ov / ov dream / ov recall <query>
    # 路由到对应处理函数
```

### 核心状态

```python
# state/sync-state.json
{
  "last_synced_timestamp": "2026-04-15T21:00:00Z",
  "last_session_id": "39c0eae3-3184-4887-b380-f32288c30504",
  "last_commit_at": "2026-04-15T21:10:00Z"
}
```

---

## Implementation Plan

### Phase 1: 适配器基类 + OpenClaw 适配器

**Files to create**:
1. `examples/skills/ov_dream/scripts/adapters/base.py` — 适配器基类
   - `BaseAdapter` 抽象类
   - `Message`, `Session` 数据类
   - 方法：`get_active_session()`, `parse_messages()`, `get_session_path()`
   - 状态管理：`load_sync_state()`, `save_sync_state()`

2. `examples/skills/ov_dream/scripts/adapters/openclaw.py` — OpenClaw 适配器
   - 实现 `get_active_session()` → 返回最新的 session 文件
   - 实现 `parse_messages(session_id, after_timestamp)` → 生成消息流
   - 实现 `get_session_path(session_id)` → 完整路径
   - 会话目录：`~/.openclaw/agents/main/sessions/`

### Phase 2: 同步逻辑

**Files to create**:
3. `examples/skills/ov_dream/scripts/sync.py` — 同步核心
   - `SyncEngine` 类
   - `sync_session(session_id, force_commit)` 方法
   - Token 计数 + commit 触发逻辑
   - 增量同步（基于 timestamp 去重）

### Phase 3: 主入口

**Files to create**:
4. `examples/skills/ov_dream/scripts/dream.py` — 主入口
   - Mode 1: `enable()` - 检查并创建 cron job
   - Mode 2: `sync()` - 调用 SyncEngine
   - Mode 3: `recall()` - 搜索记忆
   - CLI 参数解析 + 命令路由

### Phase 4: SKILL.md

**Files to create**:
5. `examples/skills/ov_dream/SKILL.md` — Skill 定义
   - name: `ov_dream`
   - description: 对话记忆同步与召回
   - 3 种触发模式说明

6. `examples/skills/ov_dream/references/openclaw.md` — OpenClaw 使用说明

### Phase 5: 配置

**Files to create**:
7. `examples/skills/ov_dream/scripts/config.json` — 配置
   - `target_uri`: `viking://user/dreams/`
   - `commit_threshold`: 2000
   - `sync_interval`: 600（10分钟）
   - `ov_base_url`: `http://127.0.0.1:1933`

### Phase 6: 状态文件

**Files to create**:
8. `examples/skills/ov_dream/state/sync-state.json` — 初始状态文件
   ```json
   {
     "last_synced_timestamp": null,
     "last_session_id": null,
     "last_commit_at": null
   }
   ```

---

## API Integration

### OpenViking Endpoints

```python
# 1. 创建 session（如果不存在，session_id 复用 openclaw 的）
POST /api/v1/sessions
{user_id: "dream", session_id: "<openclaw_session_id>", agent_id: "openclaw"}

# 2. 添加单条消息
POST /api/v1/sessions/{session_id}/messages
{
  "role": "user",
  "content": "对话内容",
  "created_at": "2026-04-15T21:00:00Z"
}

# 3. Commit（触发记忆提取）
POST /api/v1/sessions/{session_id}/commit
{telemetry: false}
# 返回: {"memories_extracted": {"profile": 0, "preferences": 1, ...}}

# 4. 搜索记忆
POST /api/v1/search/find
{
  "query": "用户之前说过什么",
  "target_uri": "viking://user/dreams/",
  "limit": 5
}
```

### Cron Job Integration

**读取/写入位置**: `~/.openclaw/cron/jobs.json`

```json
// 启用后的 jobs.json
{
  "version": 1,
  "jobs": [{
    "id": "ov-dream-sync",
    "message": "ov dream",    // 触发 sync
    "every_seconds": 600      // 10 分钟
  }]
}
```

**Enable 逻辑**:
1. 读取 `~/.openclaw/cron/jobs.json`
2. 检查是否已存在 `id: "ov-dream-sync"` 的 job
3. 不存在则添加 job
4. 写回文件

### Command Summary

| Command | Action | Description |
|---------|--------|-------------|
| `start ov` | Enable | 启用 cron 定时同步 |
| `ov dream` | Sync | 同步当前会话到 OV |
| `ov recall <query>` | Recall | 搜索记忆 |

---

## Key Design Decisions

### 1. Command Format

- `start ov` → 启用 cron（创建 10 分钟定时任务）
- `ov dream` → 同步当前会话
- `ov recall <query>` → 召回记忆

### 2. Session 文件读取策略

- 读取完整的 `.jsonl` 文件
- 使用 `last_synced_timestamp` 记录已同步位置，避免重复上传
- 支持增量同步（只上传新消息）

### 3. 适配器扩展

- 每个 bot 一个适配器类
- 适配器实现统一的接口
- 新增 bot 支持只需添加新适配器

---

## Verification

1. 创建 skill 目录结构
2. 运行 sync 脚本，手动测试：
   ```bash
   python scripts/sync.py --adapter openclaw --session-id <sid>
   ```
3. 验证消息已添加到 OpenViking session
4. 验证 commit 后 memories_extracted > 0
5. 测试增量同步（第二次运行不重复上传）

---

## Future Extensions

- **OpenCode 适配器**：读取 `~/.opencode/sessions/` 目录
- **ClaudeCode 适配器**：读取 `~/.claude/sessions/` 目录
- **自动触发**：通过 hook 或 cron 定期同步