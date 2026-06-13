#!/usr/bin/env python3
import json, os, sqlite3, socket, time, traceback
import urllib.error, urllib.parse, urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18667
CONFIG_PATH = Path.home() / ".cc-switch" / "dubhe-switch-config.json"
DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"

def load_config():
    if not CONFIG_PATH.exists():
        return {"upstream": "https://api.stepfun.com/v1/chat/completions", "model": "step-3.5-flash-2603", "subscription": "normal"}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {"upstream": data.get("upstream") or "https://api.stepfun.com/v1/chat/completions",
            "model": data.get("model") or "step-3.5-flash-2603",
            "subscription": data.get("subscription") or "normal",
            "api_key": data.get("api_key") or os.environ.get("STEPFUN_API_KEY")}

def extract_text(value):
    if value is None: return ""
    if isinstance(value, str): return value
    if isinstance(value, list):
        return "\n".join(extract_text(item) for item in value if item)
    if isinstance(value, dict):
        t = value.get("type")
        if t in ("input_text", "output_text", "text"): return extract_text(value.get("text"))
        if t == "image_url": return "[image_url omitted]"
        for k in ("text", "content", "output", "result"):
            if k in value:
                text = extract_text(value[k])
                if text: return text
        return json.dumps(value, ensure_ascii=False)
    return str(value)

def responses_to_messages(body):
    """Convert Responses API input -> Chat Completions messages.

    Merges reasoning + text + tool_calls from one assistant turn into
    a single assistant message (P0-1 + P0-2 uplink fix).
    """
    messages = []
    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": extract_text(instructions)})
    inp = body.get("input", "")
    if isinstance(inp, str):
        if inp.strip():
            messages.append({"role": "user", "content": inp})
        return messages or [{"role": "user", "content": ""}]
    if isinstance(inp, list):
        pending_assistant = None
        pending_reasoning = None  # buffer reasoning until next assistant

        def flush():
            nonlocal pending_assistant, pending_reasoning
            if pending_assistant:
                # Attach buffered reasoning if not already set
                if pending_reasoning and not pending_assistant.get("reasoning_content"):
                    pending_assistant["reasoning_content"] = pending_reasoning
                    pending_reasoning = None
                messages.append(pending_assistant)
                pending_assistant = None

        for item in inp:
            if not isinstance(item, dict):
                text = extract_text(item)
                if text:
                    flush()
                    messages.append({"role": "user", "content": text})
                continue

            typ = item.get("type")

            if typ == "function_call_output":
                flush()
                messages.append({"role": "tool",
                    "tool_call_id": item.get("call_id") or item.get("id") or "call_unknown",
                    "content": extract_text(item.get("output"))})
                continue

            if typ == "function_call":
                tool_call = {"id": item.get("call_id") or item.get("id") or "call_unknown",
                    "type": "function",
                    "function": {"name": item.get("name") or "unknown",
                                 "arguments": item.get("arguments") or "{}"}}
                if pending_assistant is None:
                    pending_assistant = {"role": "assistant", "content": None}
                # Attach buffered reasoning to this assistant
                if pending_reasoning and not pending_assistant.get("reasoning_content"):
                    pending_assistant["reasoning_content"] = pending_reasoning
                    pending_reasoning = None
                pending_assistant.setdefault("tool_calls", []).append(tool_call)
                continue

            if typ == "reasoning":
                reasoning_text = extract_text(item.get("content"))
                if reasoning_text:
                    # Buffer reasoning — attach to NEXT assistant message
                    # (reasoning comes BEFORE its assistant in Responses API output order)
                    if pending_assistant and pending_assistant.get("role") == "assistant":
                        pending_assistant["reasoning_content"] = reasoning_text
                    else:
                        pending_reasoning = reasoning_text
                continue

            role = item.get("role") or ("assistant" if typ == "message" else "user")
            # Remap OpenAI Responses API roles to Chat Completions roles
            if role == "developer": role = "system"
            text = extract_text(item.get("content"))
            if not text and typ:
                text = extract_text(item)

            if text:
                flush()
                if role == "assistant":
                    pending_assistant = {"role": "assistant", "content": text}
                    if pending_reasoning:
                        pending_assistant["reasoning_content"] = pending_reasoning
                        pending_reasoning = None
                else:
                    messages.append({"role": role, "content": text})

        flush()

    return messages or [{"role": "user", "content": ""}]

def responses_tools_to_chat_tools(tools):
    chat = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function": continue
        f = tool.get("function") or {}
        name = tool.get("name") or f.get("name")
        if not name: continue
        chat.append({"type": "function", "function": {"name": name, "description": tool.get("description") or f.get("description") or "", "parameters": tool.get("parameters") or f.get("parameters") or {"type": "object", "properties": {}}}})
    return chat

def sse(handler, event, data):
    try:
        handler.wfile.write(f"event: {event}\n".encode())
        handler.wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
        handler.wfile.flush()
        return True
    except Exception:
        return False

def output_from_chat_message(message):
    """Convert Chat Completions message -> Responses API output items.

    Emits reasoning_content as a standalone reasoning item (P0-2 downlink fix).
    """
    output = []
    reasoning = message.get("reasoning_content") or ""
    if reasoning:
        output.append({"id": "rsn_" + uuid.uuid4().hex, "type": "reasoning",
                       "status": "completed", "content": reasoning})
    text = message.get("content") or ""
    audio = message.get("audio") or {}
    if not text and isinstance(audio, dict): text = audio.get("transcript") or ""
    if text:
        output.append({"id": "msg_" + uuid.uuid4().hex, "type": "message",
                       "status": "completed", "role": "assistant",
                       "content": [{"type": "output_text", "text": text,
                                    "annotations": []}]})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        output.append({"id": "fc_" + uuid.uuid4().hex, "type": "function_call",
                       "status": "completed",
                       "call_id": call.get("id") or "call_" + uuid.uuid4().hex,
                       "name": fn.get("name") or "unknown",
                       "arguments": fn.get("arguments") or "{}"})
    return output

class Handler(BaseHTTPRequestHandler):
    server_version = "dubhe-ai-switch/1.0.0"
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        config = load_config()
        if path in ("/health", "/v1/health"):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "model": config["model"]}).encode())
            return
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not (path.startswith("/v1/responses") or path.startswith("/responses")):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            # DEBUG: log raw request before any processing
            try:
                import os as _os
                _log = _os.path.join(_os.path.expanduser("~"), ".cc-switch", "debug_raw_request.json")
                with open(_log, "w", encoding="utf-8") as _f:
                    _f.write(raw_body[:10000])
            except: pass
            body = json.loads(raw_body)
            config = load_config()
            messages = responses_to_messages(body)
            max_tokens = body.get("max_output_tokens") or body.get("max_tokens") or 4096
            do_stream = body.get("stream", True) is not False
            upstream_body = {"model": config["model"], "messages": messages,
                             "stream": do_stream, "max_tokens": max_tokens}
            tools = responses_tools_to_chat_tools(body.get("tools"))
            if tools: upstream_body["tools"] = tools
            for k in ("temperature", "top_p"):
                if k in body: upstream_body[k] = body[k]
            # DEBUG: log upstream request
            try:
                import os as _os
                _log = _os.path.join(_os.path.expanduser("~"), ".cc-switch", "debug_last_request.json")
                with open(_log, "w", encoding="utf-8") as _f:
                    json.dump(upstream_body, _f, ensure_ascii=False, indent=2)
            except: pass
            if do_stream:
                self._handle_stream(config, upstream_body)
            else:
                self._handle_non_stream(config, upstream_body)
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _call_upstream(self, config, body):
        auth = f"Bearer {config['api_key']}" if config.get("api_key") else ""
        req = urllib.request.Request(config["upstream"], data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())

    def _handle_non_stream(self, config, body):
        try:
            data = self._call_upstream(config, body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code); self.end_headers(); self.wfile.write(e.read()); return
        except Exception as e:
            self.send_response(502); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode()); return
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        output = output_from_chat_message(msg)
        usage = data.get("usage")
        result = {"id": "resp_" + uuid.uuid4().hex, "object": "response", "created_at": int(time.time()),
                  "status": "completed", "model": config["model"], "output": output,
                  "parallel_tool_calls": True, "tool_choice": "auto"}
        if usage:
            result["usage"] = {"input_tokens": usage.get("prompt_tokens", 0),
                               "output_tokens": usage.get("completion_tokens", 0),
                               "total_tokens": usage.get("total_tokens", 0)}
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def _handle_stream(self, config, body):
        """Real SSE streaming: upstream SSE chunks -> Responses API events (P0-3 fix)."""
        resp_id = "resp_" + uuid.uuid4().hex
        msg_id = "msg_" + uuid.uuid4().hex

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        created_at = int(time.time())

        # response.created
        sse(self, "response.created", {"type": "response.created",
            "response": {"id": resp_id, "object": "response",
                         "created_at": created_at, "status": "in_progress",
                         "model": config["model"], "output": []}})

        # output_item.added for message (output_index=0)
        msg_item = {"id": msg_id, "type": "message", "status": "in_progress",
                    "role": "assistant", "content": []}
        sse(self, "response.output_item.added",
            {"type": "response.output_item.added", "response_id": resp_id,
             "output_index": 0, "item": msg_item})

        # content_part.added
        sse(self, "response.content_part.added",
            {"type": "response.content_part.added", "response_id": resp_id,
             "item_id": msg_id, "output_index": 0, "content_index": 0,
             "part": {"type": "output_text", "text": "", "annotations": []}})

        # Streaming state
        full_text = ""
        reasoning_text = ""
        reasoning_id = None       # reasoning output item id
        tool_items = {}           # index -> {id, name, arguments, call_id}
        output_idx = 1            # next output_index (0 = message)
        final_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        auth = f"Bearer {config['api_key']}" if config.get("api_key") else ""
        try:
            req = urllib.request.Request(config["upstream"],
                data=json.dumps(body).encode(), method="POST",
                headers={"Authorization": auth, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                for line_bytes in r:
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue
                    if line == "data: [DONE]":
                        break

                    try:
                        chunk = json.loads(line[6:])
                    except Exception:
                        continue

                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta") if choices else {}
                    usage = chunk.get("usage")
                    if usage:
                        final_usage = {"input_tokens": usage.get("prompt_tokens", 0),
                                       "output_tokens": usage.get("completion_tokens", 0),
                                       "total_tokens": usage.get("total_tokens", 0)}

                    # --- reasoning_content delta ---
                    if delta.get("reasoning_content"):
                        rc = delta["reasoning_content"]
                        if reasoning_id is None:
                            reasoning_id = "rsn_" + uuid.uuid4().hex
                            rsn_item = {"id": reasoning_id, "type": "reasoning",
                                        "status": "in_progress", "content": ""}
                            sse(self, "response.output_item.added",
                                {"type": "response.output_item.added",
                                 "response_id": resp_id, "output_index": output_idx,
                                 "item": rsn_item})
                            output_idx += 1
                        reasoning_text += rc
                        sse(self, "response.output_text.delta",
                            {"type": "response.output_text.delta",
                             "response_id": resp_id, "item_id": reasoning_id,
                             "output_index": output_idx - 1, "content_index": 0,
                             "delta": rc})
                        continue

                    # --- content delta ---
                    if delta.get("content"):
                        full_text += delta["content"]
                        sse(self, "response.output_text.delta",
                            {"type": "response.output_text.delta",
                             "response_id": resp_id, "item_id": msg_id,
                             "output_index": 0, "content_index": 0,
                             "delta": delta["content"]})

                    # --- tool_calls delta ---
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        if idx not in tool_items:
                            fc_id = "fc_" + uuid.uuid4().hex
                            tool_items[idx] = {"id": fc_id, "name": "",
                                "arguments": "",
                                "call_id": tc.get("id") or "call_" + uuid.uuid4().hex}
                            fc_item = {"id": fc_id, "type": "function_call",
                                       "status": "in_progress",
                                       "call_id": tool_items[idx]["call_id"],
                                       "name": "", "arguments": ""}
                            sse(self, "response.output_item.added",
                                {"type": "response.output_item.added",
                                 "response_id": resp_id,
                                 "output_index": output_idx, "item": fc_item})
                            output_idx += 1
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tool_items[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_items[idx]["arguments"] += fn["arguments"]
                            sse(self, "response.function_call_arguments.delta",
                                {"type": "response.function_call_arguments.delta",
                                 "response_id": resp_id,
                                 "item_id": tool_items[idx]["id"],
                                 "output_index": output_idx - 1,
                                 "delta": fn["arguments"]})

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            sse(self, "response.error", {"type": "error", "code": str(e.code),
                "message": "Upstream " + str(e.code) + ": " + err_body})
            sse(self, "response.completed", {"type": "response.completed",
                "response": {"id": resp_id, "object": "response",
                             "created_at": created_at, "status": "failed",
                             "model": config["model"], "output": []}})
            return
        except Exception as e:
            sse(self, "response.error", {"type": "error",
                "code": "upstream_error", "message": str(e)[:500]})
            sse(self, "response.completed", {"type": "response.completed",
                "response": {"id": resp_id, "object": "response",
                             "created_at": created_at, "status": "failed",
                             "model": config["model"], "output": []}})
            return

        # --- Close message item ---
        sse(self, "response.output_text.done",
            {"type": "response.output_text.done", "response_id": resp_id,
             "item_id": msg_id, "output_index": 0, "content_index": 0,
             "text": full_text})
        sse(self, "response.content_part.done",
            {"type": "response.content_part.done", "response_id": resp_id,
             "item_id": msg_id, "output_index": 0, "content_index": 0,
             "part": {"type": "output_text", "text": full_text,
                      "annotations": []}})
        msg_item["content"] = [{"type": "output_text", "text": full_text,
                                "annotations": []}]
        msg_item["status"] = "completed"
        sse(self, "response.output_item.done",
            {"type": "response.output_item.done", "response_id": resp_id,
             "output_index": 0, "item": msg_item})

        # --- Close reasoning item if present ---
        if reasoning_id:
            rsn_done = {"id": reasoning_id, "type": "reasoning",
                        "status": "completed", "content": reasoning_text}
            sse(self, "response.output_item.done",
                {"type": "response.output_item.done", "response_id": resp_id,
                 "output_index": 1, "item": rsn_done})

        # --- Close tool_calls items ---
        for idx in sorted(tool_items.keys()):
            tc = tool_items[idx]
            sse(self, "response.function_call_arguments.done",
                {"type": "response.function_call_arguments.done",
                 "response_id": resp_id, "item_id": tc["id"],
                 "output_index": 0, "arguments": tc["arguments"]})
            fc_done = {"id": tc["id"], "type": "function_call",
                       "status": "completed", "call_id": tc["call_id"],
                       "name": tc["name"], "arguments": tc["arguments"]}
            sse(self, "response.output_item.done",
                {"type": "response.output_item.done", "response_id": resp_id,
                 "output_index": 0, "item": fc_done})

        # --- response.completed ---
        output = [msg_item]
        if reasoning_id:
            output.append(rsn_done)
        sse(self, "response.completed",
            {"type": "response.completed",
             "response": {"id": resp_id, "object": "response",
                          "created_at": created_at, "status": "completed",
                          "model": config["model"], "output": output,
                          "usage": final_usage}})

def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"dubhe codex adapter on http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    main()
