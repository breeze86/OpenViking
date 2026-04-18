#!/usr/bin/env python3
"""OV Dream - OpenViking Memory Sync Skill.

This skill handles three modes:
- start ov: Enable cron job for periodic sync
- ov dream: Sync current session to OpenViking
- ov recall <query>: Search memories from OpenViking
"""

import argparse
import asyncio
import json
import os
import sys

from sync import SyncEngine
from adapters.openclaw import OpenClawAdapter


# Configuration
DEFAULT_OV_BASE_URL = "http://127.0.0.1:1933"
CRON_JOBS_FILE = os.path.expanduser("~/.openclaw/cron/jobs.json")
DEFAULT_COMMIT_THRESHOLD = 2000
DEFAULT_TARGET_URI = "viking://user/dreams/"


def load_config() -> dict:
    """Load configuration from config.json."""
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {
        "ov_base_url": DEFAULT_OV_BASE_URL,
        "commit_threshold": DEFAULT_COMMIT_THRESHOLD,
        "target_uri": DEFAULT_TARGET_URI
    }


def cmd_enable() -> dict:
    """Enable cron job for periodic sync.

    Returns:
        Dict with result status.
    """
    # Load existing jobs
    jobs = {"version": 1, "jobs": []}
    if os.path.exists(CRON_JOBS_FILE):
        with open(CRON_JOBS_FILE, 'r') as f:
            jobs = json.load(f)

    # Check if dream sync job already exists
    job_exists = any(
        job.get("id") == "ov-dream-sync"
        for job in jobs.get("jobs", [])
    )

    if job_exists:
        return {
            "status": "already_enabled",
            "message": "OV Dream cron job already enabled",
            "sync_interval": 600  # 10 minutes
        }

    # Add new job
    jobs["jobs"].append({
        "id": "ov-dream-sync",
        "message": "ov dream",
        "every_seconds": 600  # 10 minutes
    })

    # Save jobs
    os.makedirs(os.path.dirname(CRON_JOBS_FILE), exist_ok=True)
    with open(CRON_JOBS_FILE, 'w') as f:
        json.dump(jobs, f, indent=2)

    return {
        "status": "enabled",
        "message": "OV Dream cron job enabled (every 10 minutes)",
        "sync_interval": 600
    }


async def cmd_sync(adapter_name: str = "openclaw") -> dict:
    """Sync current session to OpenViking.

    Args:
        adapter_name: Name of the adapter to use.

    Returns:
        Dict with sync results.
    """
    config = load_config()

    if adapter_name == "openclaw":
        adapter = OpenClawAdapter()
    else:
        return {"error": f"Unknown adapter: {adapter_name}"}

    engine = SyncEngine(
        adapter=adapter,
        ov_base_url=config.get("ov_base_url", DEFAULT_OV_BASE_URL),
        commit_threshold=config.get("commit_threshold", DEFAULT_COMMIT_THRESHOLD)
    )

    result = await engine.sync_session()
    return result


async def cmd_recall(query: str, limit: int = 5) -> dict:
    """Search memories from OpenViking.

    Args:
        query: Search query.
        limit: Max results to return.

    Returns:
        Dict with search results.
    """
    import aiohttp

    config = load_config()
    ov_base_url = config.get("ov_base_url", DEFAULT_OV_BASE_URL)
    target_uri = config.get("target_uri", DEFAULT_TARGET_URI)

    url = f"{ov_base_url}/api/v1/search/find"
    payload = {
        "query": query,
        "target_uri": target_uri,
        "limit": limit
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return {
                        "status": "success",
                        "query": query,
                        "results": result.get("results", [])
                    }
                else:
                    return {
                        "status": "error",
                        "error": f"Search failed: {resp.status}"
                    }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def parse_command(user_input: str) -> tuple[str, dict]:
    """Parse user input into command and args.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of (command, args_dict).
    """
    user_input = user_input.strip().lower()

    # start ov -> enable
    if user_input == "start ov":
        return "enable", {}

    # ov dream -> sync
    if user_input == "ov dream":
        return "sync", {}

    # ov recall <query> -> recall
    if user_input.startswith("ov recall "):
        query = user_input[10:].strip()  # Remove "ov recall " prefix
        return "recall", {"query": query}

    # Default: unknown
    return "unknown", {}


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="OV Dream - OpenViking Memory Sync")
    parser.add_argument("command", nargs="?", help="Command: enable, sync, or recall <query>")
    parser.add_argument("--adapter", default="openclaw", help="Adapter name (default: openclaw)")
    parser.add_argument("--query", "-q", help="Query for recall command")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Max results for recall")

    args = parser.parse_args()

    # If no command provided, check sys.argv for backward compatibility
    if not args.command and len(sys.argv) > 1:
        command_input = sys.argv[1]
    elif args.command:
        command_input = args.command
    else:
        parser.print_help()
        return

    # Handle recall with --query flag
    if args.query:
        result = await cmd_recall(args.query, args.limit)
        print(json.dumps(result, indent=2))
        return

    # Parse command
    command, cmd_args = parse_command(command_input)

    if command == "enable":
        result = cmd_enable()
        print(json.dumps(result, indent=2))

    elif command == "sync":
        result = await cmd_sync(args.adapter)
        print(json.dumps(result, indent=2))

    elif command == "recall":
        query = cmd_args.get("query", "")
        if not query:
            print(json.dumps({"error": "Missing query for recall"}, indent=2))
            return
        result = await cmd_recall(query, args.limit)
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps({
            "error": f"Unknown command: {command_input}",
            "usage": {
                "start ov": "Enable cron job for periodic sync",
                "ov dream": "Sync current session to OpenViking",
                "ov recall <query>": "Search memories from OpenViking"
            }
        }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())