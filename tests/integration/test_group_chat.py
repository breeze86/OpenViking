#!/usr/bin/env python3
"""
OpenViking 记忆演示脚本 — 群聊场景（3人聊天记录）
"""

import argparse
import time
from datetime import datetime

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import openviking as ov

# ── 常量 ───────────────────────────────────────────────────────────────────

DISPLAY_NAME = "群聊测试"
DEFAULT_URL = "http://localhost:1934"
PANEL_WIDTH = 78
DEFAULT_API_KEY = "1cf407c39990e5dc874ccc697942da4892208a86a44c4781396dfdc57aa5c98d"
DEFAULT_AGENT_ID = "test"
DEFAULT_SESSION_ID = "group-chat-demo"

# 群聊成员配置
MEMBERS = {
    "xiaoming": {"name": "小明", "role": "user"},
    "xiaohong": {"name": "小红", "role": "user"},
    "xiaohua": {"name": "小华", "role": "user"},
}

console = Console()

# ── 对话数据 (群聊，3人交叉对话) ───────────────────────────────────────────

CONVERSATION = [
    # 第1轮：自我介绍
    {
        "role_id": "xiaoming",
        "role": "user",
        "content": "大家好！我是小明，在字节做前端开发，刚入职三个月。",
    },
    {
        "role_id": "xiaohong",
        "role": "user",
        "content": "小明好！我是小红，在阿里做后端，工作两年了。",
    },
    {
        "role_id": "xiaohua",
        "role": "user",
        "content": "你们好！我是小华，在腾讯做产品，搬砖三年了。",
    },
    # 第2轮：讨论技术
    {
        "role_id": "xiaoming",
        "role": "user",
        "content": "最近在学 React，最近在做的一个项目用到了 hooks，还有 TypeScript，感觉比 JS 顺手多了。",
    },
    {
        "role_id": "xiaohong",
        "role": "user",
        "content": "我也想学 React，之前都是用 Vue。我们后端主要用 Java，还有 Go 微服务。",
    },
    {
        "role_id": "xiaohua",
        "role": "user",
        "content": "产品角度来说，我比较关心前端性能用户体验。小明你们页面首屏加载多久？",
    },
    # 第3轮：分享饮食偏好
    {
        "role_id": "xiaohong",
        "role": "user",
        "content": "中午吃啥啊？我比较喜欢川菜，麻辣香锅、水煮鱼我都爱吃，但不敢吃太辣的。",
    },
    {
        "role_id": "xiaoming",
        "role": "user",
        "content": "我胃不好，吃不了辣的。喜欢清淡的粤菜，比如白切鸡、蒸鱼。对了，我芒果过敏，大家点外卖注意点。",
    },
    {
        "role_id": "xiaohua",
        "role": "user",
        "content": "我什么都吃，不挑食哈哈。今天和小红去吃那家新开的粤菜馆吧？",
    },
    # 第4轮：运动和周末
    {
        "role_id": "xiaohua",
        "role": "user",
        "content": "这周末有啥安排吗？我想打羽毛球，缺人。",
    },
    {
        "role_id": "xiaoming",
        "role": "user",
        "content": "我周末要加班，最近赶需求。不过晚上可以出来打一小时。",
    },
    {
        "role_id": "xiaohong",
        "role": "user",
        "content": "我可以！周末刚好有时间。打完球一起去吃个夜宵？",
    },
    # 第5轮：个人习惯
    {
        "role_id": "xiaoming",
        "role": "user",
        "content": "我每天睡前都会喝一杯热牛奶，不然睡不着。",
    },
    {
        "role_id": "xiaohong",
        "role": "user",
        "content": "我习惯睡前看半小时书，最近在看《活着》，哭死我了。",
    },
    {
        "role_id": "xiaohua",
        "role": "user",
        "content": "我睡不着就刷抖音，经常一刷就停不下来，导致第二天迟到哈哈。",
    },
]

# ── 验证查询 ──────────────────────────────────────────────────────────────

VERIFY_QUERIES = [
    {
        "query": "小明的技术栈",
        "expected_keywords": ["React", "TypeScript", "hooks", "前端"],
        "expected_role": "xiaoming",
    },
    {
        "query": "小明的饮食禁忌",
        "expected_keywords": ["芒果过敏", "胃不好", "清淡", "粤菜"],
        "expected_role": "xiaoming",
    },
    {
        "query": "小红的饮食习惯",
        "expected_keywords": ["川菜", "麻辣", "水煮鱼"],
        "expected_role": "xiaohong",
    },
    {
        "query": "小华的爱好和习惯",
        "expected_keywords": ["羽毛球", "刷抖音", "夜宵"],
        "expected_role": "xiaohua",
    },
    {
        "query": "前端开发是谁",
        "expected_keywords": ["小明", "前端", "React"],
        "expected_role": None,
    },
]


# ── Phase 1: 写入对话并提交 ────────────────────────────────────────────────


def run_ingest(client: ov.SyncHTTPClient, session_id: str, wait_seconds: float):
    console.print()
    console.rule(f"[bold]Phase 1: 写入群聊对话 — {DISPLAY_NAME} ({len(CONVERSATION)} 条消息)[/bold]")

    # 获取 session；若不存在则由服务端按 session_id 自动创建
    session = client.create_session()
    session_id = session.get("session_id")
    print(f"session_id={session_id}")
    console.print(f"  Session: [bold cyan]{session_id}[/bold cyan]")
    console.print()

    # 设置一个测试用的会话时间（2023年4月2日）
    session_time = datetime(2023, 4, 2, 14, 30)
    session_time_str = session_time.isoformat()

    # 逐条添加消息
    total = len(CONVERSATION)
    for i, msg in enumerate(CONVERSATION, 1):
        role_id = msg.get("role_id")
        member_name = MEMBERS.get(role_id, {}).get("name", role_id)
        console.print(
            f"  [{i}/{total}] 添加 [{member_name}] 的消息..."
        )
        client.add_message(
            session_id,
            role=msg["role"],
            content=msg["content"],
            created_at=session_time_str,
            role_id=role_id,
        )

    console.print()
    console.print(f"  共添加 [bold]{total}[/bold] 条消息")

    # 提交 session — 触发记忆抽取
    console.print()
    console.print("  [yellow]提交 Session（触发记忆抽取）...[/yellow]")
    commit_result = client.commit_session(session_id)
    task_id = commit_result.get("task_id")
    trace_id = commit_result.get("trace_id")
    console.print(f"  [bold cyan]trace_id: {trace_id}[/bold cyan]")
    console.print(f"  Commit 结果: {commit_result}")

    # 轮询后台任务直到完成
    if task_id:
        now = time.time()
        console.print(f"  [yellow]等待记忆提取完成 (task_id={task_id})...[/yellow]")
        while True:
            task = client.get_task(task_id)
            if not task or task.get("status") in ("completed", "failed"):
                break
            time.sleep(1)
        elapsed = time.time() - now
        status = task.get("status", "unknown") if task else "not found"
        console.print(f"  [green]任务 {status}，耗时 {elapsed:.2f}s[/green]")
        console.print(f"  Task 详情: {task}")

    # 等待向量化队列处理完成
    console.print(f"  [yellow]等待向量化完成...[/yellow]")
    client.wait_processed()

    if wait_seconds > 0:
        console.print(f"  [dim]额外等待 {wait_seconds:.0f}s...[/dim]")
        time.sleep(wait_seconds)

    session_info = client.get_session(session_id)
    console.print(f"  Session 详情: {session_info}")

    return session_id


# ── Phase 2: 验证记忆召回 ─────────────────────────────────────────────────


def run_verify(client: ov.SyncHTTPClient):
    console.print()
    console.rule(
        f"[bold]Phase 2: 验证记忆召回 — {DISPLAY_NAME} ({len(VERIFY_QUERIES)} 条查询)[/bold]"
    )

    results_table = Table(
        title=f"记忆召回验证 — {DISPLAY_NAME}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
    )
    results_table.add_column("#", style="bold", width=4)
    results_table.add_column("查询", style="cyan", max_width=25)
    results_table.add_column("召回数", justify="center", width=8)
    results_table.add_column("命中关键词", style="green")
    results_table.add_column("涉及成员", style="yellow")

    total = len(VERIFY_QUERIES)
    for i, item in enumerate(VERIFY_QUERIES, 1):
        query = item["query"]
        expected = item["expected_keywords"]

        console.print(f"\n  [dim][{i}/{total}][/dim] 搜索: [cyan]{query}[/cyan]")
        console.print(f"  [dim]期望关键词: {', '.join(expected)}[/dim]")

        try:
            results = client.find(query, limit=5)

            # 收集所有召回内容
            recall_texts = []
            count = 0
            if hasattr(results, "memories") and results.memories:
                for m in results.memories:
                    text = getattr(m, "content", "") or getattr(m, "text", "") or str(m)
                    print(f"  [DEBUG] memory text: {repr(text)}")
                    recall_texts.append(text)
                    uri = getattr(m, "uri", "")
                    score = getattr(m, "score", 0)
                    console.print(f"    [green]Memory:[/green] {uri} (score: {score:.4f})")
                    console.print(
                        f"    [dim]{text[:120]}...[/dim]"
                        if len(text) > 120
                        else f"    [dim]{text}[/dim]"
                    )
                count += len(results.memories)

            if hasattr(results, "resources") and results.resources:
                for r in results.resources:
                    text = getattr(r, "content", "") or getattr(r, "text", "") or str(r)
                    print(f"  [DEBUG] resource text: {repr(text)}")
                    recall_texts.append(text)
                    console.print(f"    [blue]Resource:[/blue] {r.uri} (score: {r.score:.4f})")
                count += len(results.resources)

            if hasattr(results, "skills") and results.skills:
                count += len(results.skills)

            # 检查关键词命中
            all_text = " ".join(recall_texts)
            hits = [kw for kw in expected if kw in all_text]
            hit_str = ", ".join(hits) if hits else "[dim]无[/dim]"

            # 检查涉及哪个成员
            involved_members = []
            for member_id, member_info in MEMBERS.items():
                if member_info["name"] in all_text or member_id in all_text:
                    involved_members.append(member_info["name"])
            member_str = ", ".join(involved_members) if involved_members else "[dim]待定[/dim]"

            results_table.add_row(str(i), query, str(count), hit_str, member_str)

        except Exception as e:
            console.print(f"    [red]ERROR: {e}[/red]")
            results_table.add_row(str(i), query, "[red]ERR[/red]", str(e)[:40], "[red]ERR[/red]")

    console.print()
    console.print(results_table)


# ── 入口 ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=f"OpenViking 记忆演示 — {DISPLAY_NAME}")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Server URL (默认: {DEFAULT_URL})")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key")
    parser.add_argument("--agent-id", default=DEFAULT_AGENT_ID, help="Agent ID")
    parser.add_argument(
        "--phase",
        choices=["all", "ingest", "verify"],
        default="all",
        help="all=全部, ingest=仅写入, verify=仅验证 (默认: all)",
    )
    parser.add_argument(
        "--session-id", default=DEFAULT_SESSION_ID, help=f"Session ID (默认: {DEFAULT_SESSION_ID})"
    )
    parser.add_argument("--wait", type=float, default=5.0, help="提交后额外等待秒数 (默认: 5)")
    args = parser.parse_args()

    console.print(
        Panel(
            f"[bold]OpenViking 记忆演示 — {DISPLAY_NAME}[/bold]\n"
            f"Server: {args.url}  |  Phase: {args.phase}\n"
            f"群聊成员: {', '.join(m['name'] for m in MEMBERS.values())}",
            style="magenta",
            width=PANEL_WIDTH,
        )
    )

    client = ov.SyncHTTPClient(
        url=args.url, api_key=args.api_key, agent_id=args.agent_id, timeout=180
    )

    try:
        client.initialize()
        console.print(f"  [green]已连接[/green] {args.url}")

        if args.phase in ("all", "ingest"):
            run_ingest(client, session_id=args.session_id, wait_seconds=args.wait)

        if args.phase in ("all", "verify"):
            run_verify(client)

        console.print(
            Panel(
                "[bold green]演示完成[/bold green]",
                style="green",
                width=PANEL_WIDTH,
            )
        )

    except Exception as e:
        console.print(Panel(f"[bold red]Error:[/bold red] {e}", style="red", width=PANEL_WIDTH))
        import traceback

        traceback.print_exc()

    finally:
        client.close()


if __name__ == "__main__":
    main()