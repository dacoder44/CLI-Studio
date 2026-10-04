from pathlib import Path

DEFUALT_PORT = 25542
RECOMMENDED_MODELS = {
    "google/gemma4:e2b": "Gemma-4-E2B",
    "google/gemma4:e4b": "Gemma-4-E4B",
    "qwen2.5:3b": "Qwen-2.5-3B"
}
file = Path(__file__).resolve()
APP_FOLDER = file.parent.resolve()
MODEL_FOLDER = Path(f"{APP_FOLDER}\\models")