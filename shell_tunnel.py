#!/usr/bin/env python3
"""
HTTP Shell Service exposed via Cloudflare Tunnel.

Endpoints:
  POST /exec     — run a command, return JSON {stdout, stderr, returncode}
  POST /upload   — upload a file: {path, content (base64), mode?}
  GET  /download?path=<filepath> — download a file
  GET  /          — health check

Starts a local HTTP server and a cloudflared tunnel to expose it publicly.
"""

import http.server
import json
import subprocess
import threading
import re
import signal
import sys
import os
import platform
import time
import urllib.request
import base64
import urllib.parse
import mimetypes

PORT = 8787
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(SCRIPT_DIR, "cloudflared")


def get_cloudflared_url():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            arch = "amd64"
        elif machine in ("aarch64", "arm64"):
            arch = "arm64"
        else:
            arch = "amd64"
        return f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    elif system == "darwin":
        return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
    else:
        sys.exit(f"Unsupported platform: {system}/{machine}")


def ensure_cloudflared():
    if os.path.isfile(CLOUDFLARED) and os.access(CLOUDFLARED, os.X_OK):
        return

    url = get_cloudflared_url()
    print(f"cloudflared not found, downloading from:\n  {url}")

    if url.endswith(".tgz"):
        import tarfile
        import io
        data = urllib.request.urlopen(url).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extract("cloudflared", path=SCRIPT_DIR)
    else:
        urllib.request.urlretrieve(url, CLOUDFLARED)

    os.chmod(CLOUDFLARED, 0o755)
    print("cloudflared downloaded successfully.")


class ShellHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._json_response(200, {"status": "ok", "message": "Shell tunnel active"})
        elif self.path.startswith("/download"):
            self._handle_download()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_download(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        filepath = params.get("path", [None])[0]

        if not filepath:
            self._json_response(400, {"error": "missing 'path' query parameter"})
            return

        filepath = os.path.abspath(filepath)

        if not os.path.isfile(filepath):
            self._json_response(404, {"error": f"file not found: {filepath}"})
            return

        try:
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                mime_type = "application/octet-stream"

            with open(filepath, "rb") as f:
                data = f.read()

            filename = os.path.basename(filepath)
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)
        except PermissionError:
            self._json_response(403, {"error": f"permission denied: {filepath}"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def do_POST(self):
        if self.path == "/exec":
            self._handle_exec()
        elif self.path == "/upload":
            self._handle_upload()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_upload(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return

        filepath = data.get("path")
        content = data.get("content")

        if not filepath or content is None:
            self._json_response(400, {"error": "missing 'path' or 'content' field"})
            return

        filepath = os.path.abspath(filepath)

        try:
            file_bytes = base64.b64decode(content)
        except Exception:
            self._json_response(400, {"error": "invalid base64 in 'content'"})
            return

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(file_bytes)

            mode = data.get("mode")
            if mode:
                os.chmod(filepath, int(mode, 8))

            print(f"[upload] {filepath} ({len(file_bytes)} bytes)")
            sys.stdout.flush()
            self._json_response(200, {
                "status": "ok",
                "path": filepath,
                "size": len(file_bytes),
            })
        except PermissionError:
            self._json_response(403, {"error": f"permission denied: {filepath}"})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _handle_exec(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return

        cmd = data.get("cmd")
        if not cmd:
            self._json_response(400, {"error": "missing 'cmd' field"})
            return

        timeout = data.get("timeout", 30)
        cwd = data.get("cwd", SCRIPT_DIR)

        print(f"\n$ {cmd}")
        sys.stdout.flush()

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            if result.returncode != 0:
                print(f"[exit {result.returncode}]")
            sys.stdout.flush()
            sys.stderr.flush()

            self._json_response(200, {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            print(f"[timed out after {timeout}s]")
            sys.stdout.flush()
            self._json_response(408, {"error": f"command timed out after {timeout}s"})
        except Exception as e:
            print(f"[error: {e}]")
            sys.stdout.flush()
            self._json_response(500, {"error": str(e)})

    def _json_response(self, code, obj):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # silence request logs


def start_tunnel():
    """Start cloudflared and print the public URL."""
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    url_pattern = re.compile(r"(https://[a-z0-9-]+\.trycloudflare\.com)")

    def read_stream(stream):
        for line in stream:
            match = url_pattern.search(line)
            if match:
                url = match.group(1)
                print(f"\n{'='*60}")
                print(f"  TUNNEL URL: {url}")
                print(f"{'='*60}")
                print(f"\nEndpoints:")
                print(f"  POST /exec     — execute a shell command")
                print(f"  POST /upload   — upload a file")
                print(f"  GET  /download — download a file")
                print(f"\nExamples:")
                print(f'  curl -X POST {url}/exec \\')
                print(f'    -H "Content-Type: application/json" \\')
                print(f'    -d \'{{"cmd": "ls -la"}}\'')
                print(f"")
                print(f'  curl -X POST {url}/upload \\')
                print(f'    -H "Content-Type: application/json" \\')
                print(f'    -d \'{{"path": "/tmp/hello.txt", "content": "'
                       f'{base64.b64encode(b"hello").decode()}"}}\'')
                print(f"")
                print(f'  curl -O "{url}/download?path=/tmp/hello.txt"')
                print()

    threading.Thread(target=read_stream, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=read_stream, args=(proc.stderr,), daemon=True).start()
    return proc


def main():
    ensure_cloudflared()

    print(f"Starting shell server on port {PORT}...")
    server = http.server.HTTPServer(("0.0.0.0", PORT), ShellHandler)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Server listening on http://localhost:{PORT}")

    print("Starting cloudflare tunnel...")
    tunnel_proc = start_tunnel()

    def shutdown(sig, frame):
        print("\nShutting down...")
        tunnel_proc.terminate()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
