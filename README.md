# Non-Profit AI Toolkit — stages 1–2 (live prototype)

A runnable prototype of the toolkit's first two **levels**, powered by **GLM-5.2** on Ollama Cloud. Unlike a static mockup, this one actually calls the model and gates progression.

The hosted interface is at **https://zmuhls.github.io/nonprofit-agentic-toolkit/**. GitHub Pages serves `index.html`. The browser sends authenticated API requests to **https://toolkit-api-production-535d.up.railway.app**, where Railway runs `server.py` and keeps the Ollama key out of the browser.

- **Stage 1 · Core** — you free-write what your org wants from AI and what worries you. GLM-5.2 reads it and hands back **2–3 pointed questions**, each tagged with the stage it sets up (2 Application / 3 Infobot / 4 Fine-tuning). Getting your questions **unlocks Stage 2**.
- **Stage 2 · Application** — the **live** assistant for *your* org, grounded in the service list you type or paste in Stage 1 (or the built-in Fortune Society example preset), with a required procedure: **ask → human-in-the-loop verify → mark ready to share**. Completing all three **unlocks Stage 3**. No org is hardcoded — Fortune is only a one-click example.

## Run

```bash
export OLLAMA_API_KEY="<your ollama cloud key>"     # stays in the environment, never written to a file
cd visualizations/toolkit-app
python3 server.py                                   # → http://127.0.0.1:8765
```

Then open **http://127.0.0.1:8765** and enter the access code.

- `server.py` proxies chat to `https://ollama.com/api/chat` (model `glm-5.2`). The browser never sees the key, and there's no CORS problem.
- The key is read from the environment only — it is never committed, logged, or written to disk. Don't hardcode it here.
- Needs **python3** (standard library only — no pip installs) and an Ollama Cloud key with GLM-5.2 access.

Override the port or model if you want: `PORT=9000 TOOLKIT_MODEL=glm-5.2 python3 server.py`.

## Railway

`railway.json` sets the Railpack builder, `python3 server.py` start command, `/health` deployment check, and restart policy. The production service uses these environment variables:

- `OLLAMA_API_KEY` for Ollama Cloud; server-only and required for chat.
- `ALLOWED_ORIGIN=https://zmuhls.github.io` for browser requests from GitHub Pages.
- `ACCESS_CODE` for the shared server-side gate.
- `TOOLKIT_MODEL=glm-5.2` and `HOST=0.0.0.0` for the runtime.

The server accepts cross-origin API requests only from the configured origin. `/health` returns a small key-free response for Railway's deployment check.

## Access code

The app is gated by a shared access code, enforced **server-side** so the key can never be used by anyone who merely reaches `/api/chat`. The default code is `AI4Wut`; override it with `ACCESS_CODE=… python3 server.py`, or set `ACCESS_CODE=` (empty) to turn the gate off for local development. The frontend collects the code once (validated against `/api/auth`) and sends it as the `X-Access-Code` header on every request.

## Reasoning tokens

GLM-5.2 is a hybrid reasoning model. The request sets `think:false` and reads only `message.content` (never `message.thinking`); as a fallback for the case where the trace bleeds into `content` anyway, `strip_reasoning()` removes any `<think>…</think>` / `◁think▷…◁/think▷` block before the reply leaves the server, so reasoning never reaches the UI.

## Files

| File | Role |
|---|---|
| `server.py` | Static server + `/api/chat` proxy; the per-stage system prompts, access gate, Pages CORS policy, health check, and `strip_reasoning()` live here. |
| `index.html` | The gated two-level frontend (access code → free-write → questions; live assistant → procedure). |
| `railway.json` | Railway start command, health check, and restart policy. |
| `tests/test_strip.py` | Key-free unit tests for `strip_reasoning()`. |
| `tests/simulate.py` | Live end-to-end harness (needs the server up + a key); guards against reasoning leaks. |

The system prompts (in `server.py`) are built per-request from the org name and service list the user supplies (see `assistant_prompt()`); they tell GLM-5.2 to answer **only** from that directory, never invent a program or eligibility rule, and end every answer with a verify-with-the-team reminder — the same human-in-the-loop discipline the rest of the toolkit assumes.
