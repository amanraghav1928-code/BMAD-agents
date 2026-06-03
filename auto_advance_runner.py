"""
BMAD Auto-Advance Runner
========================
Watches auto_advance.txt and automatically runs the BMAD pipeline
when run = true is detected.

File format:
    Line 1: run = true   (or false to pause)
    Line 2: Your task/prompt here

Usage:
    python auto_advance_runner.py
"""

import time
import requests
from pathlib import Path

FILE_PATH  = Path(__file__).parent / "auto_advance.txt"
API_URL    = "https://bmad-agent-api-production.up.railway.app/v1/chat/completions"
POLL_SECS  = 5   # check every 5 seconds

def read_file():
    """Read auto_advance.txt and return (run_flag, task)."""
    if not FILE_PATH.exists():
        return False, ""
    lines = FILE_PATH.read_text().strip().splitlines()
    if len(lines) < 2:
        return False, ""
    run_flag = lines[0].split("=")[-1].strip().lower() == "true"
    task = lines[1].strip()
    return run_flag, task

def set_run_false():
    """After running, set run = false so it doesn't repeat."""
    lines = FILE_PATH.read_text().splitlines()
    lines[0] = "run = false"
    FILE_PATH.write_text("\n".join(lines) + "\n")
    print("  → Set run = false (task complete)")

def run_task(task: str):
    """Send task to BMAD API and print result."""
    print(f"\n🚀 Auto-advancing with task: '{task}'")
    try:
        response = requests.post(
            API_URL,
            json={
                "model": "bmad-agent",
                "messages": [{"role": "user", "content": task}],
                "stream": False
            },
            timeout=300
        )
        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ Done!\n{content}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("👀 BMAD Auto-Advance watching auto_advance.txt...")
    print(f"   File: {FILE_PATH}")
    print(f"   Polling every {POLL_SECS}s — set run = true to trigger\n")

    last_task = ""

    while True:
        run_flag, task = read_file()

        if run_flag and task and task != last_task:
            success = run_task(task)
            if success:
                last_task = task
                set_run_false()

        time.sleep(POLL_SECS)

if __name__ == "__main__":
    main()
