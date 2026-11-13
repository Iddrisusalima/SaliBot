import math
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from database import save_memory, search_memory
from rag import retrieve_from_rag

# --- SaliBot upgrade imports ---
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from langchain_core.runnables import RunnableConfig
from database import delete_memories


load_dotenv()


CURRENT_THREAD_ID = "default"


def set_current_thread_id(thread_id: str):
    global CURRENT_THREAD_ID
    CURRENT_THREAD_ID = thread_id


def thread_of(config: RunnableConfig | None) -> str:
    """
    SaliBot fix: read the chat's thread_id from THIS request, so two people
    chatting at the same moment never share memories or documents.
    Falls back to the old global value (e.g. in test_agent.py).
    """
    if config:
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id:
            return thread_id
    return CURRENT_THREAD_ID


# ---------------------------------------------------------------
# SaliBot upgrade: a calculator that can only do maths
# ---------------------------------------------------------------
# Python reads the expression into a tree (ast), and we walk the tree ourselves,
# allowing only numbers, + - * / // % **, brackets and a list of maths functions.
# Anything else (names, attributes, imports, strings...) is refused.

import ast
import operator

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_FUNCTIONS = {
    name: getattr(math, name)
    for name in ("sqrt", "cbrt", "exp", "log", "log2", "log10", "sin", "cos", "tan",
                 "asin", "acos", "atan", "degrees", "radians", "floor", "ceil",
                 "factorial", "gcd", "hypot", "fabs")
    if hasattr(math, name)
}
_FUNCTIONS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": lambda *x: sum(x)})

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

_MAX_EXPONENT = 1000      # stops 9**9**9, which would freeze the server
_MAX_FACTORIAL = 1000


def safe_math(expression: str):
    if len(expression) > 300:
        raise ValueError("expression is too long")

    # Accept "math.sqrt(16)" as well as "sqrt(16)", and "^" as power
    expression = expression.replace("math.", "").replace("^", "**")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)

        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value

        if isinstance(node, ast.Name) and node.id in _CONSTANTS:
            return _CONSTANTS[node.id]

        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](walk(node.operand))

        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow):
                too_big = abs(right) > _MAX_EXPONENT or (
                    isinstance(left, int) and left.bit_length() * abs(right) > 100_000)
                if too_big:
                    raise ValueError("exponent is too large")
            return _OPERATORS[type(node.op)](left, right)

        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCTIONS and not node.keywords):
            args = [walk(arg) for arg in node.args]
            if node.func.id == "factorial" and args and args[0] > _MAX_FACTORIAL:
                raise ValueError("number is too large for factorial")
            return _FUNCTIONS[node.func.id](*args)

        raise ValueError("only numbers, + - * / // % ** and maths functions are allowed")

    return walk(ast.parse(expression, mode="eval"))


web_search = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="advanced"
)


@tool
def calculator(expression: str) -> str:
    """
    Useful for simple math calculations.
    Input should be a valid math expression.
    Example: 2 + 2, math.sqrt(16), 10 * 5
    """

    # SaliBot upgrade: the course used eval(), which can run any Python code.
    # safe_math() only understands numbers, operators and maths functions.
    try:
        result = safe_math(expression)
        return str(result)

    except Exception as e:
        return f"Calculation error: {str(e)}"


@tool
def search_uploaded_documents(query: str, config: RunnableConfig) -> str:
    """
    Search uploaded documents for relevant information.
    Use this when the user asks about uploaded PDFs, DOCX, TXT, notes, files, or documents.
    Also use it for uploaded Excel sheets, PowerPoint slides, and images.
    """

    return retrieve_from_rag(
        query=query,
        thread_id=thread_of(config)
    )


@tool
def remember_this(memory: str, config: RunnableConfig) -> str:
    """
    Save an important user preference or fact into long-term memory.
    Use this when the user asks you to remember something.
    """

    return save_memory(
        thread_id=thread_of(config),
        memory=memory
    )


@tool
def recall_memory(query: str, config: RunnableConfig) -> str:
    """
    Recall saved long-term memories about the user or this conversation.
    """

    return search_memory(
        thread_id=thread_of(config),
        query=query
    )


# ---------------------------------------------------------------
# SaliBot upgrade: 4 extra tools
# ---------------------------------------------------------------

@tool
def get_current_datetime(timezone_name: str = "Africa/Accra") -> str:
    """
    Get today's date and the current time.
    Use this whenever the user asks for the date, the time, the day of the week,
    or anything relative to today (e.g. "this week", "this month", "how many days until").
    timezone_name is an IANA time zone such as "Africa/Accra" or "Europe/London".
    """

    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone, timezone_name = timezone.utc, "UTC"

    now = datetime.now(zone)
    return now.strftime(f"%A, %d %B %Y, %H:%M ({timezone_name})")


@tool
def forget_memory(what_to_forget: str, config: RunnableConfig) -> str:
    """
    Delete saved long-term memories when the user asks you to forget something.
    Pass key words that appear in the memory (e.g. "robotics", "favourite colour"),
    or "everything" to delete all memories in this chat.
    If unsure what is saved, call recall_memory first.
    """

    return delete_memories(
        thread_id=thread_of(config),
        query=what_to_forget
    )


@tool
def search_research_papers(query: str, max_results: int = 5, newest_first: bool = False) -> str:
    """
    Search arXiv for scientific research papers (AI, machine learning, robotics,
    physics, maths, computer science...). Use this when the user asks for papers,
    research, studies or academic articles on a topic.
    Set newest_first=True when the user asks for recent, new or latest papers.
    Returns titles, authors, dates, links and short summaries.
    """

    max_results = max(1, min(int(max_results or 5), 10))
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate" if newest_first else "relevance",
        "sortOrder": "descending",
    })

    try:
        request = urllib.request.Request(
            f"https://export.arxiv.org/api/query?{params}",
            headers={"User-Agent": "SaliBot/1.0"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            feed = ET.fromstring(response.read())
    except Exception as e:
        return f"Couldn't reach arXiv right now: {e}"

    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers = []

    for i, entry in enumerate(feed.findall("a:entry", ns), start=1):
        title = " ".join(entry.findtext("a:title", "", ns).split())
        summary = " ".join(entry.findtext("a:summary", "", ns).split())
        published = entry.findtext("a:published", "", ns)[:10]
        link = entry.findtext("a:id", "", ns)
        authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]
        author_text = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

        papers.append(
            f"{i}. {title}\n"
            f"   Authors: {author_text}\n"
            f"   Published: {published}\n"
            f"   Link: {link}\n"
            f"   Summary: {summary[:400]}{'...' if len(summary) > 400 else ''}"
        )

    return "\n\n".join(papers) if papers else f"No arXiv papers found for '{query}'."


YOUTUBE_PATTERN = re.compile(r"(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)[\w-]{6,}")


@tool
def youtube_summary(url: str, question: str = "") -> str:
    """
    Watch a YouTube video and summarise it (or answer a question about it).
    Use this when the user shares a YouTube link or asks about a YouTube video.
    url is the full YouTube link. question is optional, e.g. "What are the main steps?".
    """

    if not YOUTUBE_PATTERN.search(url or ""):
        return "That doesn't look like a YouTube link. Please share a full youtube.com or youtu.be URL."

    from google import genai
    from google.genai import types

    task = question.strip() or (
        "Summarise this video: start with a one-sentence overview, "
        "then the key points as bullet points, then any important takeaways."
    )

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite"),
            contents=types.Content(parts=[
                types.Part(file_data=types.FileData(file_uri=url)),
                types.Part(text=task),
            ]),
        )
        return (response.text or "").strip() or "I couldn't get anything from that video."
    except Exception as e:
        return f"Couldn't watch that video: {str(e)[:300]}"


tools = [
    calculator,
    search_uploaded_documents,
    remember_this,
    recall_memory,
    web_search,
    # SaliBot upgrade
    get_current_datetime,
    forget_memory,
    search_research_papers,
    youtube_summary,
]
