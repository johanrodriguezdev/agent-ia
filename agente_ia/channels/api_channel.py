import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

API_PORT = 8723


class _APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug(f"API: {args[0]} {args[1]}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return json.loads(self.rfile.read(length))
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok", "service": "Noddoo API"})
        elif parsed.path == "/tasks":
            from tasks.task_manager import task_manager
            user_id = parse_qs(parsed.query).get("user_id", ["default"])[0]
            tasks = task_manager.list_all_tasks(user_id, limit=20)
            self._send_json({"tasks": tasks})
        elif parsed.path == "/memory":
            from ai.memory_manager import memory
            user_id = parse_qs(parsed.query).get("user_id", ["default"])[0]
            q = parse_qs(parsed.query).get("q", [""])[0]
            if q:
                results = memory.search_semantic(q, user_id=user_id, top_k=5)
                self._send_json({"results": [{"text": r.text, "importance": r.importance, "category": r.category} for r in results]})
            else:
                important = memory.get_important_memories(user_id, limit=10)
                self._send_json({"memories": [{"text": r.text, "importance": r.importance, "category": r.category} for r in important]})
        elif parsed.path == "/audit":
            from core.security_manager import security_manager
            log = security_manager.get_audit_log(50)
            self._send_json({"audit_log": log})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._read_body()
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        if parsed.path == "/chat":
            text = body.get("text", "")
            user_id = body.get("user_id", "default")
            if not text:
                self._send_json({"error": "text is required"}, 400)
                return
            from channels.gateway import GlassGateway, GlassMessage
            from channels.gateway import MessageType
            gateway = GlassGateway()
            msg = GlassMessage(user_id=user_id, user_name=body.get("name", ""), text=text, channel="api", msg_type=MessageType.TEXT)
            resp = gateway.process(msg)
            self._send_json({"response": resp.text})
        elif parsed.path == "/tasks":
            from tasks.task_manager import task_manager
            title = body.get("title", "")
            user_id = body.get("user_id", "default")
            if not title:
                self._send_json({"error": "title is required"}, 400)
                return
            task = task_manager.create_task(user_id=user_id, title=title, channel="api",
                                            remind_at=body.get("remind_at"),
                                            recurrence=body.get("recurrence"),
                                            priority=body.get("priority", "normal"))
            self._send_json({"task": task, "message": "Task created"}, 201)
        else:
            self._send_json({"error": "not found"}, 404)


class APIServer:
    def __init__(self, port: int = API_PORT):
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        if self._server:
            return
        self._server = HTTPServer(("0.0.0.0", self.port), _APIHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="APIServer")
        self._thread.start()
        logger.info(f"API REST iniciada en http://0.0.0.0:{self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("API REST detenida")


api_server = APIServer()
