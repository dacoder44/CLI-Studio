import gc
import json
import threading
from pathlib import Path

from imports import Llama, Logger
from constants import DEFUALT_PORT, MODEL_FOLDER
from better_socket import BetterSock


logger = Logger("Sock Handler")


class RequestServer:
    """
    JSON-over-TCP request handler built on BetterSock.

    Protocol:
        Client -> {"id": 1, "action": "ping"}\n
        Server -> {"id": 1, "ok": true, "result": {...}}\n

    Supported actions:
        ping
        status
        list_models
        load_model
        unload_model
        chat

    `chat` can stream tokens:
        {"id": 2, "action": "chat", "messages": [...], "stream": true}
    """

    def __init__(self, model_folder=MODEL_FOLDER):
        self.logger = logger
        self.model_folder = Path(model_folder).resolve()

        self.model = None
        self.loaded_model_path = None

        # llama.cpp model access is serialized so two clients can't generate
        # through the same model object at the same time.
        self.model_lock = threading.RLock()

        # BetterSock gives us arbitrary TCP chunks, not guaranteed messages.
        # We use newline-delimited JSON and keep a buffer for each connection.
        self.buffers = {}
        self.buffer_lock = threading.Lock()

        self.sock = BetterSock(port=DEFUALT_PORT)

        self.sock.on_message(self.handle_message)
        self.sock.on_connect(self.handle_connect)
        self.sock.on_disconnect(self.handle_disconnect)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def handle_connect(self, client_address):
        self.logger.log(f"Client connected: {client_address}")
        with self.buffer_lock:
            self.buffers[client_address] = ""

    def handle_disconnect(self, client_address):
        self.logger.log(f"Client disconnected: {client_address}")
        with self.buffer_lock:
            self.buffers.pop(client_address, None)

    # ------------------------------------------------------------------
    # Protocol helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _send(reply, payload):
        """Send exactly one newline-delimited JSON response."""
        reply(json.dumps(payload, separators=(",", ":")) + "\n")

    def _ok(self, reply, request_id, result=None, event=None):
        payload = {
            "id": request_id,
            "ok": True,
        }

        if event is not None:
            payload["event"] = event

        if result is not None:
            payload["result"] = result

        self._send(reply, payload)

    def _error(self, reply, request_id, message):
        self._send(
            reply,
            {
                "id": request_id,
                "ok": False,
                "error": message,
            },
        )

    # ------------------------------------------------------------------
    # TCP framing
    # ------------------------------------------------------------------

    def handle_message(self, message, reply, client_address):
        """
        BetterSock may call this with only part of a request because TCP is
        stream-based. Accumulate chunks until newline-delimited JSON frames
        are complete.
        """
        with self.buffer_lock:
            buffer = self.buffers.get(client_address, "") + message

            # Put the incomplete tail back into the per-client buffer.
            parts = buffer.split("\n")
            self.buffers[client_address] = parts.pop()

        for raw_request in parts:
            raw_request = raw_request.strip()

            if not raw_request:
                continue

            try:
                request = json.loads(raw_request)
            except json.JSONDecodeError as exc:
                self._error(reply, None, f"Invalid JSON: {exc.msg}")
                continue

            if not isinstance(request, dict):
                self._error(reply, None, "Request must be a JSON object.")
                continue

            request_id = request.get("id")
            self.dispatch(request, request_id, reply)

    # ------------------------------------------------------------------
    # Request routing
    # ------------------------------------------------------------------

    def dispatch(self, request, request_id, reply):
        action = request.get("action")

        if not isinstance(action, str):
            self._error(reply, request_id, "Missing action.")
            return

        handlers = {
            "ping": self.handle_ping,
            "status": self.handle_status,
            "list_models": self.handle_list_models,
            "load_model": self.handle_load_model,
            "unload_model": self.handle_unload_model,
            "chat": self.handle_chat,
        }

        handler = handlers.get(action)

        if handler is None:
            self._error(reply, request_id, f"Unknown action: {action}")
            return

        try:
            handler(request, request_id, reply)
        except Exception as exc:
            self.logger.log(f"{action} failed: {exc}")
            self._error(reply, request_id, str(exc))

    # ------------------------------------------------------------------
    # Basic actions
    # ------------------------------------------------------------------

    def handle_ping(self, request, request_id, reply):
        self._ok(reply, request_id, {"message": "pong"})

    def handle_status(self, request, request_id, reply):
        with self.model_lock:
            result = {
                "loaded": self.model is not None,
                "model": (
                    str(self.loaded_model_path)
                    if self.loaded_model_path is not None
                    else None
                ),
            }

        self._ok(reply, request_id, result)

    def handle_list_models(self, request, request_id, reply):
        self.model_folder.mkdir(parents=True, exist_ok=True)

        models = []

        for path in sorted(self.model_folder.rglob("*.gguf")):
            try:
                relative = path.relative_to(self.model_folder)
            except ValueError:
                continue

            models.append(
                {
                    "name": path.name,
                    "path": str(relative),
                    "size": path.stat().st_size,
                }
            )

        self._ok(reply, request_id, models)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _resolve_model_path(self, requested_path):
        if not isinstance(requested_path, str) or not requested_path.strip():
            raise ValueError("model path is required.")

        root = self.model_folder.resolve()
        requested = Path(requested_path)

        # Allow the client to send either:
        #   "Gemma 4 E2B Q4_K_M.gguf"
        # or:
        #   "models/Gemma 4 E2B Q4_K_M.gguf"
        if not requested.is_absolute():
            candidate = (root / requested).resolve()

            # If the client already included the models folder, try the
            # project-level path as a fallback.
            if not candidate.exists() and requested.parts:
                project_candidate = (root.parent / requested).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
        else:
            candidate = requested.resolve()

        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("Model path must be inside the model folder.")

        if not candidate.is_file():
            raise FileNotFoundError(f"Model not found: {candidate}")

        if candidate.suffix.lower() != ".gguf":
            raise ValueError("Only GGUF models are supported.")

        return candidate

    def handle_load_model(self, request, request_id, reply):
        model_path = self._resolve_model_path(request.get("model"))

        # Optional llama.cpp settings supplied by the client.
        load_params = {
            "n_ctx": int(request.get("n_ctx", 32768)),
            "n_threads": int(request.get("n_threads", 0)),
            "n_gpu_layers": int(request.get("n_gpu_layers", 0)),
            "verbose": bool(request.get("verbose", False)),
        }

        # Treat 0 as "let llama.cpp choose" for thread count by leaving it
        # out rather than forcing n_threads=0.
        if load_params["n_threads"] <= 0:
            load_params.pop("n_threads")

        with self.model_lock:
            # Don't keep two huge GGUFs in memory.
            if self.model is not None:
                self.logger.log(
                    f"Unloading current model: {self.loaded_model_path}"
                )
                self.model = None
                self.loaded_model_path = None
                gc.collect()

            self.logger.log(f"Loading model: {model_path}")

            self.model = Llama(
                model_path=str(model_path),
                **load_params,
            )
            self.loaded_model_path = model_path

        self.logger.log(f"Model loaded: {model_path.name}")

        self._ok(
            reply,
            request_id,
            {
                "model": str(model_path),
                "name": model_path.name,
            },
        )

    def handle_unload_model(self, request, request_id, reply):
        with self.model_lock:
            if self.model is None:
                self._ok(
                    reply,
                    request_id,
                    {
                        "loaded": False,
                        "message": "No model is loaded.",
                    },
                )
                return

            old_name = (
                self.loaded_model_path.name
                if self.loaded_model_path is not None
                else None
            )

            self.model = None
            self.loaded_model_path = None
            gc.collect()

        self._ok(
            reply,
            request_id,
            {
                "loaded": False,
                "unloaded": old_name,
            },
        )

    # ------------------------------------------------------------------
    # Chat / generation
    # ------------------------------------------------------------------

    def handle_chat(self, request, request_id, reply):
        messages = request.get("messages")

        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list.")

        stream = bool(request.get("stream", True))

        generation_params = {
            "messages": messages,
            "temperature": float(request.get("temperature", 0.7)),
            "top_p": float(request.get("top_p", 0.95)),
            "max_tokens": int(request.get("max_tokens", 512)),
            "stream": stream,
        }

        # Only one generation at a time against the shared llama object.
        with self.model_lock:
            if self.model is None:
                raise RuntimeError("No model is loaded.")

            model_name = (
                self.loaded_model_path.name
                if self.loaded_model_path is not None
                else None
            )

            if stream:
                self._ok(
                    reply,
                    request_id,
                    {
                        "model": model_name,
                    },
                    event="start",
                )

                result = self.model.create_chat_completion(
                    **generation_params
                )

                for chunk in result:
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")

                    if token:
                        self._ok(
                            reply,
                            request_id,
                            {"token": token},
                            event="token",
                        )

                self._ok(
                    reply,
                    request_id,
                    {},
                    event="done",
                )

            else:
                result = self.model.create_chat_completion(
                    **generation_params
                )

                choice = result["choices"][0]
                content = choice["message"]["content"]

                self._ok(
                    reply,
                    request_id,
                    {
                        "content": content,
                        "model": model_name,
                    },
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self.sock.start()
        self.logger.log(
            f"Started request server on 127.0.0.1:{DEFUALT_PORT}"
        )

    def stop(self):
        self.sock.stop()


server = RequestServer()

if __name__ == "__main__":
    server.start()

    try:
        # Keep this process alive while BetterSock handles clients in
        # background threads.
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()