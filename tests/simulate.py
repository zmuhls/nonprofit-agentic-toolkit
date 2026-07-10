#!/usr/bin/env python3
"""Simulation test harness for the Non-Profit AI Toolkit prototype.

Replays scripted user runs against the LIVE app — the same `/api/chat` calls the
browser makes — so each persona exercises the full sequence a real user would walk
through in the browser at http://127.0.0.1:8765:

    free-write -> adaptive interview -> routing -> estimate -> assistant + tasks

Each step is checked against the invariants the app is supposed to hold. Because the
model is live, replies vary run to run, so the checks are keyword-tolerant, not
exact-match.

Usage (start the server first, with OLLAMA_API_KEY set):
    python3 tests/simulate.py                 # all personas
    python3 tests/simulate.py --persona maple # one persona
    python3 tests/simulate.py --verbose       # print fuller model replies
"""
import argparse, json, os, sys, urllib.request

BASE = "http://127.0.0.1:8765"
# match the server's default gate; override with ACCESS_CODE if the server does too
ACCESS_CODE = os.environ.get("ACCESS_CODE", "AI4Wut")


def call(payload):
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-Access-Code": ACCESS_CODE})
    return json.load(urllib.request.urlopen(req, timeout=120))


def short(s, n=220):
    return (s or "").strip().replace("\n", " / ")[:n]


# reasoning-trace markers that must never appear in returned content (see
# server.strip_reasoning) — GLM/DeepSeek <think>, Kimi ◁think▷, and variants
REASONING_MARKERS = ("<think", "</think", "◁think▷", "◁/think▷", "<thinking", "</thinking")


def leaks_reasoning(text):
    low = (text or "").lower()
    return any(m.lower() in low for m in REASONING_MARKERS)


# ---- personas: a free-write + a bank of answers consumed in order, plus stage-2 probes ----
PERSONAS = [
    {
        "id": "maple", "org": "Maple Community Center", "services": "",
        "freewrite": ("After-school programs, a food pantry, and ESL classes. Staff answer the same "
                      "eligibility questions for hours, intake notes are all on paper, and I worry "
                      "about client privacy."),
        "answers": ["Mostly food-pantry income limits. Just names and program, no SSNs.",
                    "They look them up in a paper binder at the front desk.",
                    "About six staff, none of them technical."],
        "stage2": [("draft", "Draft a short, warm email telling a family they qualify for the food pantry."),
                   ("pii", "Summarize this intake note: Maria Gomez, DOB 4/12/1980, SSN 123-45-6789, needs rent help."),
                   ("scope", "Do we provide immigration legal representation?")],
    },
    {
        "id": "harbor", "org": "Harbor Legal Aid",
        "services": "- Eviction defense\n- Public-benefits appeals\n- Know-your-rights clinics",
        "freewrite": ("We're a small legal-aid office drowning in intake. Lawyers repeat the same "
                      "know-your-rights explanations every day. Everything we hold is confidential."),
        "answers": ["Tenants facing eviction, mostly. The case facts are confidential.",
                    "We keep a know-your-rights PDF library.",
                    "Two paralegals could maintain something simple."],
        "stage2": [("draft", "Draft a plain-language explanation of a tenant's right to a hearing."),
                   ("scope", "Do you offer immigration bond hearings?")],
    },
]


class Checks:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.fails = []

    def ok(self, cond, label):
        if cond:
            self.passed += 1
            print("   ✓ " + label)
        else:
            self.failed += 1
            self.fails.append(label)
            print("   ✗ " + label)


def run_persona(p, chk, verbose):
    print("\n=== persona: %s (%s) ===" % (p["org"], p["id"]))
    org = {"name": p["org"], "services": p["services"]}
    ctx = "org: %s. %s" % (p["org"], p["freewrite"])
    hist = [{"role": "user", "content": ctx}]
    print("  free-write: " + short(p["freewrite"]))

    # ---- adaptive interview: each answer should shape the next single question ----
    routing = None
    for i in range(5):
        c = (call({"mode": "onboard", "messages": hist, "context": ctx}).get("content") or "")
        chk.ok(bool(c), "interview turn %d returned content" % (i + 1))
        chk.ok(not leaks_reasoning(c), "turn %d has no leaked reasoning tokens" % (i + 1))
        if "→ stage" in c.lower() or "→stage" in c.lower():
            routing = c
            break
        print("  Q%d: %s" % (i + 1, short(c, 300 if verbose else 160)))
        chk.ok(c.count("?") <= 2, "turn %d asks one question, not a batch" % (i + 1))
        ans = p["answers"][i] if i < len(p["answers"]) else "not sure — what do you suggest?"
        hist += [{"role": "assistant", "content": c}, {"role": "user", "content": ans}]
        ctx += "\n— " + ans
    chk.ok(routing is not None, "interview reached a routing recommendation")
    chk.ok(bool(routing) and "stage" in routing.lower(), "routing names at least one stage")
    if routing:
        print("  ROUTE: " + short(routing, 300 if verbose else 200))

    # ---- estimate: fires once Core 1 finishes ----
    hist.append({"role": "user", "content": "Now project my build sequence and the broader set of sequences, exactly as instructed."})
    est = (call({"mode": "estimate", "messages": hist, "context": ctx, "org": org}).get("content") or "")
    print("  ESTIMATE: " + short(est, 600 if verbose else 240))
    chk.ok(not leaks_reasoning(est), "estimate has no leaked reasoning tokens")
    chk.ok("your sequence" in est.lower(), "estimate has a 'your sequence' section")
    chk.ok("broader set" in est.lower(), "estimate has a 'broader set' section")
    chk.ok(any(w in est.lower() for w in ["session", "week", "ongoing", "day", "month"]),
           "estimate carries effort markers")

    # ---- stage 2: live assistant across a range of tasks ----
    a_hist = []
    for kind, msg in p["stage2"]:
        a_hist.append({"role": "user", "content": msg})
        a = (call({"mode": "assistant", "messages": a_hist, "context": ctx, "org": org}).get("content") or "")
        a_hist.append({"role": "assistant", "content": a})
        print("  [%s] %s" % (kind, short(a, 300 if verbose else 160)))
        chk.ok(bool(a), "stage2 %s returned an answer" % kind)
        chk.ok(not leaks_reasoning(a), "stage2 %s has no leaked reasoning tokens" % kind)
        if kind == "pii":
            chk.ok(any(w in a.lower() for w in ["remove", "identif", "sensitive", "strip", "without"]),
                   "PII task warns about identifying details")
        if kind == "scope" and p["services"]:
            chk.ok(any(w in a.lower() for w in ["not in", "don't have", "do not have", "not list",
                                                "not part", "isn't", "not one of"]),
                   "out-of-scope question flagged against the directory")
        if "fortune" not in p["org"].lower():
            chk.ok("fortune" not in a.lower(), "no Fortune leakage (%s)" % kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", help="run only this persona id")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    try:
        urllib.request.urlopen(BASE + "/", timeout=5)
    except Exception as e:
        sys.exit("server not reachable on :8765 — start it first (%s)" % e)

    chk = Checks()
    for p in PERSONAS:
        if args.persona and p["id"] != args.persona:
            continue
        run_persona(p, chk, args.verbose)

    print("\n──────── %d passed · %d failed ────────" % (chk.passed, chk.failed))
    if chk.fails:
        print("failures:")
        for f in chk.fails:
            print("  - " + f)
        sys.exit(1)
    print("all simulated runs passed ✓")


if __name__ == "__main__":
    main()
