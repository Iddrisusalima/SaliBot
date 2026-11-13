"""
Terminal test for the agent, without the web page.

Usage:
    python scripts/test_agent.py
"""

# Run from anywhere: work from the project folder so imports and data/ paths resolve
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


from agent import get_agent
from langchain_core.messages import SystemMessage, HumanMessage
from database import init_db

# SaliBot: show emojis and special characters correctly in the Windows terminal
sys.stdout.reconfigure(encoding="utf-8")

init_db()

agent =get_agent("gemini-3.5-flash")


def chunk_text(content) -> str:
    """
    SaliBot fix: newer Gemini models send text as a list of "parts"
    like [{'type': 'text', 'text': 'Hello'}]. This pulls out just the text.
    """
    if isinstance(content, str):
        return content

    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in content
    )


config = {
    "configurable": {
        "thread_id": "test_thread_id",
    }
}


for message_chunk, metadata in agent.stream(
    {'messages': [HumanMessage(content="What is My name?")]},
    config= config,
    stream_mode= 'messages'):

    # SaliBot fix: only print SaliBot's own reply, not the raw tool results
    if metadata.get("langgraph_node") != "chatbot":
        continue

    if message_chunk.content:
        print(chunk_text(message_chunk.content), end="", flush=True)
