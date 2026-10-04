from threading import Thread
import gc
import multiprocessing as mp
import traceback
from pathlib import Path

from setup.main_setup import rerun_script
from constants import APP_FOLDER

try:
    from llama_cpp import Llama
    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import Button, Input, Markdown, Select, Static
except ModuleNotFoundError:
    rerun_script(Path(__file__).resolve())
    raise SystemExit


APP_NAME = "CLI Studio"
MODEL_ROOT = Path(APP_FOLDER) / "models"
N_CTX = 8192
N_THREADS = 8
N_GPU_LAYERS = 0
TEMPERATURE = 0.7
TOP_P = 0.9

running_sever_socket = False

def run_socket():
    rerun_script(Path(f"{APP_FOLDER}\\sockets\\socket_handler.py"))

def start_server(
    result_queue: mp.Queue
):
    global running_sever_socket
    if not running_sever_socket:
        result_queue.put("running server socket")
        Thread(daemon=True, target=run_socket, args=("Worker-1",)).run()
        result_queue.put("ran server socket")

def model_worker(
    command_queue: mp.Queue,
    result_queue: mp.Queue,
    model_path: str,
) -> None:
    """Owns the llama.cpp model in a separate process.

    Keeping llama.cpp out of the Textual process guarantees that a large
    model load or inference cannot block the Textual event loop.
    """
    try:
        path = Path(model_path)
        result_queue.put(("loading", path.name))

        llm = Llama(
            model_path=str(path),
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )

        result_queue.put(("loaded", path.name))

        while True:
            command = command_queue.get()
            kind = command[0]

            if kind == "shutdown":
                return

            if kind != "generate":
                continue

            messages = command[1]
            response = ""
            result_queue.put(("generation_started",))

            try:
                stream = llm.create_chat_completion(
                    messages=messages,
                    stream=True,
                    temperature=TEMPERATURE,
                    top_p=TOP_P,
                    max_tokens=None,
                )

                for chunk in stream:
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    token = delta.get("content", "") or ""
                    if not token:
                        continue

                    response += token
                    result_queue.put(("token", token))

                result_queue.put(("generation_done", response))
            except Exception:
                result_queue.put(("generation_error", traceback.format_exc()))

    except Exception:
        result_queue.put(("load_error", traceback.format_exc()))


class ChatApp(App[str | None]):
    CSS = """
    Screen {
        background: #0f1117;
        border: round #252936;
    }

    #topbar {
        height: 4;
        width: 100%;
        background: #11141b;
        border-bottom: solid #252936;
        padding: 0 1;
        align-vertical: middle;
    }

    #brand {
        width: 1fr;
        height: 1;
        color: #f1f3f8;
        text-style: bold;
    }

    #model-controls {
        width: auto;
        height: 3;
        align-vertical: middle;
    }

    #model-select {
        width: 42;
        height: 3;
        margin-right: 1;
    }

    #load-model-button {
        width: 10;
        min-width: 10;
        height: 3;
        margin-right: 1;
        background: #202633;
        color: #e8ebf2;
        border: round #353d4d;
    }

    #load-model-button:hover {
        background: #2a3140;
        border: round #52617a;
    }

    #refresh-models-button {
        width: 4;
        min-width: 4;
        height: 3;
        margin-right: 1;
        background: #181c24;
        color: #c9ceda;
        border: round #2d3340;
    }

    #refresh-models-button:hover {
        background: #252b36;
    }

    #model-status {
        width: auto;
        height: 3;
        align-vertical: middle;
        margin-right: 1;
    }

    #model-dot {
        width: 2;
        color: #e06c75;
        text-style: bold;
        content-align: center middle;
    }

    #model-name {
        width: 22;
        height: 1;
        color: #c9ceda;
        content-align: left middle;
    }

    #exit-button {
        width: 9;
        min-width: 9;
        height: 3;
        background: #181c24;
        color: #c9ceda;
        border: round #2d3340;
    }

    #exit-button:hover {
        background: #252b36;
        border: round #52617a;
    }

    #chat {
        height: 1fr;
        width: 100%;
        padding: 2 3;
        scrollbar-size-vertical: 1;
    }

    .message-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    .user-row {
        align: right top;
    }

    .assistant-row {
        align: left top;
    }

    .message-bubble {
        width: auto;
        max-width: 72%;
        height: auto;
        padding: 1 2;
        border: round #2a2f3a;
        color: #e8ebf2;
    }

    .user-bubble {
        background: #222733;
        border: round #343b4a;
    }

    .assistant-bubble {
        background: #151922;
        border: round #252b36;
    }

    #composer-area {
        height: auto;
        width: 100%;
        padding: 0 3 2 3;
    }

    #composer {
        width: 100%;
        height: 4;
        align-vertical: middle;
    }

    #plus-button {
        width: 5;
        min-width: 5;
        height: 3;
        margin-right: 1;
        background: #181c24;
        color: #c7ccd7;
        border: round #2d3340;
    }

    #plus-button:hover {
        background: #252b36;
        border: round #52617a;
    }

    #message-input {
        width: 1fr;
        height: 3;
        border: round #2d3340;
        background: #151922;
        color: #e8ebf2;
    }

    #message-input:focus {
        border: round #52617a;
    }

    #status {
        height: 1;
        width: 100%;
        margin-top: 1;
        color: #72798a;
        text-align: center;
    }

    Button {
        text-style: bold;
    }

    Markdown {
        width: auto;
        height: auto;
    }
    """

    BINDINGS = [
        ("escape", "clear_input", "Clear"),
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "exit_chat", "Exit Chat"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a helpful local AI assistant. "
                    "Be concise, accurate, and useful."
                ),
            }
        ]
        self.model_process: mp.Process | None = None
        self.command_queue: mp.Queue | None = None
        self.result_queue: mp.Queue | None = None
        self.model_path: Path | None = None
        self.loading_model = False
        self.generating = False
        self.current_response: Markdown | None = None
        self.response_text = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(APP_NAME, id="brand")

            with Horizontal(id="model-controls"):
                yield Select(
                    [],
                    prompt="Select a GGUF model",
                    allow_blank=True,
                    id="model-select",
                )
                yield Button("Load", id="load-model-button")
                yield Button("↻", id="refresh-models-button")

                with Horizontal(id="model-status"):
                    yield Static("●", id="model-dot")
                    yield Static("No model loaded", id="model-name")

                yield Button("Exit", id="exit-button")

        yield VerticalScroll(id="chat")

        with Vertical(id="composer-area"):
            with Horizontal(id="composer"):
                yield Button("+", id="plus-button")
                yield Input(
                    placeholder="Ask anything...",
                    id="message-input",
                )
            yield Static("Select a model and press Load", id="status")

    def on_mount(self) -> None:
        self.refresh_model_list()
        self.set_interval(0.05, self.poll_model_queue)
        self.call_after_refresh(self.focus_message_input)

    def on_ready(self) -> None:
        self.call_after_refresh(self.focus_message_input)

    def focus_message_input(self) -> None:
        input_widget = self.query_one("#message-input", Input)
        if not input_widget.disabled:
            input_widget.focus()

    def find_models(self) -> list[Path]:
        if not MODEL_ROOT.exists():
            return []

        return sorted(
            MODEL_ROOT.rglob("*.gguf"),
            key=lambda path: path.name.lower(),
        )

    def refresh_model_list(self) -> None:
        select = self.query_one("#model-select", Select)
        models = self.find_models()

        options = [(model.name, str(model.resolve())) for model in models]
        select.set_options(options)
        select.clear()

        if models:
            self.set_status(
                f"Found {len(models)} GGUF model(s). Select one and press Load."
            )
        else:
            self.set_status("No GGUF models found in the models folder.")

        self.call_after_refresh(self.focus_message_input)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "model-select":
            return

        if event.value is Select.NULL:
            return

        selected = Path(str(event.value))
        self.set_status(f"Selected {selected.name} — press Load.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "plus-button":
            self.set_status("Attachments/tools coming soon.")
            self.focus_message_input()
            return

        if button_id == "refresh-models-button":
            if self.loading_model:
                return
            self.refresh_model_list()
            return

        if button_id == "load-model-button":
            if self.generating:
                self.set_status("Wait for the current response to finish.")
                return

            if self.loading_model:
                return

            if self.model_process is not None and self.model_process.is_alive():
                self.unload_model()
                return

            select = self.query_one("#model-select", Select)
            selected = select.value

            if selected is Select.NULL:
                self.set_status("Select a GGUF model first.")
                return

            self.start_model_load(Path(str(selected)))
            return

        if button_id == "exit-button":
            self.stop_model_process()
            self.exit()

    def start_model_load(self, path: Path) -> None:
        if not path.is_file():
            self.set_status("That GGUF file no longer exists.")
            return

        self.stop_model_process()
        self.loading_model = True
        self.model_path = path

        self.set_model_controls(True)
        self.set_load_button("Loading")
        self.set_model_status(False, path.name)
        self.set_status(f"Loading {path.name}...")

        ctx = mp.get_context("spawn")
        self.command_queue = ctx.Queue()
        self.result_queue = ctx.Queue()
        self.model_process = ctx.Process(
            target=model_worker,
            args=(self.command_queue, self.result_queue, str(path)),
            daemon=True,
        )
        self.model_process.start()

    def poll_model_queue(self) -> None:
        queue = self.result_queue
        if queue is None:
            return

        while True:
            try:
                message = queue.get_nowait()
            except Exception:
                break

            kind = message[0]

            if kind == "loading":
                self.set_status(f"Loading {message[1]}...")
                continue

            if kind == "loaded":
                self.loading_model = False
                self.set_model_controls(False)
                self.set_load_button("Unload")
                self.set_model_status(True, message[1])
                self.set_status(f"Loaded {message[1]} — Ready")
                self.focus_message_input()
                continue

            if kind == "load_error":
                self.loading_model = False
                self.model_path = None
                self.set_model_controls(False)
                self.set_load_button("Load")
                self.set_model_status(False, "No model loaded")
                self.set_status("Model load failed. See terminal for details.")
                print(message[1])
                self.stop_model_process()
                self.focus_message_input()
                continue

            if kind == "generation_started":
                self.set_status("Generating...")
                continue

            if kind == "token":
                self.response_text += message[1]
                self.update_streaming_response(self.response_text)
                continue

            if kind == "generation_done":
                response = message[1]
                if response:
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": response,
                        }
                    )
                self.generation_finished()
                continue

            if kind == "generation_error":
                self.generation_failed(message[1])
                continue

    def set_model_controls(self, disabled: bool) -> None:
        self.query_one("#model-select", Select).disabled = disabled
        self.query_one("#refresh-models-button", Button).disabled = disabled
        self.query_one("#load-model-button", Button).disabled = disabled

    def set_load_button(self, label: str) -> None:
        self.query_one("#load-model-button", Button).label = label

    def set_model_status(self, ready: bool, name: str) -> None:
        dot = self.query_one("#model-dot", Static)
        model_name = self.query_one("#model-name", Static)
        dot.update("●")
        model_name.update(name)
        dot.styles.color = "#63d297" if ready else "#e06c75"

    def unload_model(self) -> None:
        if self.generating:
            self.set_status("Wait for the current response to finish.")
            return

        self.stop_model_process()
        self.model_path = None
        self.loading_model = False
        self.set_load_button("Load")
        self.set_model_status(False, "No model loaded")
        self.set_model_controls(False)
        self.set_status("Model unloaded.")
        self.focus_message_input()

    def stop_model_process(self) -> None:
        process = self.model_process

        if process is not None:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

            if process.is_alive():
                process.kill()
                process.join(timeout=1)

        self.model_process = None
        self.command_queue = None
        self.result_queue = None
        gc.collect()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "message-input":
            return
        self.send_message(event.value.strip())

    def send_message(self, message: str) -> None:
        if not message:
            return

        if self.model_process is None or not self.model_process.is_alive():
            self.set_status("Load a model before sending a message.")
            return

        if self.generating:
            return

        input_widget = self.query_one("#message-input", Input)
        input_widget.value = ""
        input_widget.disabled = True

        self.add_message("user", message)
        self.messages.append({"role": "user", "content": message})

        self.generating = True
        self.response_text = ""
        self.begin_assistant_message()
        self.set_status("Generating...")

        assert self.command_queue is not None
        self.command_queue.put(("generate", list(self.messages)))

    def add_message(self, role: str, content: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)

        bubble = Static(
            content,
            classes="message-bubble "
            + ("user-bubble" if role == "user" else "assistant-bubble"),
        )
        row = Horizontal(
            bubble,
            classes="message-row " + ("user-row" if role == "user" else "assistant-row"),
        )

        # Mount the whole widget tree at once. A newly-created Horizontal is
        # not attached to the app yet, so calling row.mount(...) before
        # chat.mount(row) raises MountError.
        chat.mount(row)
        chat.call_after_refresh(chat.scroll_end, animate=False)

    def begin_assistant_message(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)

        bubble = Markdown(
            "...",
            classes="message-bubble assistant-bubble",
            id="streaming-response",
        )
        row = Horizontal(
            bubble,
            classes="message-row assistant-row",
        )

        # As above, construct the child relationship first, then mount the
        # complete row into the already-mounted chat container.
        chat.mount(row)
        self.current_response = bubble
        chat.call_after_refresh(chat.scroll_end, animate=False)

    def update_streaming_response(self, content: str) -> None:
        if self.current_response is None:
            return

        self.current_response.update(content or "...")
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def generation_finished(self) -> None:
        self.generating = False
        input_widget = self.query_one("#message-input", Input)
        input_widget.disabled = False
        input_widget.value = ""
        input_widget.focus()
        self.set_status("Ready")
        self.current_response = None
        self.response_text = ""

    def generation_failed(self, error: str) -> None:
        self.generating = False
        input_widget = self.query_one("#message-input", Input)
        input_widget.disabled = False

        if self.current_response is not None:
            self.current_response.update(
                "**Generation failed**\n\n```text\n" + error + "\n```"
            )

        self.set_status("Generation failed. See terminal for details.")
        print(error)
        input_widget.focus()
        self.current_response = None
        self.response_text = ""

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_clear_input(self) -> None:
        input_widget = self.query_one("#message-input", Input)
        input_widget.value = ""
        input_widget.focus()

    def action_exit_chat(self) -> None:
        self.stop_model_process()
        self.exit()

    def on_unmount(self) -> None:
        self.stop_model_process()


if __name__ == "__main__":
    mp.freeze_support()
    ChatApp().run()