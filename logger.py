from datetime import datetime
from dataclasses import dataclass

@dataclass
class Logger:
    header: str
    def log(self, _input):
        print(f"[{datetime.now()}] [{self.header}] {_input}")