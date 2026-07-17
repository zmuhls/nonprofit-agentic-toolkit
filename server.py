#!/usr/bin/env python3
"""Local prototype server for the Non-Profit AI Toolkit — stages 1–2.

Serves index.html and proxies chat to GLM-5.2 on Ollama Cloud. The API key is
read from the environment and never written to disk.

  export OLLAMA_API_KEY=...        # your ollama cloud key
  python3 server.py               # then open http://127.0.0.1:8765

The assistant is org-agnostic: the frontend sends the org's name and (optional)
service notes, and the system prompt is built from those. No org is hardcoded.
"""
import http.server, socketserver, json, os, pathlib, re, urllib.request, urllib.error

KEY   = os.environ.get("OLLAMA_API_KEY", "").strip()
MODEL = os.environ.get("TOOLKIT_MODEL", "glm-5.2")
HERE  = pathlib.Path(__file__).parent
HOST  = os.environ.get("HOST", "0.0.0.0")

# The hosted frontend lives on GitHub Pages while the API runs on Railway.
# Keep this to one exact browser origin in production. Local and Railway-hosted
# copies remain same-origin and do not need CORS headers.
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "").rstrip("/")

# Shared access code gating the app. Enforced server-side on /api/chat so the
# key can never be used by anyone who merely reaches the endpoint. Overridable
# via the ACCESS_CODE env var; set it to "" to disable the gate entirely.
ACCESS_CODE = os.environ.get("ACCESS_CODE", "AI4Wut").strip()

# GLM-5.2 is a hybrid reasoning model. Even with think:false it INTERMITTENTLY
# leaks its chain-of-thought into message.content — verified live against Ollama
# Cloud — and typically as a PREFIX with only a CLOSING tag and no opening one,
# e.g. "…long reasoning… Let me finalize.</think>**the real answer**". Ollama's
# contract puts reasoning in message.thinking (empty in the leak case), which we
# never read; strip_reasoning removes the trace from content so it never reaches
# the UI. Delimiters seen: <think>/<thinking> (GLM, DeepSeek-R1) and ◁think▷ (Kimi).
_REASONING_BLOCK = re.compile(         # well-formed <think>…</think> block (both tags)
    r"<think\b[^>]*>.*?</think\s*>"
    r"|<thinking\b[^>]*>.*?</thinking\s*>"
    r"|◁think▷.*?◁/think▷",
    re.IGNORECASE | re.DOTALL,
)
_CLOSE_TAG = re.compile(               # a closing reasoning tag on its own (the common leak)
    r"</think\s*>|</thinking\s*>|◁/think▷",
    re.IGNORECASE,
)
_ORPHAN_OPEN = re.compile(             # a stray opening tag left by a truncated trace
    r"<think\b[^>]*>|<thinking\b[^>]*>|◁think▷",
    re.IGNORECASE,
)


def strip_reasoning(text):
    """Remove any leaked reasoning trace from model content; a no-op on clean text.

    Handles a well-formed <think>…</think> block AND the common GLM leak where only
    the closing tag survives and the reasoning is the whole prefix before it. When a
    closing tag is present, everything up to and including the last one is dropped, so
    the trace can never survive as visible prose. A leak with no tag at all is not
    detectable and is left untouched.
    """
    if not text:
        return text
    cleaned = _REASONING_BLOCK.sub("", text)          # paired <think>…</think> blocks
    closes = list(_CLOSE_TAG.finditer(cleaned))       # orphan closing tag → reasoning is the prefix
    if closes:
        cleaned = cleaned[closes[-1].end():]          # drop everything up to & incl. the last close
    cleaned = _ORPHAN_OPEN.sub("", cleaned)           # stray unmatched opening tag
    return cleaned.strip()

# Stage 1 · Core — an ADAPTIVE interview: each disclosure shapes the next question
ONBOARD = (
    "You are the onboarding interviewer for the Non-Profit AI Toolkit, having a short adaptive "
    "conversation with a non-profit staff member to find where they should start.\n\n"
    "Read the FULL conversation each turn. Then do ONE of these:\n"
    "- If they have answered FEWER THAN 3 of your questions so far: ask exactly ONE short, pointed "
    "follow-up. It must build on what they just disclosed (reference it), go one level deeper than "
    "your last question, and target the biggest remaining unknown for routing them. Just the "
    "question — no preamble, no list, no praise.\n"
    "- If they have already answered 3 of your questions: stop asking. Give a 2-4 line recommendation "
    "of which stage to start with and why, grounded in what they told you. Tag the stages you name "
    "with (→ Stage 2: a chatbot and prompts for everyday tasks), (→ Stage 3: answers from your own "
    "documents), or (→ Stage 4: teach a model one narrow task).\n\n"
    "Plain language. No buzzwords, no slogans, no em-dash pivots. One thing at a time — never a list "
    "of questions."
)

# After Core 1 finishes — project the org's stage sequence and the broader set of paths
ESTIMATE = (
    "You are the planning agent for the Non-Profit AI Toolkit. The staff member just finished "
    "onboarding (Stage 1). Using everything they disclosed, project their path through the "
    "toolkit's six stages.\n\n"
    "The six stages:\n"
    "1. Core — setup and AI literacy for staff.\n"
    "2. Application — a chatbot, prompt templates, and simple workflows for everyday tasks.\n"
    "3. Infobot & RAG — an assistant that answers from the org's own documents.\n"
    "4. Fine-tuning — teach a small model one narrow, repeated task, on synthetic data.\n"
    "5. Hosting — run the org's own model locally, for privacy and no per-seat fee.\n"
    "6. Maintenance — updates, safety, governance, and a handoff plan.\n\n"
    "Write two short sections in plain language. No preamble, no slogans, no em-dash pivots.\n\n"
    "**Your sequence** — the ordered stages THIS org should actually do, skipping any they do not "
    "need. Give 3 to 5 steps as a numbered list. For each: the stage name in bold, one line on what "
    "it delivers for them that references what they told you, and a rough effort estimate in "
    "parentheses (a session / a few weeks / ongoing).\n\n"
    "**The broader set** — 2 or 3 other common sequences nonprofits take through these stages (for "
    "example literacy-first, documents-first, or ownership-first), one line each, so they can see "
    "where their own path sits and adjust.\n\n"
    "Keep the whole reply under 180 words."
)


def assistant_prompt(org, context=""):
    """Build the Stage-2 assistant prompt, inflected by the user's Stage-1 free-write."""
    name = (org.get("name") or "").strip() or "the organization"
    services = (org.get("services") or "").strip()
    context = (context or "").strip()
    base = (
        "You are the staff assistant for %s inside the Non-Profit AI Toolkit. Help staff with the "
        "full range of everyday work: answering questions about the org's services, drafting "
        "emails and summaries, plain-language rewrites, translation, and de-identifying notes. "
        "Adapt to whatever the staffer asks.\n\n"
        "Guardrails:\n"
        "- Your answers are DRAFTS. End each substantive answer with one short line telling the "
        "staffer to verify anything factual with the team before acting.\n"
        "- Never invent a program, statistic, or eligibility rule.\n"
        "- If the message contains anything that looks like client PII (names, dates of birth, "
        "case numbers, addresses, health details), do the task but first warn the staffer to "
        "remove identifying details — sensitive data should not go into AI.\n"
        "- Be plain and trauma-informed. Keep answers short. No buzzwords or slogans." % name
    )
    if context:
        base += ("\n\nIn onboarding (Stage 1) this staffer wrote:\n\"%s\"\nKeep their situation and "
                 "worries in mind and tailor your help to them." % context)
    if services:
        return (base + "\n\nFor questions about what %s offers, use ONLY the directory below; if "
                "something is not listed, say it is not in the directory and suggest who to ask.\n\n"
                "%s's services:\n%s" % (name, name, services))
    return (base + "\n\nYou do not have %s's service directory yet. For service-specific questions, "
            "say you would need their documents (that is Stage 3) rather than guessing. You can "
            "still help fully with drafting, summarizing, translating, and prompts." % name)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def _authorized(self):
        if not ACCESS_CODE:                       # gate disabled
            return True
        return (self.headers.get("X-Access-Code") or "").strip() == ACCESS_CODE

    def end_headers(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if ALLOWED_ORIGIN and origin == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not ALLOWED_ORIGIN or origin != ALLOWED_ORIGIN:
            self.send_error(403); return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"}); return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/auth":              # frontend gate check
            self._json(200, {"ok": self._authorized()}); return
        if self.path != "/api/chat":
            self.send_error(404); return
        if not self._authorized():
            self._json(200, {"content": None, "error": "access code required or incorrect"}); return
        try:
            n = int(self.headers.get("content-length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            mode = req.get("mode", "assistant")
            if mode == "onboard":
                system = ONBOARD
            elif mode == "estimate":
                system = ESTIMATE
            else:
                system = assistant_prompt(req.get("org", {}), req.get("context", ""))
            messages = [{"role": "system", "content": system}] + req.get("messages", [])
            self._json(200, self._ollama(messages))
        except Exception as e:
            self._json(200, {"content": None, "error": str(e)})

    def _ollama(self, messages):
        if not KEY:
            return {"content": None,
                    "error": "OLLAMA_API_KEY is not set — restart the server with the key in the environment."}
        payload = json.dumps({"model": MODEL, "messages": messages,
                              "stream": False, "think": False}).encode()
        request = urllib.request.Request(
            "https://ollama.com/api/chat", data=payload,
            headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                data = json.load(resp)
            # read only message.content (never message.thinking) and strip any
            # reasoning trace that leaked inline despite think:false
            return {"content": strip_reasoning(data.get("message", {}).get("content") or ""),
                    "error": None, "model": MODEL}
        except urllib.error.HTTPError as e:
            return {"content": None, "error": "ollama %s: %s" % (e.code, e.read().decode()[:200])}
        except Exception as e:
            return {"content": None, "error": str(e)}

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("non-profit ai toolkit · prototype")
    print("  http://%s:%d   model=%s   key=%s   gate=%s"
          % (HOST, port, MODEL, "set" if KEY else "MISSING", "on" if ACCESS_CODE else "off"))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    socketserver.ThreadingTCPServer((HOST, port), Handler).serve_forever()
