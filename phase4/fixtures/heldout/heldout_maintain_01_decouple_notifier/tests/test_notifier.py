import pytest
from src.notifier import NotificationDispatcher

def test_dispatch_email():
    dispatcher = NotificationDispatcher()
    assert dispatcher.dispatch("email", "dev@example.com", "Build Succeeded") is True
    assert dispatcher.dispatch("email", "invalid-email", "Build Succeeded") is False
    assert len(dispatcher.sent_log) == 1

def test_dispatch_webhook():
    dispatcher = NotificationDispatcher()
    assert dispatcher.dispatch("webhook", "https://hooks.slack.com/services/123", "Alert") is True
    assert dispatcher.dispatch("webhook", "ftp://invalid-url", "Alert") is False

def test_dispatch_sms():
    dispatcher = NotificationDispatcher()
    assert dispatcher.dispatch("sms", "+15551234567", "Urgent page") is True
    assert dispatcher.dispatch("sms", "12345", "Urgent page") is False

def test_dispatch_unknown_channel():
    dispatcher = NotificationDispatcher()
    assert dispatcher.dispatch("carrier_pigeon", "rooftop", "Fly") is False
