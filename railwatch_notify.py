"""Pluggable outbound notification channels for ticket hits and human-action alerts."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from typing import Callable, Dict, Mapping, Optional

from railwatch_config_contract import merge_notification_settings, redact_sensitive_text


class NotificationService:
  def __init__(
    self,
    settings: Optional[Mapping[str, object]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
  ):
    self.settings = merge_notification_settings(settings)
    self.log = log_callback or (lambda _message: None)

  def update_settings(self, settings: Optional[Mapping[str, object]] = None) -> None:
    self.settings = merge_notification_settings(settings)

  def notify(self, title: str, message: str, urgent: bool = False) -> Dict[str, bool]:
    results = {
      "desktop_urgent": bool(self.settings.get("desktop_urgent")),
      "sound_loop": bool(self.settings.get("sound_loop")) and urgent,
      "server_chan": False,
      "email": False,
      "wecom_webhook": False,
    }
    if self.settings.get("server_chan_enabled") and self.settings.get("server_chan_key"):
      results["server_chan"] = self._send_server_chan(title, message)
    if self.settings.get("email_enabled"):
      results["email"] = self._send_email(title, message)
    if self.settings.get("wecom_webhook_enabled") and self.settings.get("wecom_webhook_url"):
      results["wecom_webhook"] = self._send_wecom(title, message)
    return results

  def _send_server_chan(self, title: str, message: str) -> bool:
    key = str(self.settings.get("server_chan_key", "")).strip()
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
        self.log(f"Server酱通知失败：{body}")
      return bool(ok)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
      self.log(f"Server酱通知异常：{exc}")
      return False

  def _send_wecom(self, title: str, message: str) -> bool:
    url = str(self.settings.get("wecom_webhook_url", "")).strip()
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
        self.log(f"企业微信 webhook 通知失败：{body}")
      return bool(ok)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
      self.log(f"企业微信 webhook 通知异常：{exc}")
      return False

  def _send_email(self, title: str, message: str) -> bool:
    host = str(self.settings.get("email_smtp_host", "")).strip()
    user = str(self.settings.get("email_user", "")).strip()
    password = str(self.settings.get("email_password", "")).strip()
    recipient = str(self.settings.get("email_to", "")).strip()
    port = int(self.settings.get("email_smtp_port") or 465)
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
      self.log(f"邮件通知异常：{exc}")
      return False
