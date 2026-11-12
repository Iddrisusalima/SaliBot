"""
SaliBot web server (FastAPI).

Run it with:   python app.py
Then open:     http://127.0.0.1:8080
"""

from dotenv import load_dotenv
import os
import certifi

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import json
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    AIMessageChunk,
    ToolMessage
)

from agent import get_agent
from database import (
    init_db,
    save_chat_message,
    get_chat_history,
    create_or_update_conversation,
    list_conversations)

from rag import add_document_to_rag
from tools import set_current_thread_id

# --- SaliBot extras (needed for SaliBot's own page, model list and voice input) ---
import sys
from pydantic import BaseModel
from google import genai
from google.genai import types as genai_types
from agent import ALLOWED_MODELS, DEFAULT_MODEL, normalize_model_name

# SaliBot: show emojis and special characters correctly in the Windows terminal
sys.stdout.reconfigure(encoding="utf-8")


app = FastAPI()

templates = Jinja2Templates(directory="templates")

Path("uploads").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)


init_db()


def sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def should_stream_chunk(chunk, metadata) -> bool:
    """
    This prevents raw tool/search/RAG JSON from appearing in the frontend.

    We only stream normal AI text chunks.
    We do NOT stream:
    - ToolMessage
    - messages from tool nodes
    - tool call chunks
    - raw tool outputs
    """

    metadata = metadata or {}

    node_name = str(metadata.get("langgraph_node", "")).lower()

    if "tool" in node_name:
        return False

    if isinstance(chunk, ToolMessage):
        return False

    if not isinstance(chunk, (AIMessage, AIMessageChunk)):
        return False

    if getattr(chunk, "tool_calls", None):
        return False

    if getattr(chunk, "invalid_tool_calls", None):
        return False

    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}

    if additional_kwargs.get("tool_calls"):
        return False

    return True


def extract_text_from_chunk(chunk) -> str:
    content = getattr(chunk, "content", "")

    if not content:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []

        for item in content:
            if isinstance(item, str):
                text_parts.append(item)

            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    text_parts.append(item["content"])

        return "".join(text_parts)

    return ""


def friendly_error(error: Exception, model: str) -> str:
    """Turn Google's long technical errors into short, helpful messages."""
    text = str(error)

    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return (
            f"The free daily limit for **{model}** is used up. "
            "Pick another model from the dropdown, or try again tomorrow."
        )

    if "UNAVAILABLE" in text or "503" in text:
        return f"**{model}** is busy right now. Try again in a minute, or pick another model."

    if "NOT_FOUND" in text or "404" in text:
        return f"**{model}** isn't available for this API key. Please pick another model."

    return f"Sorry, something went wrong: {text[:300]}"


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.get("/models")
def models():
    return {"default": DEFAULT_MODEL, "models": sorted(ALLOWED_MODELS)}


@app.get("/conversations")
async def conversations():
    items = list_conversations()

    return {
        "conversations": [
            {
                "thread_id": item.thread_id,
                "title": item.title,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat()
            }
            for item in items
        ]
    }


@app.get("/history/{thread_id}")
async def history(thread_id: str):
    messages = get_chat_history(thread_id)

    return {
        "messages": [
            {
                "role": msg.role,
                "content": msg.content
            }
            for msg in messages
        ]
    }


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    thread_id: str = Form(...)
):
    try:
        allowed_extensions = [".pdf", ".docx", ".txt", ".md", ".py", ".csv",
                              # SaliBot upgrade: Excel, PowerPoint and pictures
                              ".xlsx", ".pptx", ".png", ".jpg", ".jpeg", ".webp"]

        filename = file.filename or "uploaded_file"
        suffix = Path(filename).suffix.lower()

        if suffix not in allowed_extensions:
            return JSONResponse(
                {
                    "success": False,
                    "message": "Unsupported file type. Upload PDF, DOCX, TXT, MD, PY, CSV, XLSX, PPTX, or an image (PNG, JPG, JPEG, WEBP)."
                },
                status_code=400
            )

        file_id = str(uuid.uuid4())
        safe_filename = filename.replace(" ", "_")
        file_path = f"uploads/{file_id}_{safe_filename}"

        with open(file_path, "wb") as f:
            f.write(await file.read())

        create_or_update_conversation(thread_id, "Uploaded document")

        result = add_document_to_rag(
            file_path=file_path,
            thread_id=thread_id
        )

        return JSONResponse({
            "success": True,
            "message": f"Uploaded {result['filename']} and created {result['chunks']} chunks."
        })

    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "message": str(e)
            },
            status_code=500
        )


@app.post("/transcribe")
def transcribe(file: UploadFile = File(...), model: str | None = Form(None)):
    """🎤 Turn a recorded voice message into text using Gemini."""
    audio = file.file.read()

    if not audio:
        return JSONResponse(status_code=400, content={"error": "The recording was empty — please try again."})

    if len(audio) > 20 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "That recording is too long. Try a shorter message."})

    mime_type = (file.content_type or "audio/webm").split(";")[0]
    selected_model = normalize_model_name(model)

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=selected_model,
            contents=[
                genai_types.Part.from_bytes(data=audio, mime_type=mime_type),
                "Transcribe this voice message exactly as spoken. "
                "Reply with only the transcription text, nothing else. "
                "If there is no speech, reply with nothing.",
            ],
        )
        text = (response.text or "").strip()
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": friendly_error(e, selected_model)})

    if not text:
        return JSONResponse(
            status_code=400,
            content={"error": "I couldn't hear any words — try speaking a bit closer to the mic."},
        )

    return {"text": text}


@app.post("/chat/stream")
async def chat_stream(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body."},
            status_code=400
        )

    user_message = data.get("message", "")
    thread_id = data.get("thread_id", "default")
    selected_model = data.get("model", DEFAULT_MODEL)   # SaliBot: video uses "gemini-2.5-flash" (closed to new accounts)

    if not user_message.strip():
        return JSONResponse(
            {"error": "Message is required."},
            status_code=400
        )

    agent = get_agent(selected_model)

    create_or_update_conversation(thread_id, user_message)
    save_chat_message(thread_id, "user", user_message)

    set_current_thread_id(thread_id)

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    def event_generator():
        final_answer = ""

        try:
            inputs = {
                "messages": [
                    HumanMessage(content=user_message)
                ]
            }

            for chunk, metadata in agent.stream(
                inputs,
                config=config,
                stream_mode="messages"
            ):
                # SaliBot extra: tell the page which tool is running (🌐 Searching the web, etc.)
                for call in getattr(chunk, "tool_call_chunks", None) or []:
                    if call.get("name"):
                        yield sse_data({"tool": call["name"]})

                if not should_stream_chunk(chunk, metadata):
                    continue

                token = extract_text_from_chunk(chunk)

                if token:
                    final_answer += token
                    yield sse_data({"token": token})

            if final_answer.strip():
                save_chat_message(thread_id, "assistant", final_answer)

            yield sse_data({"done": True})

        except Exception as e:
            # SaliBot extra: friendly_error(...) gives a short message instead of Google's long str(e)
            yield sse_data({"error": friendly_error(e, normalize_model_name(selected_model))})
            yield sse_data({"done": True})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8080,
        reload=True
    )
