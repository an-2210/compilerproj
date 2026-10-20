"""Dummy test frontend for the analysis pipeline (no Streamlit, standard library only).

Run from the project root:

    python3 dev_frontend/server.py            # then open http://127.0.0.1:8765

Endpoints:
    GET  /               the test page
    GET  /api/samples    mutated programs from the Data Engineer's splits, for quick testing
    POST /api/analyze    {"code": str, "language": str} -> detection, context and repair

This is a development harness, not the production API (that belongs to the Systems
Engineer). It serves only on 127.0.0.1.
"""

import json
import sys
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis_engine import build_context, detect, rule_repair  # noqa: E402

PAGE = Path(__file__).resolve().parent / "index.html"
SAMPLE_FILES = ["data/splits/test.jsonl", "data/splits/real_test.jsonl", "data/splits/val.jsonl"]
MAX_CODE_CHARS = 20_000
HOST, PORT = "127.0.0.1", 8765


def analyze(code: str, language: str) -> Dict[str, Any]:
    """Run detect -> build_context -> rule_repair and return JSON-ready data."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"code is longer than {MAX_CODE_CHARS} characters")

    detection = detect(code, language)
    payload: Dict[str, Any] = {
        "detection": detection.model_dump(),
        "context": None,
        "repair": None,
    }
    if detection.root is None:
        return payload

    context = build_context(code, detection.root, language)
    repair = rule_repair(context)
    payload["context"] = context.model_dump(exclude={"code"})
    payload["repair"] = repair.model_dump()
    return payload


@lru_cache(maxsize=1)
def sample_list() -> List[Dict[str, Any]]:
    samples = []
    for rel in SAMPLE_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("source_type") == "seed" or not record.get("mutated_code"):
                continue
            samples.append({
                "id": record["example_id"],
                "split": record.get("split") or "unassigned",
                "language": record["language"],
                "mutated_code": record["mutated_code"],
                "source_code": record["source_code"],
                "operator": (record.get("mutation") or {}).get("operator_id", "REAL_BUG"),
            })
    return samples[:200]


class Handler(BaseHTTPRequestHandler):
    server_version = "AnalysisDevFrontend/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/samples":
            self._send_json(200, sample_list())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/analyze":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_CODE_CHARS * 4:
                self._send_json(413, {"error": "request too large"})
                return
            body = json.loads(self.rfile.read(length) or b"{}")
            result = analyze(body.get("code", ""), body.get("language", "python"))
            self._send_json(200, result)
        except (ValueError, json.JSONDecodeError) as err:
            self._send_json(400, {"error": str(err)})
        except RuntimeError as err:
            # Missing toolchain (for example g++ not installed)
            self._send_json(500, {"error": str(err)})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Analysis dev frontend on http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
