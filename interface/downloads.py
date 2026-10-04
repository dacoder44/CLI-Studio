from pathlib import Path

from setup.main_setup import rerun_script
from constants import APP_FOLDER

try:
    from huggingface_hub import HfApi, snapshot_download

    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import Vertical, Horizontal
    from textual.widgets import (
        Header,
        Footer,
        Input,
        ListItem,
        ListView,
        Static,
        Button,
    )
    from textual.worker import get_current_worker

    from rich.text import Text

except ModuleNotFoundError:
    rerun_script(Path(__file__).resolve())
    raise SystemExit


class Download(App):
    """Browse and download GGUF models from Hugging Face."""

    CSS = """
    Screen {
        background: $background;
    }

    #search-container {
        height: auto;
        margin: 1 2 0 2;
    }

    #search-row {
        height: 3;
    }

    #search-input {
        width: 1fr;
    }

    #search-btn {
        width: 12;
        margin-left: 1;
    }

    #main-layout {
        height: 1fr;
        margin: 1 2;
    }

    #list-container {
        width: 62%;
        border: round $panel;
        background: $surface;
    }

    #details-container {
        width: 38%;
        margin-left: 1;
        padding: 1 2;
        border: round $panel;
        background: $surface;
    }

    #model-list {
        height: 1fr;
    }

    ListItem {
        height: 4;
        padding: 1 2;
    }

    ListItem:hover {
        background: $boost;
    }

    ListItem.-highlight {
        background: $boost;
    }

    #details-text {
        height: 1fr;
        overflow-y: auto;
    }

    #download-btn {
        width: 100%;
        margin-top: 1;
    }

    #status-text {
        height: auto;
        margin-top: 1;
        color: $success;
    }

    #empty-text {
        margin: 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "clear_search", "Clear Search"),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.api = HfApi()

        self.models = []
        self.selected_model = None

    # =========================================================
    # UI
    # =========================================================

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="search-container"):
            with Horizontal(id="search-row"):
                yield Input(
                    placeholder="Search models (e.g llama, qwen, gemma)...",
                    id="search-input",
                )

                yield Button(
                    "Search",
                    id="search-btn",
                    variant="primary",
                )

        with Horizontal(id="main-layout"):

            with Vertical(id="list-container"):
                yield ListView(
                    id="model-list",
                )

            with Vertical(id="details-container"):
                yield Static(
                    "Select a model to view its details.",
                    id="details-text",
                )

                yield Button(
                    "Download GGUF",
                    id="download-btn",
                    variant="success",
                )

                yield Static(
                    "",
                    id="status-text",
                )

        yield Footer()

    def on_mount(self) -> None:
        """Focus the search box and load popular GGUF models."""

        self.query_one(
            "#search-input",
            Input,
        ).focus()

        self.search_models("")

    # =========================================================
    # SEARCH INPUT
    # =========================================================

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        """Run a search when Enter is pressed."""

        query = event.value.strip()

        self.search_models(query)

    # =========================================================
    # BUTTONS
    # =========================================================

    def on_button_pressed(
        self,
        event: Button.Pressed,
    ) -> None:

        # -----------------------------------------------------
        # Search
        # -----------------------------------------------------

        if event.button.id == "search-btn":

            search_input = self.query_one(
                "#search-input",
                Input,
            )

            self.search_models(
                search_input.value.strip()
            )

            return

        # -----------------------------------------------------
        # Download
        # -----------------------------------------------------

        if event.button.id == "download-btn":

            if self.selected_model is None:
                self.update_status(
                    "Select a model first."
                )
                return

            self.download_model(
                self.selected_model
            )

    # =========================================================
    # SEARCH
    # =========================================================

    @work(
        thread=True,
        exclusive=True,
        group="search",
        exit_on_error=False,
    )
    def search_models(
        self,
        query: str,
    ) -> None:
        """
        Search Hugging Face in a background thread.

        The @work decorator is important because
        get_current_worker() only works inside a worker.
        """

        worker = get_current_worker()

        self.call_from_thread(
            self.update_status,
            "Searching Hugging Face...",
        )

        try:

            # -------------------------------------------------
            # Search
            # -------------------------------------------------

            if query:
                search_query = f"{query} GGUF"
            else:
                search_query = "GGUF"

            models = list(
                self.api.list_models(
                    search=search_query,
                    sort="downloads",
                    limit=30,
                    expand=[
                        "downloads",
                        "downloadsAllTime",
                        "likes",
                        "gated",
                        "pipeline_tag",
                        "gguf",
                    ],
                )
            )

            if worker.is_cancelled:
                return

            # -------------------------------------------------
            # Keep only models that expose GGUF information.
            #
            # If the Hub does not provide GGUF metadata for a
            # result, we check the repository files directly.
            # -------------------------------------------------

            gguf_models = []

            for model in models:

                if worker.is_cancelled:
                    return

                gguf_info = getattr(
                    model,
                    "gguf",
                    None,
                )

                if gguf_info:
                    gguf_models.append(model)
                    continue

                # Fallback for repositories where GGUF
                # metadata isn't returned by list_models().
                try:

                    files = self.api.list_repo_files(
                        model.id,
                        repo_type="model",
                    )

                    if any(
                        file.lower().endswith(".gguf")
                        for file in files
                    ):
                        gguf_models.append(model)

                except Exception:
                    continue

            if worker.is_cancelled:
                return

            self.call_from_thread(
                self.display_models,
                gguf_models,
            )

        except Exception as e:

            if worker.is_cancelled:
                return

            self.call_from_thread(
                self.show_search_error,
                str(e),
            )

    # =========================================================
    # DISPLAY SEARCH RESULTS
    # =========================================================

    def display_models(
        self,
        models,
    ) -> None:
        """Display model search results."""

        self.models = models
        self.selected_model = None

        list_view = self.query_one(
            "#model-list",
            ListView,
        )

        list_view.clear()

        self.query_one(
            "#details-text",
            Static,
        ).update(
            "Select a model to view its details."
        )

        if not models:

            list_view.append(
                ListItem(
                    Static(
                        "No GGUF models found."
                    )
                )
            )

            self.update_status(
                "No GGUF models found."
            )

            return

        # -----------------------------------------------------
        # Add results
        # -----------------------------------------------------

        for model in models:

            downloads = (
                getattr(model, "downloads", None)
                or 0
            )

            likes = (
                getattr(model, "likes", None)
                or 0
            )

            downloads_all_time = (
                getattr(
                    model,
                    "downloads_all_time",
                    None,
                )
                or 0
            )

            pipeline = getattr(
                model,
                "pipeline_tag",
                None,
            )

            text = Text()

            text.append(
                model.id,
                style="bold",
            )

            text.append(
                "\nGGUF  •  ",
                style="green",
            )

            text.append(
                f"{downloads:,} downloads",
                style="dim",
            )

            text.append(
                f"  •  {likes:,} likes",
                style="dim",
            )

            if pipeline:
                text.append(
                    f"\nTask: {pipeline}",
                    style="dim",
                )

            if downloads_all_time:
                text.append(
                    f"  •  {downloads_all_time:,} total",
                    style="dim",
                )

            list_view.append(
                ListItem(
                    Static(text)
                )
            )

        self.update_status(
            f"Found {len(models)} GGUF repositories."
        )

    def show_search_error(
        self,
        error: str,
    ) -> None:

        self.query_one(
            "#details-text",
            Static,
        ).update(
            f"Search failed:\n\n{error}"
        )

        self.update_status(
            "Search failed."
        )

    # =========================================================
    # MODEL SELECTION
    # =========================================================

    def on_list_view_highlighted(
        self,
        event: ListView.Highlighted,
    ) -> None:
        """Update the details panel."""

        index = event.list_view.index

        if index is None:
            return

        if index < 0 or index >= len(self.models):
            return

        model = self.models[index]

        self.selected_model = model

        downloads = (
            getattr(model, "downloads", None)
            or 0
        )

        downloads_all_time = (
            getattr(
                model,
                "downloads_all_time",
                None,
            )
            or 0
        )

        likes = (
            getattr(model, "likes", None)
            or 0
        )

        gated = getattr(
            model,
            "gated",
            False,
        )

        pipeline = getattr(
            model,
            "pipeline_tag",
            None,
        )

        details = Text()

        details.append(
            "Repository\n",
            style="bold",
        )

        details.append(
            f"{model.id}\n\n"
        )

        details.append(
            "GGUF\n",
            style="bold green",
        )

        details.append(
            "✓ Compatible with llama.cpp\n\n",
            style="green",
        )

        details.append(
            "Downloads\n",
            style="bold",
        )

        details.append(
            f"{downloads:,}\n\n"
        )

        if downloads_all_time:

            details.append(
                "All-time downloads\n",
                style="bold",
            )

            details.append(
                f"{downloads_all_time:,}\n\n"
            )

        details.append(
            "Likes\n",
            style="bold",
        )

        details.append(
            f"{likes:,}\n\n"
        )

        details.append(
            "Task\n",
            style="bold",
        )

        details.append(
            f"{pipeline or 'Unknown'}\n\n"
        )

        details.append(
            "Gated\n",
            style="bold",
        )

        details.append(
            f"{gated}\n\n"
        )

        details.append(
            "Press Download GGUF to inspect the repo "
            "and download its GGUF files."
        )

        self.query_one(
            "#details-text",
            Static,
        ).update(details)

        self.update_status("")

    # =========================================================
    # DOWNLOAD
    # =========================================================

    @work(
        thread=True,
        exclusive=True,
        group="download",
        exit_on_error=False,
    )
    def download_model(
        self,
        model,
    ) -> None:
        """Download only GGUF files from the selected repository."""

        worker = get_current_worker()

        self.call_from_thread(
            self.update_status,
            f"Checking {model.id}...",
        )

        try:

            # -------------------------------------------------
            # Destination
            # -------------------------------------------------

            model_root = (
                Path(APP_FOLDER)
                / "models"
                / model.id.replace("/", "__")
            )

            model_root.mkdir(
                parents=True,
                exist_ok=True,
            )

            # -------------------------------------------------
            # Get repo files
            # -------------------------------------------------

            files = list(
                self.api.list_repo_files(
                    model.id,
                    repo_type="model",
                )
            )

            gguf_files = [
                file
                for file in files
                if file.lower().endswith(".gguf")
            ]

            if not gguf_files:

                self.call_from_thread(
                    self.update_status,
                    "No GGUF files found in this repository.",
                )

                return

            if worker.is_cancelled:
                return

            # -------------------------------------------------
            # Show what we're downloading
            # -------------------------------------------------

            self.call_from_thread(
                self.update_status,
                (
                    f"Found {len(gguf_files)} GGUF file(s).\n"
                    f"Downloading..."
                ),
            )

            # -------------------------------------------------
            # Download
            # -------------------------------------------------

            path = snapshot_download(
                repo_id=model.id,
                repo_type="model",
                local_dir=model_root,
                allow_patterns="*.gguf",
                max_workers=4,
            )

            if worker.is_cancelled:
                return

            # -------------------------------------------------
            # Finished
            # -------------------------------------------------

            self.call_from_thread(
                self.update_status,
                (
                    f"Download complete.\n\n"
                    f"Files: {len(gguf_files)}\n"
                    f"Location:\n{path}"
                ),
            )

        except Exception as e:

            if worker.is_cancelled:
                return

            self.call_from_thread(
                self.update_status,
                f"Download failed:\n{e}",
            )

    # =========================================================
    # STATUS
    # =========================================================

    def update_status(
        self,
        text: str,
    ) -> None:

        self.query_one(
            "#status-text",
            Static,
        ).update(text)

    # =========================================================
    # CLEAR SEARCH
    # =========================================================

    def action_clear_search(self) -> None:

        search_input = self.query_one(
            "#search-input",
            Input,
        )

        search_input.value = ""

        search_input.focus()

        self.search_models("")


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":
    app = Download()
    app.run()