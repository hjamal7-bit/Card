"""Notification system - alerts you when products become available."""

import logging
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import MonitorConfig
from .scrapers import ProductResult

logger = logging.getLogger(__name__)


def notify_desktop(result: ProductResult):
    """Send a desktop notification."""
    title = f"In Stock: {result.name}"
    price_str = f" - ${result.price:.2f}" if result.price else ""
    message = f"{result.name}{price_str}\n{result.retailer}\n{result.url}"
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Product Monitor",
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"Desktop notification failed: {e}")
        try:
            subprocess.run(
                ["notify-send", "--urgency=critical", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.warning("notify-send not available")


def notify_sound():
    """Play an alert sound."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
        elif sys.platform == "linux":
            subprocess.run(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                check=False, capture_output=True,
            )
        elif sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            print("\a", end="", flush=True)
    except Exception as e:
        logger.warning(f"Sound notification failed: {e}")
        print("\a", end="", flush=True)


def notify_email(result: ProductResult, config: MonitorConfig):
    """Send an email notification."""
    notif = config.notifications
    if not all([notif.email_to, notif.smtp_user, notif.smtp_password]):
        logger.warning("Email notification skipped: missing email configuration")
        return

    price_str = f"${result.price:.2f}" if result.price else "N/A"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"IN STOCK: {result.name}"
    msg["From"] = notif.email_from or notif.smtp_user
    msg["To"] = notif.email_to

    text_body = (
        f"{result.name} is now available for purchase!\n\n"
        f"Retailer: {result.retailer}\n"
        f"Price: {price_str}\n"
        f"URL: {result.url}\n\n"
        f"Go buy it now!"
    )
    html_body = f"""
    <html>
    <body>
        <h2 style="color: green;">&#x2705; {result.name} is IN STOCK!</h2>
        <p><strong>Retailer:</strong> {result.retailer}</p>
        <p><strong>Price:</strong> {price_str}</p>
        <p><a href="{result.url}" style="font-size: 18px; font-weight: bold;">
            Click here to buy it now
        </a></p>
    </body>
    </html>
    """

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(notif.smtp_host, notif.smtp_port) as server:
            server.starttls()
            server.login(notif.smtp_user, notif.smtp_password)
            server.sendmail(msg["From"], [notif.email_to], msg.as_string())
        logger.info(f"Email sent to {notif.email_to}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def send_notifications(result: ProductResult, config: MonitorConfig):
    """Dispatch all configured notifications for an available product."""
    notif = config.notifications

    if notif.desktop:
        notify_desktop(result)
    if notif.sound:
        notify_sound()
    if notif.email:
        notify_email(result, config)
