"""내 PC 안에서만 열리는 웹서버: 편집툴 화면을 띄우고 Claude 호출·자료 저장을 맡는다."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from balje import llm

from .store import Store, StoreError

SYSTEM = ("너는 한국 신문 편집기자의 피플면 제목 작업을 돕는다. 사용자 메시지에 적힌 지시와 형식을 그대로 따른다. "
          "기사에 없는 사실을 지어내지 않는다.")
JSON_RULE = " 답은 JSON 값 하나만 쓴다. 설명 문장이나 코드 블록 표시 없이."

# claude.ai가 페이지에 씌우는 기본 틀과 같은 모양
HEAD = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        "<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}"
        "img{max-width:100%}[hidden]{display:none!important}</style>")


def resource(rel):
    """exe 안에 함께 묶인 파일 경로(개발 중에는 저장소 안)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def build_page():
    page = resource("haneul/web/index.html").read_text(encoding="utf-8")
    shim = resource("haneul/web/shim.js").read_text(encoding="utf-8")
    return f"{HEAD}<script>{shim}</script></head><body>{page}</body></html>"


def ask_claude(prompt, as_json, config):
    """(text, None) 또는 (None, error). 발제 도우미의 Claude 연결을 그대로 쓴다."""
    text = llm.call_claude(SYSTEM + (JSON_RULE if as_json else ""), prompt, config)
    if not text or text.startswith("> "):
        msg = (text or "> 빈 응답").lstrip("> ").strip()
        return None, {"code": "upstream_error", "message": msg, "detail": msg}
    return text, None


class Handler(BaseHTTPRequestHandler):
    server_version = "Haneul/1"

    def log_message(self, *args):  # 콘솔 창이 없으니 조용히
        pass

    def _host_ok(self):
        # 다른 사이트가 이 주소를 빌려 쓰지 못하게(DNS rebinding) 내 PC 주소로 온 요청만 받는다.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": {"code": "forbidden", "message": "host"}})
        if self.path.split("?")[0] in ("/", "/index.html"):
            return self._send(200, build_page().encode("utf-8"), "text/html; charset=utf-8")
        self._send(404, {"error": {"code": "not_found", "message": self.path}})

    def do_POST(self):
        # 사용자 정의 헤더가 있어야 받는다: 다른 웹사이트의 스크립트는 이 헤더를 붙여 보낼 수 없다.
        if not self._host_ok() or self.headers.get("X-Haneul") != "1":
            return self._send(403, {"error": {"code": "forbidden", "message": "forbidden"}})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": {"code": "invalid_argument", "message": "bad json"}})
        app = self.server.app
        try:
            route = self.path.split("?")[0]
            if route == "/api/sample":
                prompt = str(req.get("prompt") or "")
                if not prompt.strip():
                    return self._send(200, {"error": {"code": "invalid_request", "message": "empty prompt"}})
                text, err = ask_claude(prompt, bool(req.get("json")), app.config())
                return self._send(200, {"error": err} if err else {"text": text})
            st = app.store
            if route == "/api/db/get":
                return self._send(200, {"data": st.get(req.get("path"))})
            if route == "/api/db/set":
                st.set(req.get("path"), req.get("data"))
            elif route == "/api/db/update":
                st.update(req.get("path"), req.get("data"))
            elif route == "/api/db/delete":
                st.delete(req.get("path"))
            elif route == "/api/db/list":
                docs = st.list(req.get("collection"), req.get("orderBy"), req.get("dir") or "asc", req.get("limit"))
                return self._send(200, {"docs": docs})
            else:
                return self._send(404, {"error": {"code": "not_found", "message": route}})
            return self._send(200, {"ok": True})
        except StoreError as e:
            return self._send(200, {"error": {"code": "invalid_argument", "message": str(e)}})
        except OSError as e:
            return self._send(200, {"error": {"code": "unavailable", "message": str(e),
                                              "detail": f"자료 파일에 쓰지 못했습니다: {e}"}})


class App:
    """서버 하나와 그 서버가 쓰는 저장소·설정."""

    def __init__(self, data_file, config_fn, port=0):
        self.store = Store(data_file)
        self.config = config_fn
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self
        self.thread = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.flush()
