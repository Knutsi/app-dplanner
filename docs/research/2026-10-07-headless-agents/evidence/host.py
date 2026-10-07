"""Minimal SDK host: drives `claude -p` over stream-json, answers control requests, logs everything."""
import json, subprocess, sys, time, os
mode, prompt, answer = sys.argv[1], sys.argv[2], sys.argv[3]
log = open(sys.argv[4], "w")
cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
       "--model", "haiku", "--strict-mcp-config", "--permission-prompts", "host",
       "--permission-prompt-tool", "stdio"]
if mode == "plan":
    cmd += ["--permission-mode", "plan"]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
def send(o):
    p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush(); log.write(">> " + json.dumps(o) + "\n")
send({"type": "control_request", "request_id": "init1", "request": {"subtype": "initialize"}})
send({"type": "user", "message": {"role": "user", "content": prompt}, "parent_tool_use_id": None, "session_id": ""})
t0 = time.time()
for line in p.stdout:
    log.write(line); log.flush()
    try: m = json.loads(line)
    except Exception: continue
    if m.get("type") == "control_request":
        req = m["request"]; rid = m["request_id"]
        print("CONTROL", req.get("subtype"), req.get("tool_name"), json.dumps(req.get("input"))[:400], flush=True)
        if req.get("subtype") == "can_use_tool":
            inp = dict(req.get("input") or {})
            if req.get("tool_name") == "AskUserQuestion":
                qs = inp.get("questions", [])
                inp["answers"] = {q["question"]: answer for q in qs}
            send({"type": "control_response", "response": {"subtype": "success", "request_id": rid,
                  "response": {"behavior": "allow", "updatedInput": inp}}})
    elif m.get("type") == "result":
        print("RESULT", m.get("subtype"), str(m.get("result"))[:300], "denials:", m.get("permission_denials"), flush=True)
        break
    elif m.get("type") == "system" and m.get("subtype") == "init":
        print("TOOLS has AskUserQuestion:", "AskUserQuestion" in m.get("tools", []), "ExitPlanMode:", "ExitPlanMode" in m.get("tools", []), flush=True)
p.stdin.close(); p.terminate(); print("secs", round(time.time() - t0, 1))
