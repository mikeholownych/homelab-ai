"""Notification dispatcher with decoupled handler dispatch."""
from typing import Dict, List, Any

class BaseHandler:
    def send(self, recipient: str, message: str) -> bool:
        raise NotImplementedError

class EmailHandler(BaseHandler):
    def send(self, recipient: str, message: str) -> bool:
        return "@" in recipient and len(message) > 0

class WebhookHandler(BaseHandler):
    def send(self, recipient: str, message: str) -> bool:
        return recipient.startswith("http://") or recipient.startswith("https://")

class SMSHandler(BaseHandler):
    def send(self, recipient: str, message: str) -> bool:
        return recipient.startswith("+") and len(recipient) >= 10

class NotificationDispatcher:
    def __init__(self) -> None:
        self.handlers: Dict[str, BaseHandler] = {
            "email": EmailHandler(),
            "webhook": WebhookHandler(),
            "sms": SMSHandler(),
        }
        self.sent_log: List[Dict[str, Any]] = []

    def dispatch(self, channel: str, recipient: str, message: str) -> bool:
        handler = self.handlers.get(channel)
        if not handler:
            return False
        success = handler.send(recipient, message)
        if success:
            self.sent_log.append({"channel": channel, "recipient": recipient, "message": message})
        return success
