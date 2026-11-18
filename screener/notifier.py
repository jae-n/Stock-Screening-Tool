"""ntfy notification sender. No message is sent unless explicitly called."""
import requests
from screener.config import Config
from screener.singleton import SingletonMeta
class Notifier(metaclass=SingletonMeta):
    def __init__(self): self._cfg = Config()
    def send(self, title, body, priority=3, tags=None):
        topic = self._cfg.require_ntfy()
        headers = {"Title": title, "Priority": str(priority)}
        if tags: headers["Tags"] = tags
        if self._cfg.ntfy_token: headers["Authorization"] = f"Bearer {self._cfg.ntfy_token}"
        response = requests.post(f"{self._cfg.ntfy_server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
        response.raise_for_status()
        return response
