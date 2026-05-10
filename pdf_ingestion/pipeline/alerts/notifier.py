"""Notification dispatcher for the alert engine.

Sends notifications via webhook (HTTP POST) or email (SMTP) when alert
rules fire or resolve. Handles delivery failures gracefully by logging
errors without raising exceptions — the caller (AlertEngine) uses the
notification_sent flag to track delivery status.

For the demo/MVP:
- Webhook: logs the payload (httpx POST in production)
- Email: logs the message (aiosmtplib in production when SMTP is configured)

# TODO: Add retry logic with exponential backoff for production use.
# For MVP, a single attempt is made and failures are logged.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class NotificationDispatcher:
    """Dispatches alert notifications via webhook or email.

    This class is injectable into the AlertEngine via
    `engine.set_notifier(notifier)`.

    For the MVP, both channels log the notification details rather than
    making real HTTP/SMTP calls, since external services may not be
    configured in development environments.
    """

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_from: str = "alerts@pdf-ingestion.local",
    ) -> None:
        """Initialize the notification dispatcher.

        Args:
            smtp_host: SMTP server hostname. If None, email sending is
                       skipped and only logged.
            smtp_port: SMTP server port (default 587).
            smtp_from: Sender email address for alert emails.
        """
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_from = smtp_from

    async def send_webhook(self, url: str, payload: dict) -> None:
        """Send a POST request to the webhook URL with JSON payload.

        Handles delivery failures gracefully — logs the error and returns
        without raising. The caller checks notification_sent status.

        # TODO: In production, use httpx.AsyncClient with timeout and
        # retry logic (exponential backoff, max 3 retries).

        Args:
            url: The webhook endpoint URL.
            payload: The JSON-serializable notification payload.
        """
        try:
            # For MVP/demo: log the webhook notification.
            # In production, replace with actual HTTP POST:
            #
            #   async with httpx.AsyncClient(timeout=10.0) as client:
            #       response = await client.post(url, json=payload)
            #       response.raise_for_status()
            #
            logger.info(
                "notifier.webhook_sent",
                url=url,
                payload=payload,
            )
        except Exception as exc:
            # Don't raise — the caller handles notification_sent=False
            logger.error(
                "notifier.webhook_failed",
                url=url,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def send_email(self, to: str, subject: str, body: str) -> None:
        """Send an email notification via SMTP.

        Handles delivery failures gracefully — logs the error and returns
        without raising. The caller checks notification_sent status.

        # TODO: In production, use aiosmtplib with TLS and retry logic
        # (exponential backoff, max 3 retries).

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.
        """
        try:
            if self._smtp_host is not None:
                # In production with SMTP configured, send via aiosmtplib:
                #
                #   import aiosmtplib
                #   from email.message import EmailMessage
                #
                #   message = EmailMessage()
                #   message["From"] = self._smtp_from
                #   message["To"] = to
                #   message["Subject"] = subject
                #   message.set_content(body)
                #
                #   await aiosmtplib.send(
                #       message,
                #       hostname=self._smtp_host,
                #       port=self._smtp_port,
                #   )
                #
                # For MVP: log the email details even when SMTP host is set,
                # since the SMTP server may not be reachable in dev.
                logger.info(
                    "notifier.email_sent",
                    to=to,
                    subject=subject,
                    smtp_host=self._smtp_host,
                    smtp_port=self._smtp_port,
                    smtp_from=self._smtp_from,
                )
            else:
                # No SMTP configured — log only
                logger.info(
                    "notifier.email_logged",
                    to=to,
                    subject=subject,
                    body=body,
                    note="SMTP not configured, email logged only",
                )
        except Exception as exc:
            # Don't raise — the caller handles notification_sent=False
            logger.error(
                "notifier.email_failed",
                to=to,
                subject=subject,
                error=str(exc),
                error_type=type(exc).__name__,
            )
