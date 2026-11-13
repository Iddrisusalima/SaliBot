# Learning Log: SaliBot

Every problem I hit while building SaliBot, in the order the request flows
through the app: model, agent, tools, streaming, accounts, then reliability.
Each entry records what happened, why, what I changed, and what it taught me.

The three findings I would point at first:

- **The course's model did not exist for me.** A tutorial pins a model; the
  provider moves on. Section 1 is how I found out what my key could actually use.
- **One global variable leaked between users.** Fine for one person in a
  terminal, wrong the moment two people use the app at once. Section 4.
- **"Retry" is two different things.** Resuming a saved run and re-sending a
  question look the same until one of them crashes. Section 7.

---

## 1. The model

### Gemini 2.5 returned 404 for a new key

The course uses `gemini-2.5-flash`. On my key every call failed with
`404 NOT_FOUND`. Nothing was wrong with the code: the model is closed to new
accounts. I listed the models my key could see, tested each one, and moved
SaliBot to the Gemini 3.5 family, with `gemini-3.5-flash-lite` as the default.

**Lesson:** when a tutorial step fails, check whether the outside world changed
before assuming my code is wrong.

### The free tier runs out

The free tier allows roughly 20 requests a day on `gemini-3.5-flash`, and one
agent answer can use several (one per tool round trip). That is why
`flash-lite` became the default, why there is a model picker, and why
`friendly_error()` turns Google's long `429 RESOURCE_EXHAUSTED` text into one
sentence telling the user what to do.

### Gemini 3.5 answers in parts, not a string

Older models return `content` as a string. Gemini 3.5 returns a **list of
parts**, for example `[{"type": "text", "text": "Hello"}]`, sometimes with an
encrypted signature part alongside. Printing `content` directly showed raw
dictionaries. `extract_text_from_chunk()` in `app.py` (and `chunk_text()` in
`scripts/test_agent.py`) now pull out only the text parts.

---

## 2. The agent

### An agent is only as good as its tool descriptions

The model decides which tool to call from the tool's docstring alone. Two
examples where the description had to change, not the code:

- Asked for *recent* papers, the arXiv tool returned the most *relevant* ones,
  some years old. I added a `newest_first` option and told the model in the
  docstring when to set it.
- `forget_memory` deletes memories that match the words it is given, so a
  guess at the wording could miss. The system prompt tells the model to call
  `recall_memory` first, so it deletes what was actually saved.

### The model did not know today's date

"What happened this week?" was answered relative to the model's training data.
A small `get_current_datetime` tool fixed it. A tool does not have to be
clever to be useful.

---

## 3. Tools and files

### More file types

The course reads PDF, Word, TXT, Markdown, Python and CSV. I added Excel
(`openpyxl`), PowerPoint (`python-pptx`) and images. Images have no text layer,
so `rag.py` sends them to Gemini vision and stores the description plus any
text it reads, which is then chunked and embedded like any other document.

### The calculator could run any code

The course's calculator passes the model's expression to `eval()` with
builtins removed. That looks locked down but is a known escape: an expression
like `().__class__.__bases__[0].__subclasses__()` reaches Python's internals
again. On a public site, a user could talk the model into "calculating" an
expression that reads `.env` or runs a command.

`safe_math()` in `tools.py` replaces it. Python's `ast` module turns the
expression into a tree, and the code walks that tree itself, allowing only
numbers, `+ - * / // % **`, brackets, `pi`/`e`/`tau` and a list of `math`
functions. Everything else is refused. Exponents and factorials have limits,
because `9**9**9` is valid maths that would freeze the server.

**Lesson:** removing the dangerous parts of a powerful tool is weaker than
building a small tool that can only do the one job.

### YouTube summaries without downloading anything

Gemini can watch a public YouTube URL directly when it is passed as
`file_data`. No transcript library and no download: the tool is a single call.

---

## 4. Streaming and per-user state

### Raw tool JSON appeared in the chat

Streaming with `stream_mode="messages"` sends **every** message, including tool
calls and tool results. Users saw search JSON and signatures before the answer.
`should_stream_chunk()` now drops anything from a tool node, any `ToolMessage`,
and any chunk carrying tool calls. The page shows a small "Searching the web"
label instead, driven by the tool name.

### One global thread id, shared by everyone

The course stores the current chat in a module-level `CURRENT_THREAD_ID`, which
memory and document tools read. With one user that works. With two users
sending at the same moment, one person's tool can read the other person's chat
id, and save a memory into the wrong chat.

The fix is to pass the thread id **with the request**: every tool now takes
`config: RunnableConfig`, which LangGraph injects per run and hides from the
model's view of the tool. The global stays only as a fallback for the terminal
script.

**Lesson:** "it works when I test it" is a single-user test.

---

## 5. Voice input

The browser's built-in speech recognition showed "listening" but returned
nothing, silently, on my network: it sends audio to an online service the
browser chooses. I replaced it: the page records audio with `MediaRecorder`,
uploads it to `/transcribe`, and Gemini returns the text. It works anywhere the
Gemini API works, and it fails with a message instead of silence.

---

## 6. Accounts

The course has no login, so every visitor shares every chat. I added accounts:

- Passwords are stored as salted **PBKDF2-SHA256** hashes, never as text.
- Login tokens live in a `LoginSession` table and are sent as
  `Authorization: Bearer`. Logging out deletes the token.
- Every route that touches a chat (history, stream, upload, rename, pin,
  delete) checks the chat belongs to the logged-in user. Another user's chat
  returns **404**, not 403, so it does not even confirm the chat exists.
- Chats created before accounts existed are claimed by the first user who opens
  them, so nothing I had already built was lost.

One bug on the way: `create_user` returned a user object after its database
session closed, and reading `user.id` raised `DetachedInstanceError`. Adding
`db.refresh(user)` before closing fixed it.

`scripts/reset_password.py` exists because I forgot my own password while
testing. It asks for the new one hidden and logs out every session.

---

## 7. Reliability: when Gemini is busy

Free-tier Gemini models regularly answer `503 UNAVAILABLE` ("overloaded"),
sometimes before a reply starts and sometimes halfway through.

SaliBot now tries a backup model (`gemini-3.5-flash-lite`, then
`gemini-3.5-flash`) when the chosen one is busy **before any words were shown**,
and the page says "Model busy, switched to ...". If it fails **mid-answer**, the
partial answer is kept and marked as possibly incomplete, instead of being lost.

### The bug the test found

My first version always *resumed* the stopped run on the backup model. The test
failed with `Received no input for __start__`: when a model fails before
LangGraph saves the step, there is nothing to resume. Re-sending the question
instead would duplicate it in the conversation whenever the step *was* saved.

So the retry now asks the checkpointer first: if `agent.get_state(config).next`
shows a pending step, resume it; otherwise send the question again. Tested both
ways, the backup answered and the conversation holds the question exactly once.

**Lesson:** test the failure path with the failure actually happening. My
first fallback looked correct and was wrong.

---

## 8. Deployment notes

- The course deploys to AWS (ECR + EC2) with GitHub Actions. That workflow is in
  `.github/workflows/cicd.yaml`, switched to manual so it does not fail on
  every push without AWS secrets.
- SaliBot is set up for Hugging Face Spaces, which runs the same `Dockerfile`
  for free. API keys go in the Space's secrets, never in the image:
  `.dockerignore` excludes `.env`, the databases and uploads.
