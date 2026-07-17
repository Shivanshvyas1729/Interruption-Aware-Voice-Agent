import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from common.logging.logger import get_logger

logger = get_logger("orchestrator")

class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default console logs to keep test output clean
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def make_server(port: int = 8000) -> HTTPServer:
    """Creates the HTTP server instance and emits service_started log."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.log(
        event_name="service_started",
        session_id="system",
        turn_id="system",
        detail={"port": port}
    )
    return server

def run_server(port: int = 8000) -> None:
    server = make_server(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port)
