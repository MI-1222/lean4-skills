#!/usr/bin/env python3
"""
Lean 4 LSP PlainGoal Extractor.
Uses only the Python 3 standard library to communicate with the Lean 4 Language Server
(lean --server / lake serve) and retrieve the Tactic State (goals) and diagnostics
at a specified file, line, and column.
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url


def to_utf16_col(line_str: str, col_1indexed: int) -> int:
    """
    Convert a 1-indexed character position to a 0-indexed UTF-16 code unit offset.
    Accurately handles surrogate pairs (such as emojis and mathematical symbols).
    """
    if col_1indexed <= 1:
        return 0
    target_str = line_str[: col_1indexed - 1]
    return len(target_str.encode("utf-16le")) // 2


def get_eol_utf16_col(line_str: str) -> int:
    """Calculate the 0-indexed UTF-16 code unit offset at the end of the line (excluding newline)."""
    clean_line = line_str.rstrip("\r\n")
    return len(clean_line.encode("utf-16le")) // 2


class LeanLSPClient:
    """Self-contained client communicating with Lean 4 language server over stdio."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.process = None
        self.reader_thread = None
        self.running = False
        self._request_id = 0
        self._pending_requests = {}
        self._lock = threading.Lock()
        self.diagnostics = []
        self.file_progress = {}
        self.elaboration_done_event = threading.Event()
        self._has_started_processing = False

    def _determine_launch_command(self) -> list:
        """Select the appropriate server launch command based on project configuration."""
        lake_lean = self.project_dir / "lakefile.lean"
        lake_toml = self.project_dir / "lakefile.toml"
        if lake_lean.exists() or lake_toml.exists():
            return ["lake", "serve"]
        return ["lean", "--server"]

    def start(self):
        """Start the language server process, spawn reader thread, and perform handshake."""
        cmd = self._determine_launch_command()
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.project_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.running = True
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        self._perform_handshake()

    def _reader_loop(self):
        """Monitor stdout stream, parse JSON-RPC messages, and dispatch them."""
        stdout = self.process.stdout
        while self.running and self.process.poll() is None:
            try:
                content_length = None
                while True:
                    line = stdout.readline()
                    if not line:
                        self.running = False
                        return
                    header_line = line.decode("ascii", errors="replace").strip()
                    if not header_line:
                        break
                    if header_line.lower().startswith("content-length:"):
                        parts = header_line.split(":", 1)
                        content_length = int(parts[1].strip())

                if content_length is None:
                    continue

                body_bytes = stdout.read(content_length)
                if not body_bytes:
                    break

                message = json.loads(body_bytes.decode("utf-8"))
                self._dispatch_message(message)

            except Exception:
                if not self.running:
                    break

    def _dispatch_message(self, message: dict):
        """Dispatch incoming messages to pending response queues or notification handlers."""
        if "id" in message and message["id"] in self._pending_requests:
            req_id = message["id"]
            resp_queue = self._pending_requests.pop(req_id, None)
            if resp_queue:
                resp_queue.put(message)
        else:
            method = message.get("method")
            if method == "textDocument/publishDiagnostics":
                params = message.get("params", {})
                new_diags = params.get("diagnostics", [])
                self.diagnostics = new_diags
                # Don't set the event for empty diagnostics (initial empty notification at file open).
                # Set the event if there are any compiler errors (severity == 1), as this indicates elaboration has failed.
                if new_diags and any(d.get("severity", 1) == 1 for d in new_diags):
                    self.elaboration_done_event.set()
            elif method == "$/lean/fileProgress":
                params = message.get("params", {})
                processing = params.get("processing", [])
                uri = params.get("textDocument", {}).get("uri")
                self.file_progress[uri] = processing
                if processing:
                    self._has_started_processing = True
                else:
                    # The processing range has become empty, which means elaboration has completed.
                    self.elaboration_done_event.set()

    def _transmit(self, msg: dict):
        """Encode JSON-RPC message and write to server stdin."""
        payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        with self._lock:
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(header + payload)
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    self.running = False

    def send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._transmit(msg)

    def send_request(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        """Send a JSON-RPC request and synchronously await its response."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        resp_queue = queue.Queue(maxsize=1)
        self._pending_requests[req_id] = resp_queue

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        self._transmit(msg)

        try:
            return resp_queue.get(timeout=timeout)
        except queue.Empty:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"LSP request '{method}' (id={req_id}) timed out after {timeout} seconds.")

    def _perform_handshake(self):
        """Execute the LSP initialization sequence (initialize / initialized)."""
        root_uri = urljoin("file:", pathname2url(str(self.project_dir)))
        if not root_uri.endswith("/"):
            root_uri += "/"
        init_params = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "synchronization": {"dynamicRegistration": False, "sendIncremental": False},
                    "publishDiagnostics": {"relatedInformation": True},
                }
            },
        }
        self.send_request("initialize", init_params)
        self.send_notification("initialized", {})

    def open_document(self, file_path: Path, content: str):
        """Open document in server memory to trigger elaboration."""
        self.elaboration_done_event.clear()
        self.diagnostics = []
        self._has_started_processing = False
        uri = urljoin("file:", pathname2url(str(file_path.resolve())))
        params = {
            "textDocument": {
                "uri": uri,
                "languageId": "lean4",
                "version": 1,
                "text": content,
            }
        }
        self.send_notification("textDocument/didOpen", params)

    def wait_for_elaboration(self, timeout: float = 3.0):
        """Wait for elaboration progress notification (fileProgress: empty) or error diagnostics to arrive."""
        self.elaboration_done_event.wait(timeout=timeout)
        # Stabilization wait to absorb slight delays in diagnostic message delivery.
        time.sleep(0.08)

    def fetch_plain_goal(
        self, file_path: Path, line_0indexed: int, col_utf16: int, timeout: float = 8.0
    ) -> dict:
        """
        Retrieve goal state ($/lean/plainGoal) at specified 0-indexed line and UTF-16 column offset.
        Uses exponential backoff polling while elaboration completes.
        """
        uri = urljoin("file:", pathname2url(str(file_path.resolve())))
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line_0indexed, "character": col_utf16},
        }

        deadline = time.time() + timeout
        backoff = 0.05
        last_response = None

        while time.time() < deadline:
            try:
                response = self.send_request("$/lean/plainGoal", params, timeout=timeout)
                if "result" in response:
                    res = response["result"]
                    if res is not None:
                        return res
                last_response = response
            except TimeoutError:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 0.5)

        return last_response.get("result") if (last_response and "result" in last_response) else {}

    def close(self):
        """Gracefully shut down the server process."""
        self.running = False
        try:
            self.send_request("shutdown", {}, timeout=2.0)
            self.send_notification("exit", {})
        except Exception:
            pass
        finally:
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()


def find_project_root(target_file: Path) -> Path:
    """Traverse parent directories to locate Lake project root if available."""
    current = target_file.resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "lakefile.lean").exists() or (parent / "lakefile.toml").exists():
            return parent
    return current


def extract_goal_and_diagnostics(
    file_path: Path, line_1indexed: int, col_1indexed: int = None, timeout: float = 8.0
) -> dict:
    """
    Extract Tactic State and compiler diagnostics at the target position, returning structured JSON.
    """
    if not file_path.exists():
        return {
            "success": False,
            "error": f"File does not exist: {file_path}",
            "rendered": None,
            "goals": [],
            "is_done": False,
            "diagnostics": [],
        }

    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not (1 <= line_1indexed <= len(lines)):
        return {
            "success": False,
            "error": f"Line {line_1indexed} out of range (valid range: 1 - {len(lines)}).",
            "rendered": None,
            "goals": [],
            "is_done": False,
            "diagnostics": [],
        }

    target_line_content = lines[line_1indexed - 1]
    line_0indexed = line_1indexed - 1

    if col_1indexed is not None:
        col_utf16 = to_utf16_col(target_line_content, col_1indexed)
    else:
        col_utf16 = get_eol_utf16_col(target_line_content)

    project_root = find_project_root(file_path)
    client = LeanLSPClient(project_root)

    try:
        client.start()
        content = "".join(lines)
        client.open_document(file_path, content)

        # Wait for elaboration to complete and diagnostics to arrive
        client.wait_for_elaboration(timeout=min(timeout, 3.0))

        # Retrieve plainGoal
        goal_result = client.fetch_plain_goal(
            file_path, line_0indexed, col_utf16, timeout=timeout
        )

        rendered = goal_result.get("rendered") if goal_result else None
        goals = goal_result.get("goals", []) if goal_result else []

        # Compiler diagnostics.
        formatted_diags = []
        severity_map = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}
        has_errors = False
        for diag in client.diagnostics:
            severity_num = diag.get("severity", 1)
            if severity_num == 1:
                has_errors = True
            d_range = diag.get("range", {})
            start_pos = d_range.get("start", {})
            d_line = start_pos.get("line", 0) + 1  # 1-indexed に変換
            d_col = start_pos.get("character", 0) + 1
            formatted_diags.append(
                {
                    "line": d_line,
                    "column": d_col,
                    "severity": severity_map.get(severity_num, "Error"),
                    "message": diag.get("message", "").strip(),
                }
            )

        # Determine if the proof is complete.
        # IMPORTANT: If compiler errors (severity: 1) exist, elaboration has failed or been interrupted.
        # Lean 4's plainGoal returns "no goals" even during type errors, so is_done must never be set to True when errors are present.
        is_done = False
        if not has_errors:
            if rendered:
                clean_rendered = rendered.strip()
                if "goals accomplished" in clean_rendered or "no goals" in clean_rendered:
                    is_done = True
                elif len(goals) == 0:
                    is_done = True
            elif goal_result is not None and len(goals) == 0:
                is_done = True

        return {
            "success": True,
            "line": line_1indexed,
            "column": col_1indexed if col_1indexed is not None else len(target_line_content.rstrip("\r\n")),
            "rendered": rendered,
            "goals": goals,
            "is_done": is_done,
            "diagnostics": formatted_diags,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "rendered": None,
            "goals": [],
            "is_done": False,
            "diagnostics": [],
        }
    finally:
        client.close()


def main():
    """Parse CLI arguments and retrieve goal state."""
    parser = argparse.ArgumentParser(
        description="Retrieve Lean 4 Tactic State (goals) and diagnostics at a specified line and column."
    )
    parser.add_argument("file", type=str, help="Target Lean source file path")
    parser.add_argument(
        "--line", "-l", type=int, required=True, help="1-indexed line number"
    )
    parser.add_argument(
        "--col", "-c", type=int, default=None, help="1-indexed column number (defaults to end of line)"
    )
    parser.add_argument(
        "--timeout", "-t", type=float, default=8.0, help="Elaboration timeout in seconds (default: 8.0)"
    )

    args = parser.parse_args()
    file_path = Path(args.file)

    result = extract_goal_and_diagnostics(
        file_path=file_path,
        line_1indexed=args.line,
        col_1indexed=args.col,
        timeout=args.timeout,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
