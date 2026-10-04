from pathlib import Path
from constants import APP_FOLDER
from setup.main_setup import rerun_script

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Static
except ModuleNotFoundError:
    rerun_script(Path(__file__).resolve())


class MainMenu(App[str | None]):
    """CLI Studio main launcher."""

    CSS = """
    Screen {
        background: #0f1117;
    }

    #main {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    #content {
        width: 72;
        height: auto;
    }

    #title {
        width: 100%;
        height: auto;
        text-align: center;
        color: #f1f3f8;
        text-style: bold;
        margin-bottom: 1;
    }

    #subtitle {
        width: 100%;
        height: auto;
        text-align: center;
        color: #7f8798;
        margin-bottom: 3;
    }

    #cards {
        width: 100%;
        height: 12;
    }

    .card {
        width: 1fr;
        height: 12;
        margin: 0 1;
        border: round #2a2f3a;
        background: #151922;
    }

    .card:hover {
        background: #1c212c;
        border: round #52617a;
    }

    .card-title {
        width: 100%;
        height: auto;
        margin-top: 2;
        text-align: center;
        color: #f1f3f8;
        text-style: bold;
    }

    .card-description {
        width: 100%;
        height: auto;
        margin: 1 2;
        text-align: center;
        color: #7f8798;
    }

    .card-button {
        width: 80%;
        margin: 1 2;
    }

    #status {
        width: 100%;
        height: auto;
        margin-top: 3;
        text-align: center;
        color: #7f8798;
    }

    #quit-row {
        width: 100%;
        height: auto;
        align-horizontal: center;
    }

    #quit-button {
        width: 20;
        margin: 2 0 0 0;
        background: #181c24;
        border: round #2a2f3a;
    }
    """

    BINDINGS = [
        ("d", "downloads", "Models"),
        ("c", "chat", "Chat"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.model_count = self.get_model_count()

    def get_model_count(self) -> int:
        model_root = Path(APP_FOLDER) / "models"

        if not model_root.exists():
            return 0

        return len(
            list(model_root.rglob("*.gguf"))
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="main"):
            with Vertical(id="content"):

                yield Static(
                    "CLI Studio Main Menu Selection",
                    id="title",
                )

                yield Static(
                    "CLI Studio - Model managing - Built-in Chat App",
                    id="subtitle",
                )

                with Horizontal(id="cards"):

                    with Vertical(classes="card"):
                        yield Static(
                            "MODEL LIBRARY",
                            classes="card-title",
                        )

                        yield Static(
                            "Search Hugging Face and "
                            "download GGUF models.",
                            classes="card-description",
                        )

                        yield Button(
                            "Download Models",
                            id="download-button",
                            classes="card-button",
                            variant="primary",
                        )

                    with Vertical(classes="card"):
                        yield Static(
                            "CHAT",
                            classes="card-title",
                        )

                        yield Static(
                            "Chat with your installed "
                            "local models.",
                            classes="card-description",
                        )

                        yield Button(
                            "Open Chat",
                            id="chat-button",
                            classes="card-button",
                            variant="primary",
                        )

                if self.model_count == 0:
                    status = (
                        "No GGUF models installed • "
                        "Download a model to start chatting"
                    )
                elif self.model_count == 1:
                    status = "1 GGUF model installed"
                else:
                    status = (
                        f"{self.model_count} "
                        "GGUF models installed"
                    )

                yield Static(
                    status,
                    id="status",
                )

                with Horizontal(id="quit-row"):
                    yield Button(
                        "Quit",
                        id="quit-button",
                    )

        yield Footer()

    def on_button_pressed(
        self,
        event: Button.Pressed,
    ) -> None:

        if event.button.id == "download-button":
            self.exit("downloads")

        elif event.button.id == "chat-button":
            self.exit("chat")

        elif event.button.id == "quit-button":
            self.exit("quit")

    def action_downloads(self) -> None:
        self.exit("downloads")

    def action_chat(self) -> None:
        self.exit("chat")

    def action_quit_app(self) -> None:
        self.exit("quit")


def main() -> None:

    while True:

        choice = MainMenu().run()

        if choice == "downloads":
            from interface.downloads import Download

            Download().run()

        elif choice == "chat":
            from interface.chat import ChatApp

            ChatApp().run()

        else:
            break


if __name__ == "__main__":
    main()