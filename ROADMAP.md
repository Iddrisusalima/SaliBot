# SaliBot Roadmap 🗺️

My plan for growing SaliBot from a course project into a production app.

> **Production = safe for many users.**
> Start with login + per-user data, not with a new framework.

---

## Stage 1 — Finish the course ✅ (in progress)
- [x] LangGraph agent with 5 tools (web search, calculator, documents, remember, recall)
- [x] RAG with extra file types (Excel, PowerPoint, pictures)
- [x] Upgraded to Gemini 3.5 (2.5 is closed to new accounts)
- [x] SaliBot's own chat page (FastAPI + HTML) with voice input
- [ ] Follow the rest of the video
- [ ] **Deploy to AWS** → get a live link for my presentation
- [ ] Add "You were created by Salima Iddrisu" to the system prompt

## Stage 2 — Make it safe for other people (the real "production" step)
- [ ] **Login** (e.g. "Sign in with Google")
- [ ] **Separate data per user** — their own chats, memory and documents
      (replace the shared `CURRENT_THREAD_ID` with per-request user/thread info)
- [ ] **Paid Gemini plan** with a monthly spending limit
      (free plan ≈ 20 requests/day on gemini-3.5-flash)
- [ ] **PostgreSQL** instead of SQLite for the server database
- [ ] Upload size limits + rate limits (so one person can't overload it)
- [ ] Error monitoring (LangSmith traces + server logs)
- [ ] **Chat menu (⋯) in the sidebar**: rename a chat, delete a chat
      (needs new rename/delete routes in app.py + database.py, and clearing
      that chat's memory, documents and LangGraph checkpoints on delete)
- [ ] My 4 extra tools:
  - [ ] 🔬 `search_research_papers` (arXiv)
  - [ ] 🎬 `youtube_summary`
  - [ ] 🕒 `get_current_datetime`
  - [ ] 🗑️ `forget_memory`

## Stage 3 — Rebuild the frontend in Next.js (optional, for growth)
- [ ] Learn the basics of React + Next.js
- [ ] Rebuild the chat page in Next.js — the FastAPI backend stays the same
- [ ] Deploy the frontend (e.g. Vercel) and point it at the FastAPI backend
- Portfolio story: *"I started with plain HTML, then upgraded to Next.js."*
