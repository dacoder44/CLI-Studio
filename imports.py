from pathlib import Path
from logger import Logger
from setup.main_setup import rerun_script
from sockets.socket_handler import RequestServer
import os

os.environ["PYTHONUTF8"] = "1"

logger = Logger("Imports")

logger.log("Importing packages.")

try:
    import platform
    import psutil
    import socket
    import threading
    from llama_cpp import Llama
except ModuleNotFoundError as e:
    logger.log(f"Installing missing dependency: ↓↓\n {e.name}")
    os.environ.pop("PYTHONUTF8")
    rerun_script(
        Path(__file__).resolve() # reruns script and sets up the user in setup.py
    )