import json
import time
from websocket import create_connection

from app.config import config


class ZookeeperAgent:
    """
    Thin client for Zoo's Agent API "Zookeeper" (ws /ws/ml/copilot).

    This is the AI-powered CAD assistant agent. It can:
      - reason about a drawing image / PDF,
      - use tools: edit_kcl_code, text_to_cad, mechanical_knowledge_base, web_search,
      - keep state across prompts via a conversation_id.

    Wire protocol (from the Zoo OpenAPI schemas MlCopilot*):
      client -> { type: headers } auth, { type: system, command } sysctrl,
                { type: project_context }, { type: user, content, additional_files }
      server -> session_data, conversation_id, reasoning, delta, end_of_stream, error...
    """

    def __init__(self):
        self.api_key = config.ZOO_API_KEY
        self.url = f"{config.ZOO_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/ml/copilot"

    def open(self, conversation_id: str = None) -> "ZookeeperSession":
        return ZookeeperSession(self, conversation_id)


class ZookeeperSession:
    def __init__(self, agent: ZookeeperAgent, conversation_id: str = None):
        self.agent = agent
        self.conversation_id = conversation_id or ""
        self.socket = create_connection(
            self.agent.url + (f"?conversation_id={conversation_id}" if conversation_id else ""),
            timeout=120, enable_multithread=True,
        )
        self._send({"type": "headers", "headers": {"Authorization": f"Bearer {agent.api_key}"}})
        self._handshake()

    def _send(self, payload: dict) -> None:
        self.socket.send(json.dumps(payload))

    def _next(self) -> dict:
        try:
            return json.loads(self.socket.recv())
        except Exception as e:
            return {"error": {"detail": f"recv error: {e}"}}

    def _handshake(self) -> None:
        """Wait for auth + conversation id so the caller can act on the session base."""
        got_conv = bool(self.conversation_id)
        deadline = time.time() + 15
        while time.time() < deadline:
            m = self._next()
            if "error" in m and not got_conv:
                # first nag message before auth is applied — ignore
                continue
            if m.get("conversation_id"):
                self.conversation_id = m["conversation_id"]["conversation_id"]
                got_conv = True
                return
            if "session_data" in m and got_conv:
                return

    def reset(self) -> str:
        """Start a brand new conversation, returns the new conversation_id."""
        self._send({"type": "system", "command": "new"})
        deadline = time.time() + 15
        while time.time() < deadline:
            m = self._next()
            if m.get("conversation_id"):
                self.conversation_id = m["conversation_id"]["conversation_id"]
                return self.conversation_id
        return self.conversation_id

    def prompt(self, content: str, files: list = None, mode: str = "fast",
               forced_tools: list = None) -> dict:
        """
        Send a user prompt (optionally with drawing image files) and stream the
        agent's full text response. Returns {reply, reasoning, tools, kcl_files}.
        If the agent writes/edits KCL (edit_kcl_code), the authoritative KCL is
        returned in `kcl_files` (dict name -> source) captured from tool_output /
        project_updated messages.
        """
        msg = {
            "type": "user",
            "mode": mode,
            "content": content,
        }
        if files:
            msg["additional_files"] = files
        if forced_tools:
            msg["forced_tools"] = forced_tools
        self._send(msg)

        reasoning = []
        parts = []
        tools = []
        kcl_files = {}
        whole_response = ""
        deadline = time.time() + 160
        while time.time() < deadline:
            m = self._next()
            if "error" in m:
                return {"reply": "".join(parts).strip(), "reasoning": reasoning, "tools": tools,
                        "kcl_files": kcl_files, "error": m["error"]}
            if m.get("end_of_stream") is not None:
                whole_response = (m["end_of_stream"].get("whole_response") or "") if isinstance(m["end_of_stream"], dict) else ""
                break
            if "reasoning" in m:
                r = m["reasoning"]
                reasoning.append(r.get("content", "") if isinstance(r, dict) else str(r))
            if "delta" in m:
                parts.append(m["delta"].get("delta", ""))
            # Tool output: edit_kcl_code -> result.outputs (name: kcl source)
            if "tool_output" in m:
                to = m["tool_output"]
                tools.append(to)
                result = to.get("result") if isinstance(to, dict) else None
                if not isinstance(result, dict):
                    result = to
                out = result.get("outputs") or {}
                for name, kcl in out.items():
                    if isinstance(kcl, str):
                        kcl_files[name] = kcl
            # The project after the engine applied the edits
            if "project_updated" in m and isinstance(m["project_updated"], dict):
                for name, kcl in (m["project_updated"].get("files") or {}).items():
                    kcl_files[name] = kcl
            if "files" in m and isinstance(m["files"], dict):
                for fl in m["files"].get("files") or []:
                    if isinstance(fl, dict) and fl.get("name") and fl.get("data"):
                        try:
                            kcl_files[fl["name"]] = bytes(fl["data"]).decode("utf-8", "replace")
                        except Exception:
                            pass
        reply = "".join(parts).strip() or whole_response
        return {
            "reply": reply,
            "whole_response": whole_response,
            "reasoning": "\n".join(reasoning).strip(),
            "tools": tools,
            "kcl_files": kcl_files,
            "error": None,
        }

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass


zookeeper = ZookeeperAgent()

import concurrent.futures


def run_parallel_part_tasks(tasks: list, max_workers: int = 4) -> list:
    """
    Execute multiple Zookeeper part-design tasks concurrently.

    `tasks` is a list of dicts:
        {"prompt": str, "files": list|None, "mode": str, "forced_tools": list|None}
    Returns a list (same order) of result dicts from ZookeeperSession.prompt().

    Uses a fresh WebSocket session per task via a thread pool so the agent
    works each part in parallel. Falls back to sequential if threading is
    unavailable or the API rejects concurrent connections.
    """
    def _one(task):
        sess = None
        try:
            sess = zookeeper.open(None)
            return sess.prompt(
                task.get("prompt", ""),
                files=task.get("files"),
                mode=task.get("mode", "thoughtful"),
                forced_tools=task.get("forced_tools"),
            )
        except Exception as e:
            return {"reply": "", "reasoning": "", "tools": [], "kcl_files": {}, "error": str(e)}
        finally:
            if sess:
                try:
                    sess.close()
                except Exception:
                    pass

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_one, tasks))
    except Exception:
        return [_one(t) for t in tasks]