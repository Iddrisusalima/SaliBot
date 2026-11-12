"""
SaliBot web server (FastAPI).

Run it with:   python app.py
Then open:     http://127.0.0.1:8000
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

UPLOAD_DIR = Path("uploads")

# Course types + SaliBot upgrade types (Excel, PowerPoint, images)
ALLOWED_UPLOADS = {
    ".pdf", ".docx", ".txt", ".md", ".py", ".csv",
    ".xlsx", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp",
}


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    model: str | None = None


def chunk_text(content) -> str:
    """Newer Gemini models send text as a list of parts. Keep only the text."""
    if isinstance(content, str):
        return content

    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in content
    )


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
def conversations():
    return [
        {
            "thread_id": c.thread_id,
            "title": c.title,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in list_conversations()
    ]


@app.get("/history/{thread_id}")
def history(thread_id: str):
    return [
        {"role": m.role, "content": m.content}
        for m in get_chat_history(thread_id)
    ]


@app.post("/upload")
async def upload(file: UploadFile = File(...), thread_id: str = Form(...)):
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_UPLOADS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Sorry, {suffix or 'this file type'} isn't supported yet."},
        )

    # Keep each chat's files in its own folder
    folder = UPLOAD_DIR / thread_id
    folder.mkdir(parents=True, exist_ok=True)
    saved_path = folder / filename
    saved_path.write_bytes(await file.read())

    try:
        result = add_document_to_rag(str(saved_path), thread_id)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    create_or_update_conversation(thread_id, f"📎 {filename}")
    chunk_word = "chunk" if result["chunks"] == 1 else "chunks"
    save_chat_message(
        thread_id,
        "system",
        f"📎 Uploaded **{result['filename']}** ({result['chunks']} {chunk_word})",
    )

    return result


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
def chat_stream(req: ChatRequest):
    message = req.message.strip()
    thread_id = req.thread_id
    model = normalize_model_name(req.model)

    create_or_update_conversation(thread_id, message)
    save_chat_message(thread_id, "user", message)

    # Tell the tools which chat we're in (for documents and memory)
    set_current_thread_id(thread_id)

    agent = get_agent(model)
    config = {"configurable": {"thread_id": thread_id}}

    def event_stream():
        full_reply = ""

        try:
            for message_chunk, metadata in agent.stream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode="messages",
            ):
                # Only SaliBot's own words — skip raw tool output
                if metadata.get("langgraph_node") != "chatbot":
                    continue

                # Let the page show "Searching the web..." etc.
                for call in getattr(message_chunk, "tool_call_chunks", None) or []:
                    if call.get("name"):
                        yield json.dumps({"type": "tool", "name": call["name"]}) + "\n"

                text = chunk_text(message_chunk.content)
                if text:
                    full_reply += text
                    yield json.dumps({"type": "token", "text": text}) + "\n"

        except Exception as e:
            error = friendly_error(e, model)
            full_reply += f"\n\n⚠️ {error}"
            yield json.dumps({"type": "error", "message": error}) + "\n"

        save_chat_message(thread_id, "assistant", full_reply)
        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))

    uvicorn.run(
        "app:app",   # SaliBot: our file is app.py, so it's "app:app" (the video says "main:app")
        host=host,
        port=port,
        reload=True
    )
