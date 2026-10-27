"""Pluggable outbound notification channels for ticket hits and human-action alerts."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from email.mime.text import MIMEText
from typing import Callable, Dict, Mapping, Optional

from railwatch_config_contract import (NOTIFICATION_CHANNELS, NOTIFICATION_FIELDS, NOTIFICATION_REQUIRED_FIELDS,
                                       https_url, merge_notification_settings, ntfy_endpoint, redact_sensitive_text)

CHANNELS = NOTIFICATION_CHANNELS
CHANNEL_CAPACITY = 4  # One active send and at most three waiting, per channel.
# Events that must reach the phone even when it is silenced; the rest are ordinary updates.
URGENT_EVENTS = frozenset({"hit", "verification", "payment"})


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self, *_args, **_kwargs):
    return None  # A push endpoint never redirects; do not carry a key or token elsewhere.


_PUSH_OPENER = urllib.request.build_opener(_RefuseRedirect)


def _post_json(url: str, payload: dict, headers: Optional[Mapping[str, str]] = None) -> dict:
  request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                   headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
  with _PUSH_OPENER.open(request, timeout=8) as response:
    body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
  return body if isinstance(body, dict) else {}


class NotificationService:
  def __init__(
    self,
    settings: Optional[Mapping[str, object]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
  ):
    self.settings = merge_notification_settings(settings)
    self.log = log_callback or (lambda _message: None)
    self._lock = threading.RLock()
    self._executors = {channel: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"notify-{channel}")
                       for channel in CHANNELS}
    self._capacity = {channel: threading.BoundedSemaphore(CHANNEL_CAPACITY) for channel in CHANNELS}
    self._seen: dict[tuple[str, str], float] = {}
    self._pending: set[tuple[str, str]] = set()
    self._status: dict[str, dict] = {}
    self._status_sequence = {channel: 0 for channel in CHANNELS}

  def close(self) -> None:
    for executor in self._executors.values():
      executor.shutdown(wait=True)

  def update_settings(self, settings: Optional[Mapping[str, object]] = None) -> None:
    with self._lock:
      self.settings = merge_notification_settings(settings)

  def status(self) -> Dict[str, dict]:
    with self._lock:
      return {key: dict(value) for key, value in self._status.items()}

  def _channel_state(self, channel: str, settings: dict) -> str:
    enabled = settings.get(f"{channel}_enabled")
    if not enabled:
      return "disabled"
    required = NOTIFICATION_REQUIRED_FIELDS[channel]
    return "ready" if all(settings.get(field) for field in required) else "not_configured"

  def _deliver(self, channel: str, title: str, message: str, settings: dict, sequence=None, urgent=False) -> dict:
    # Looked up on the instance at send time so tests can replace one channel's sender.
    sender = getattr(self, f"_send_{channel}")
    try:
      ok = sender(title, message, settings, urgent)
    except Exception:
      ok = False
      self.log(f"{channel} 通知失败，请检查渠道配置与网络。")
    result = {"status": "success" if ok else "failed", "sent_at": time.time()}
    with self._lock:
      if sequence is None or self._status_sequence[channel] == sequence:
        self._status[channel] = result
    return result

  def _submit(self, channel, title, message, settings, state, event_key=None, urgent=False):
    """Admission and dedup share one lock; rejected sends never claim delivery."""
    key = (channel, event_key) if event_key is not None else None
    with self._lock:
      now = time.monotonic()
      self._seen = {key: at for key, at in self._seen.items() if now - at < 3600}
      if state == "ready" and key is not None and (key in self._pending or key in self._seen):
        return {"status": "duplicate", "sent_at": None}, None
      sequence = self._status_sequence[channel] + 1
      self._status_sequence[channel] = sequence
      future = None
      if state == "ready":
        if not self._capacity[channel].acquire(blocking=False):
          state = "queue_full"
        else:
          if key is not None:
            self._pending.add(key)
          try:
            future = self._executors[channel].submit(self._deliver, channel, title, message, settings, sequence, urgent)
          except RuntimeError:
            self._pending.discard(key)
            self._capacity[channel].release()
            state = "failed"
          else:
            state = "queued"
            def completed(_future):
              with self._lock:
                if key is not None:
                  self._pending.discard(key)
                  # Accepted network sends may have reached the recipient even
                  # on a transport failure; only rejected admission is retried.
                  self._seen[key] = time.monotonic()
                  while len(self._seen) > 1536:
                    self._seen.pop(next(iter(self._seen)))
                self._capacity[channel].release()
            future.add_done_callback(completed)
      result = {"status": state, "sent_at": None}
      if state == "queue_full" and self._status.get(channel, {}).get("status") != "queue_full":
        self.log(f"{channel} 通知队列已满，本次未入队，可在容量恢复后重试。")
      self._status[channel] = result
      return result, future

  def enqueue(self, title: str, message: str, *, event_type: str, event_key: str) -> Dict[str, dict]:
    with self._lock:
      settings = dict(self.settings)
    results = {}
    selected = settings.get("event_channels", {}).get(event_type, [])
    urgent = event_type in URGENT_EVENTS
    for channel in CHANNELS:
      state = "disabled" if channel not in selected else self._channel_state(channel, settings)
      results[channel], _ = self._submit(channel, title, message, settings, state, event_key, urgent)
    return results

  def test_notification(self) -> Dict[str, dict]:
    """Send fixed content on configured channels, independent of event filters.

    Sent as urgent, so a phone channel demonstrates the alert level a hit would use.
    """
    with self._lock:
      settings = dict(self.settings)
    futures = {}
    results = {}
    for channel in CHANNELS:
      state = self._channel_state(channel, settings)
      results[channel], future = self._submit(channel, "RailWatch 测试通知", "这是一条不包含行程或乘客信息的测试通知。", settings, state,
                                              urgent=True)
      if future is not None:
        futures[channel] = future
    # One shared waiting deadline; a slow channel does not add twelve seconds
    # for each later channel. Unfinished sends stay queued in the public state.
    wait(list(futures.values()), timeout=12)
    for channel, future in futures.items():
      if future.done():
        results[channel] = future.result()
    return results

  def notify(self, title: str, message: str, urgent: bool = False) -> Dict[str, bool]:
    results = {
      "desktop_urgent": bool(self.settings.get("desktop_urgent")),
      "sound_loop": bool(self.settings.get("sound_loop")) and urgent,
      **{channel: False for channel in CHANNELS},
    }
    settings = dict(self.settings)
    for channel in CHANNELS:
      if self._channel_state(channel, settings) == "ready":
        results[channel] = self._deliver(channel, title, message, settings, urgent=urgent)["status"] == "success"
    return results

  def _send_server_chan(self, title: str, message: str, settings: dict, urgent: bool = False) -> bool:
    key = str(settings.get("server_chan_key", "")).strip()
    if not key:
      return False
    payload = urllib.parse.urlencode({"text": title, "desp": message}).encode("utf-8")
    url = f"https://sctapi.ftqq.com/{key}.send"
    try:
      request = urllib.request.Request(url, data=payload, method="POST")
      with urllib.request.urlopen(request, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
      ok = body.get("code") in (0, "0")
      if ok:
        self.log("Server酱通知已发送。")
      else:
        self.log("Server酱通知失败，请检查渠道配置。")
      return bool(ok)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
      self.log("Server酱通知异常，请检查网络或渠道配置。")
      return False

  def _send_wecom_webhook(self, title: str, message: str, settings: dict, urgent: bool = False) -> bool:
    url = str(settings.get("wecom_webhook_url", "")).strip()
    if not url:
      return False
    payload = {
      "msgtype": "text",
      "text": {"content": f"{title}\n{message}"},
    }
    try:
      request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
      )
      with urllib.request.urlopen(request, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
      ok = body.get("errcode") == 0
      if ok:
        self.log("企业微信 webhook 通知已发送。")
      else:
        self.log("企业微信 webhook 通知失败，请检查渠道配置。")
      return bool(ok)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
      self.log("企业微信 webhook 通知异常，请检查网络或渠道配置。")
      return False

  def _send_email(self, title: str, message: str, settings: dict, urgent: bool = False) -> bool:
    host = str(settings.get("email_smtp_host", "")).strip()
    user = str(settings.get("email_user", "")).strip()
    password = str(settings.get("email_password", "")).strip()
    recipient = str(settings.get("email_to", "")).strip()
    port = int(settings.get("email_smtp_port") or 465)
    if not host or not user or not password or not recipient:
      return False
    mime = MIMEText(message, "plain", "utf-8")
    mime["Subject"] = title
    mime["From"] = user
    mime["To"] = recipient
    try:
      context = ssl.create_default_context()
      with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [recipient], mime.as_string())
      self.log(f"邮件通知已发送至 {redact_sensitive_text(recipient)}。")
      return True
    except (smtplib.SMTPException, OSError) as exc:
      self.log("邮件通知异常，请检查 SMTP 配置与网络。")
      return False

  def _send_bark(self, title: str, message: str, settings: dict, urgent: bool = False) -> bool:
    key = str(settings.get("bark_key", "")).strip()
    server = https_url(settings.get("bark_server") or NOTIFICATION_FIELDS["bark_server"]["default"])
    if not key or not server:
      return False
    payload = {"device_key": key, "title": title, "body": message, "group": "RailWatch", "level": "active"}
    if urgent:
      # timeSensitive breaks through Focus; critical also rings on silent and needs the user's opt-in.
      payload["level"] = "critical" if settings.get("bark_critical") else "timeSensitive"
      if settings.get("bark_call"):
        payload["call"] = "1"
    try:
      ok = _post_json(f"{server.rstrip('/')}/push", payload).get("code") == 200
      self.log("Bark 通知已发送。" if ok else "Bark 通知失败，请检查渠道配置。")
      return ok
    except (urllib.error.URLError, OSError, ValueError):
      self.log("Bark 通知异常，请检查网络或渠道配置。")
      return False

  def _send_ntfy(self, title: str, message: str, settings: dict, urgent: bool = False) -> bool:
    endpoint = ntfy_endpoint(settings.get("ntfy_topic_url"))
    token = str(settings.get("ntfy_token", "")).strip()
    if endpoint is None:
      self.log("ntfy 主题地址格式无效，请检查渠道配置。")
      return False
    # JSON goes to the server root with the topic in the body.
    root, topic = endpoint
    payload = {"topic": topic, "title": title, "message": message, "priority": 5 if urgent else 3}
    try:
      body = _post_json(f"{root}/", payload, {"Authorization": f"Bearer {token}"} if token else None)
      ok = bool(body.get("id"))
      self.log("ntfy 通知已发送。" if ok else "ntfy 通知失败，请检查渠道配置。")
      return ok
    except (urllib.error.URLError, OSError, ValueError):
      self.log("ntfy 通知异常，请检查网络或渠道配置。")
      return False


# Every channel in the shared table needs exactly one ``_send_<channel>`` sender.
_SENDERS = {name[len("_send_"):] for name in vars(NotificationService) if name.startswith("_send_")}
if _SENDERS != set(CHANNELS):
  raise RuntimeError(f"通知渠道表与发送函数不一致：{sorted(_SENDERS ^ set(CHANNELS))}")
