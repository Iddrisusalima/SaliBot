# SaliBot Roadmap 🗺️

My plan for growing SaliBot from a course project into a production app.

> **Production = safe for many users.**
> Start with login + per-user data, not with a new framework.

---

## Stage 1 — Finish the course ✅
- [x] LangGraph agent with 5 tools (web search, calculator, documents, remember, recall)
- [x] RAG with extra file types (Excel, PowerPoint, pictures)
- [x] Upgraded to Gemini 3.5 (2.5 is closed to new accounts)
- [x] SaliBot's own chat page (FastAPI + HTML) with voice input
- [x] Follow the rest of the video (Dockerfile, .dockerignore, cicd.yaml ready)
- [x] **Deploy** → live at https://salibot.onrender.com (Render, free; AWS later with a funded card)
- [x] Add "You were created by Salima Iddrisu" to the system prompt
- [x] **Polished GitHub README** with a clean draw.io architecture diagram
- [x] **Launch drafts**: dev.to article + LinkedIn post (in `launch/`, live link added)
- [ ] **Demo video**: script ready in `launch/`; record it after deploying
- [ ] **LangSmith walkthrough**: explain tracing and monitoring (traces, latency,
      error rate, LLM calls, cost & tokens, tools)
- [ ] LangSmith warns of a **deprecated API endpoint** (stops working 31 Jan 2027):
      update the `langsmith` package before then

## Stage 2 — Make it safe for other people (the real "production" step)
- [x] **Accounts**: create account / log in / log out (email + password)
- [ ] "Sign in with Google" (optional extra)
- [x] **Separate chats per user**: each user only sees and opens their own chats
- [x] Replace the shared `CURRENT_THREAD_ID` in tools.py with per-request info
      (needed before many people chat at the *same moment*, or tools could
      read the wrong chat's memory/documents)
- [ ] **Paid Gemini plan** with a monthly spending limit
      (free plan ≈ 20 requests/day on gemini-3.5-flash)
- [ ] **PostgreSQL** instead of SQLite for the server database
- [ ] Upload size limits + rate limits (so one person can't overload it)
- [ ] Error monitoring (LangSmith traces + server logs)
- [x] **Chat menu (⋯) in the sidebar**: rename, delete and **pin** a chat
      (pinned chats stay at the top of Recents)
      (needs new rename/delete routes in app.py + database.py, and clearing
      that chat's memory, documents and LangGraph checkpoints on delete)
- [x] My 4 extra tools:
  - [x] 🔬 `search_research_papers` (arXiv)
  - [x] 🎬 `youtube_summary`
  - [x] 🕒 `get_current_datetime`
  - [x] 🗑️ `forget_memory`

## Stage 3 — Rebuild the frontend in Next.js (optional, for growth)
- [ ] Learn the basics of React + Next.js
- [ ] Rebuild the chat page in Next.js — the FastAPI backend stays the same
- [ ] Deploy the frontend (e.g. Vercel) and point it at the FastAPI backend
- Portfolio story: *"I started with plain HTML, then upgraded to Next.js."*
