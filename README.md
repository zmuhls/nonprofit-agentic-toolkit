# Non-Profit AI Toolkit — entry screen + Red Line Test (live prototype)

The current prototype opens with an explanatory landing screen. Staff select **Begin the guided review** before reaching the **Strategic Fit entry screen**, followed by **Step 1, the Red Line Test**. It gathers a cumulative, in-session AI Adoption Record, asks one question at a time, and carries facts, negotiated conditions, owners, and unknowns into the next test. Users describe data categories and current practices only. They should never paste client records, names, identifying details, confidential text, or document uploads into the guide.

The entry screen records the proposed use, mission or strategic-plan connection, people affected, current practice, desired outcome, non-AI option, staff capacity, accountable owner, and reasons to stop. The Red Line Test covers public, restricted, and sensitive data; ownership and consent; human decision authority; equity and access; audit and recourse; intellectual-property ownership; staff capacity; and the organization's ability to stop the work.

The model drafts one of three routes from the supplied facts: **Proceed**, **Negotiate and return**, or **Walk Away**. The organization's responsible data, program, and governance owners decide. A Proceed decision unlocks the Stress Test. A negotiable condition keeps Step 1 open, and a Walk Away decision closes the proposal while preserving the reason.

The former application assistant is retired. Technical patterns such as an Infobot, document search, RAG, or local inference enter only after the organization has completed the six decision tests.

A runnable browser prototype powered by **GLM-5.2** on Ollama Cloud. The model drafts each record and the interface gates progression.

The hosted interface is at **https://zmuhls.github.io/nonprofit-agentic-toolkit/**. GitHub Pages serves `index.html`. The browser sends API requests to **https://toolkit-api-production-535d.up.railway.app**, where Railway runs `server.py` and keeps the Ollama key out of the browser.

- **Entry screen · Strategic fit** — free-write followed by four adaptive questions and a draft Entry record.
- **Step 1 · Red Line Test** — five adaptive questions, a draft Red Line record, one of three routes, and required review by responsible owners before the Stress Test.

## Run

```bash
export OLLAMA_API_KEY="<your ollama cloud key>"     # stays in the environment, never written to a file
cd visualizations/toolkit-app
python3 server.py                                   # → http://127.0.0.1:8765
```

Then open **http://127.0.0.1:8765**.

- `server.py` proxies chat to `https://ollama.com/api/chat` (model `glm-5.2`). The browser never sees the key, and there's no CORS problem.
- The key is read from the environment only — it is never committed, logged, or written to disk. Don't hardcode it here.
- Needs **python3** (standard library only — no pip installs) and an Ollama Cloud key with GLM-5.2 access.

Override the port or model if you want: `PORT=9000 TOOLKIT_MODEL=glm-5.2 python3 server.py`.

## Railway

`railway.json` sets the Railpack builder, `python3 server.py` start command, `/health` deployment check, and restart policy. The production service uses these environment variables:

- `OLLAMA_API_KEY` for Ollama Cloud; server-only and required for chat.
- `ALLOWED_ORIGIN=https://zmuhls.github.io` for browser requests from GitHub Pages.
- `TOOLKIT_MODEL=glm-5.2` and `HOST=0.0.0.0` for the runtime.

The server accepts cross-origin API requests only from the configured origin. `/health` returns a small key-free response for Railway's deployment check.

`/api/chat` has no access-code check. `ALLOWED_ORIGIN` limits which browser origin can read responses, but it does not authenticate direct HTTP clients. A public deployment can therefore consume the server's model quota.

## Reasoning tokens

GLM-5.2 is a hybrid reasoning model. The request sets `think:false` and reads only `message.content` (never `message.thinking`); as a fallback for the case where the trace bleeds into `content` anyway, `strip_reasoning()` removes any `<think>…</think>` / `◁think▷…◁/think▷` block before the reply leaves the server, so reasoning never reaches the UI.

## Files

| File | Role |
|---|---|
| `server.py` | Static server + `/api/chat` proxy; the per-stage system prompts, Pages CORS policy, health check, and `strip_reasoning()` live here. |
| `index.html` | The landing page and wide conversation workspace (overview → strategic-fit interview → Red Line Test). |
| `railway.json` | Railway start command, health check, and restart policy. |
| `tests/test_strip.py` | Key-free unit tests for `strip_reasoning()`. |
| `tests/simulate.py` | Live end-to-end harness (needs the server up + a key); guards against reasoning leaks. |

The system prompts in `server.py` use the org name and cumulative in-session record. They separate organization-supplied facts from unknowns, forbid requests for raw sensitive material, and require responsible people to review the model's draft route.
