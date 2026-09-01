# email_notifier.py
# SMTP integration for transactional notification emails.
#
# Sends through Google Workspace, which already owns the SPF record for
# getyoudle.com, so these messages authenticate as the domain instead of
# relying on a third-party ESP.

import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_SENDER_EMAIL = "info@getyoudle.com"
DEFAULT_SENDER_NAME = "Youdle"
DASHBOARD_URL = "https://youdle-agent-dashboard.vercel.app"

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587

# Values that look like a credential but are not one. A placeholder is truthy,
# so it connects fine and only fails at login with an opaque auth error.
PLACEHOLDER_SECRETS = {
    "your-app-password",
    "your_app_password",
    "changeme",
    "todo",
    "none",
    "null",
}


def _clean_secret(raw: Optional[str]) -> Optional[str]:
    """
    Normalize a credential read from the environment.

    A secret pasted with a trailing newline or wrapping quotes is still truthy,
    so it authenticates as garbage. Google app passwords are also displayed in
    four space-separated groups, and the spaces must be removed before use.
    """
    if not raw:
        return None
    cleaned = raw.strip().strip('"').strip("'").strip()
    return cleaned or None


def _describe_send_error(error: Exception) -> str:
    """
    Build an actionable message from an SMTP failure.

    smtplib exceptions stringify to a bare tuple of code and server bytes, so
    add the interpretation rather than leaving the caller to decode it.
    """
    parts = [f"{type(error).__name__}: {error}"]

    if isinstance(error, smtplib.SMTPAuthenticationError):
        parts.append(
            "Google rejected the login. SMTP_PASSWORD must be a 16-character "
            "app password (not the account password), and the account needs "
            "2-Step Verification enabled to create one."
        )
    elif isinstance(error, smtplib.SMTPSenderRefused):
        parts.append(
            "Google refused the From address. SENDER_EMAIL must be the "
            "SMTP_USERNAME account or an alias it is allowed to send as."
        )
    elif isinstance(error, smtplib.SMTPRecipientsRefused):
        parts.append("Every recipient was rejected. Check ADMIN_NOTIFICATION_EMAIL.")
    elif isinstance(error, (smtplib.SMTPConnectError, OSError)):
        parts.append(
            f"Could not reach the SMTP server. Check SMTP_HOST/SMTP_PORT and "
            f"that outbound port {DEFAULT_SMTP_PORT} is not blocked."
        )

    return " | ".join(parts)


# ============================================================================
# EMAIL TEMPLATES
# ============================================================================

BASE_EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f5f5f5; }}
    .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
    .header {{ background-color: #1a1a2e; padding: 30px; text-align: center; }}
    .header img {{ max-width: 120px; }}
    .header h1 {{ color: #ffffff; margin: 15px 0 0 0; font-size: 24px; }}
    .content {{ padding: 30px; }}
    .status-box {{ background-color: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }}
    .status-item {{ display: flex; justify-content: space-between; margin: 10px 0; }}
    .status-label {{ color: #666; }}
    .status-value {{ font-weight: bold; color: #333; }}
    .status-good {{ color: #28a745; }}
    .status-warning {{ color: #ffc107; }}
    .status-danger {{ color: #dc3545; }}
    .cta-button {{ display: inline-block; background-color: #f93822; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 5px; font-weight: bold; margin: 20px 0; }}
    .cta-button:hover {{ background-color: #e02d1a; }}
    .footer {{ background-color: #333; color: #fff; padding: 20px; text-align: center; font-size: 12px; }}
    .footer a {{ color: #fff; }}
    .urgency-high {{ border-left: 4px solid #dc3545; padding-left: 15px; }}
    .urgency-medium {{ border-left: 4px solid #ffc107; padding-left: 15px; }}
    .urgency-low {{ border-left: 4px solid #28a745; padding-left: 15px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Youdle</h1>
    </div>
    <div class="content">
      {content}
    </div>
    <div class="footer">
      <p>&copy; {year} Youdle. All rights reserved.</p>
      <p><a href="mailto:info@getyoudle.com">info@getyoudle.com</a></p>
    </div>
  </div>
</body>
</html>"""


class EmailNotifier:
    """
    SMTP integration for sending transactional notification emails.
    """

    def __init__(
        self,
        smtp_password: Optional[str] = None,
        admin_emails: Optional[str] = None,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        dry_run: bool = False
    ):
        """
        Initialize the SMTP notifier.

        Args:
            smtp_password: Google app password (defaults to SMTP_PASSWORD env var)
            admin_emails: Admin email(s) to receive notifications, comma-separated for multiple
                         (defaults to ADMIN_NOTIFICATION_EMAIL env var)
            sender_email: Sender email address (defaults to SMTP_USERNAME, then DEFAULT_SENDER_EMAIL)
            sender_name: Sender display name (defaults to DEFAULT_SENDER_NAME)
            smtp_host: SMTP server (defaults to SMTP_HOST env var, then smtp.gmail.com)
            smtp_port: SMTP port (defaults to SMTP_PORT env var, then 587)
            smtp_username: Account to authenticate as (defaults to SMTP_USERNAME env var)
            dry_run: Print the message instead of sending it. Works without
                     credentials, so it can be used to preview content.
        """
        self.dry_run = dry_run
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST)
        self.smtp_port = int(smtp_port or os.getenv("SMTP_PORT", DEFAULT_SMTP_PORT))
        self.smtp_username = _clean_secret(smtp_username or os.getenv("SMTP_USERNAME"))
        # Google displays app passwords in four space-separated groups; the
        # spaces are presentation only and must not be sent.
        password = _clean_secret(smtp_password or os.getenv("SMTP_PASSWORD"))
        self.smtp_password = password.replace(" ", "") if password else None

        self.sender_email = (
            sender_email
            or os.getenv("SENDER_EMAIL")
            or self.smtp_username
            or DEFAULT_SENDER_EMAIL
        )
        self.sender_name = sender_name or DEFAULT_SENDER_NAME

        # Parse admin emails (comma-separated)
        admin_emails_str = admin_emails or os.getenv("ADMIN_NOTIFICATION_EMAIL", "")
        self.admin_emails = [
            email.strip() for email in admin_emails_str.split(",") if email.strip()
        ]

        if self.smtp_password and self.smtp_password.lower() in PLACEHOLDER_SECRETS:
            print(
                "Warning: SMTP_PASSWORD is a placeholder, not a real app password. "
                "Set the real value or sending will fail to authenticate."
            )
            self.smtp_password = None

    @property
    def is_configured(self) -> bool:
        """True when there are enough credentials to attempt a send."""
        return bool(self.smtp_username and self.smtp_password)

    def _build_html(self, subject: str, content: str) -> str:
        """Build full HTML email from content."""
        return BASE_EMAIL_TEMPLATE.format(
            subject=subject,
            content=content,
            year=datetime.now().year
        )

    def send_notification(
        self,
        subject: str,
        html_content: str,
        to_emails: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Send a notification email to one or more recipients.

        Args:
            subject: Email subject line
            html_content: HTML content for the email body
            to_emails: List of recipient emails (uses admin_emails if not provided)

        Returns:
            Result dictionary with success status
        """
        recipients = to_emails or self.admin_emails

        # Ensure recipients is a list
        if isinstance(recipients, str):
            recipients = [recipients]

        # Checked before the credential guard so content can be previewed
        # without a configured mailbox.
        if self.dry_run:
            print("=" * 78)
            print("DRY RUN - nothing sent")
            print("=" * 78)
            print(f"From    : {self.sender_name} <{self.sender_email}>")
            print(f"To      : {', '.join(recipients) if recipients else '(none)'}")
            print(f"Subject : {subject}")
            print("-" * 78)
            print(html_content)
            print("=" * 78)
            return {
                "success": True,
                "dry_run": True,
                "to_emails": recipients,
                "subject": subject
            }

        if not self.is_configured:
            missing = [
                name for name, value in (
                    ("SMTP_USERNAME", self.smtp_username),
                    ("SMTP_PASSWORD", self.smtp_password),
                ) if not value
            ]
            return {
                "success": False,
                "error": f"SMTP not configured. Missing: {', '.join(missing)}."
            }

        if not recipients:
            return {
                "success": False,
                "error": "No recipient email provided. Set ADMIN_NOTIFICATION_EMAIL."
            }

        try:
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = formataddr((self.sender_name, self.sender_email))
            message["To"] = ", ".join(recipients)

            # Plain-text part first, then the HTML alternative clients prefer.
            message.set_content(
                "This notification is formatted as HTML. "
                f"View it in an HTML-capable client, or open {DASHBOARD_URL}."
            )
            message.add_alternative(html_content, subtype="html")

            context = ssl.create_default_context()
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port,
                                          timeout=30, context=context)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)

            with server:
                if self.smtp_port != 465:
                    server.starttls(context=context)
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(message)

            return {
                "success": True,
                "status_code": 250,
                "to_emails": recipients,
                "subject": subject
            }

        except Exception as e:
            return {
                "success": False,
                "error": _describe_send_error(e)
            }

    def send_blogs_generated_notification(
        self,
        posts_generated: int,
        shoppers_count: int = 0,
        recall_count: int = 0
    ) -> Dict[str, Any]:
        """
        Send notification that blogs have been generated.

        Args:
            posts_generated: Total number of posts generated
            shoppers_count: Number of SHOPPERS posts
            recall_count: Number of RECALL posts
        """
        subject = "Youdle: This Week's Blogs Have Been Generated"

        content = f"""
        <h2>Blog Posts Generated Successfully</h2>
        <p>This week's blog posts have been generated and are ready for your review.</p>

        <div class="status-box">
            <div class="status-item">
                <span class="status-label">Total Posts Generated:</span>
                <span class="status-value">{posts_generated}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Shoppers Articles:</span>
                <span class="status-value">{shoppers_count}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Recall Articles:</span>
                <span class="status-value">{recall_count}</span>
            </div>
        </div>

        <p><strong>Action Required:</strong> Please review and publish these blog posts before Thursday. The newsletter is built from published posts, and still needs your approval on the dashboard before it goes out.</p>

        <p style="text-align: center;">
            <a href="{DASHBOARD_URL}/posts" class="cta-button">Review Blog Posts</a>
        </p>

        <p><strong>Publishing Requirements:</strong></p>
        <ul>
            <li>At least 6 Shoppers articles must be published</li>
            <li>At least 1 Recall article must be published</li>
            <li>Total: 7 posts minimum</li>
        </ul>
        """

        html = self._build_html(subject, content)
        return self.send_notification(subject, html)

    def send_reminder_notification(
        self,
        reminder_type: str,
        published_count: int,
        required_count: int,
        shoppers_published: int = 0,
        recall_published: int = 0
    ) -> Dict[str, Any]:
        """
        Send a reminder notification with current publish status.

        Args:
            reminder_type: Type of reminder (tuesday_evening, wednesday_morning, wednesday_evening)
            published_count: Number of posts currently published
            required_count: Number of posts required (7)
            shoppers_published: Number of SHOPPERS posts published
            recall_published: Number of RECALL posts published
        """
        remaining = max(0, required_count - published_count)
        shoppers_needed = max(0, 6 - shoppers_published)
        recall_needed = max(0, 1 - recall_published)

        # Determine urgency based on reminder type. The deadline describes when
        # posts must be published by, not when the newsletter sends -- sending
        # is a manual approval step on the dashboard.
        urgency_map = {
            "tuesday_evening": ("medium", "by Wednesday"),
            "wednesday_morning": ("medium", "by tomorrow morning"),
            "wednesday_evening": ("high", "by tomorrow morning")
        }
        urgency, deadline = urgency_map.get(reminder_type, ("medium", "soon"))

        # Subject line based on urgency
        if urgency == "high":
            subject = "URGENT: Blog Posts Need Publishing Before Newsletter"
        else:
            subject = "Reminder: Please Review and Publish This Week's Blogs"

        # Status color
        if published_count >= required_count:
            status_class = "status-good"
            status_text = "On Track"
        elif published_count >= required_count - 2:
            status_class = "status-warning"
            status_text = "Almost There"
        else:
            status_class = "status-danger"
            status_text = "Action Needed"

        content = f"""
        <div class="urgency-{urgency}">
            <h2>Blog Publishing Reminder</h2>
            <p>This week's newsletter is put together from published posts, so everything needs to be published <strong>{deadline}</strong>. Once the draft is ready you'll get a separate email to review and approve it.</p>
        </div>

        <div class="status-box">
            <h3>Current Status: <span class="{status_class}">{status_text}</span></h3>
            <div class="status-item">
                <span class="status-label">Posts Published:</span>
                <span class="status-value {status_class}">{published_count} / {required_count}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Shoppers Published:</span>
                <span class="status-value">{shoppers_published} / 6 required</span>
            </div>
            <div class="status-item">
                <span class="status-label">Recall Published:</span>
                <span class="status-value">{recall_published} / 1 required</span>
            </div>
        </div>

        {"<p><strong>Still needed:</strong></p><ul>" +
         (f"<li>{shoppers_needed} more Shoppers article(s)</li>" if shoppers_needed > 0 else "") +
         (f"<li>{recall_needed} more Recall article(s)</li>" if recall_needed > 0 else "") +
         "</ul>" if remaining > 0 else "<p style='color: #28a745;'><strong>All requirements met! You're all set for the newsletter.</strong></p>"}

        <p style="text-align: center;">
            <a href="{DASHBOARD_URL}/posts" class="cta-button">Review & Publish Posts</a>
        </p>
        """

        html = self._build_html(subject, content)
        return self.send_notification(subject, html)

    def send_final_warning_notification(
        self,
        published_count: int,
        required_count: int,
        shoppers_published: int = 0,
        recall_published: int = 0
    ) -> Dict[str, Any]:
        """
        Send final warning before newsletter is sent.

        Args:
            published_count: Number of posts currently published
            required_count: Number of posts required
            shoppers_published: Number of SHOPPERS posts published
            recall_published: Number of RECALL posts published
        """
        subject = "FINAL NOTICE: Publish Blog Posts Before Tomorrow's Newsletter"

        meets_requirement = (shoppers_published >= 6 and recall_published >= 1)

        if meets_requirement:
            status_message = """
            <p style="color: #28a745; font-weight: bold;">
                All publishing requirements are met. A draft newsletter can be created tomorrow morning — you'll get an email to review and approve it before anything sends.
            </p>
            """
        else:
            shoppers_needed = max(0, 6 - shoppers_published)
            recall_needed = max(0, 1 - recall_published)
            status_message = f"""
            <p style="color: #dc3545; font-weight: bold;">
                WARNING: Publishing requirements are NOT met. The newsletter will be CANCELLED if not resolved.
            </p>
            <p><strong>Still needed:</strong></p>
            <ul>
                {"<li>" + str(shoppers_needed) + " more Shoppers article(s)</li>" if shoppers_needed > 0 else ""}
                {"<li>" + str(recall_needed) + " more Recall article(s)</li>" if recall_needed > 0 else ""}
            </ul>
            """

        content = f"""
        <div class="urgency-high">
            <h2>Final Newsletter Notice</h2>
            <p>This week's newsletter is assembled <strong>tomorrow morning</strong>, and only includes posts that are published by then.</p>
        </div>

        <div class="status-box">
            <div class="status-item">
                <span class="status-label">Posts Published:</span>
                <span class="status-value">{published_count} / {required_count}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Shoppers Published:</span>
                <span class="status-value">{shoppers_published} / 6 required</span>
            </div>
            <div class="status-item">
                <span class="status-label">Recall Published:</span>
                <span class="status-value">{recall_published} / 1 required</span>
            </div>
        </div>

        {status_message}

        <p>Please review and make sure all your blog posts are published before the deadline.</p>

        <p style="text-align: center;">
            <a href="{DASHBOARD_URL}/posts" class="cta-button">Review Posts Now</a>
        </p>
        """

        html = self._build_html(subject, content)
        return self.send_notification(subject, html)

    def send_requirements_met_notification(
        self,
        published_count: int,
        required_count: int,
        shoppers_published: int = 0,
        recall_published: int = 0
    ) -> Dict[str, Any]:
        """
        Send notification that requirements are met and newsletter will be created.

        Args:
            published_count: Number of posts currently published
            required_count: Number of posts required (7)
            shoppers_published: Number of SHOPPERS posts published
            recall_published: Number of RECALL posts published
        """
        subject = "Newsletter Ready: All Requirements Met"

        content = f"""
        <div class="urgency-low">
            <h2>Newsletter Requirements Met</h2>
            <p>All publishing requirements have been met, so a <strong>draft</strong> newsletter is being created now. It will not send until you approve it on the dashboard.</p>
        </div>

        <div class="status-box">
            <h3 style="color: #28a745;">Publishing Status</h3>
            <div class="status-item">
                <span class="status-label">Posts Published:</span>
                <span class="status-value status-good">{published_count} / {required_count}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Shoppers Published:</span>
                <span class="status-value status-good">{shoppers_published} / 6 required</span>
            </div>
            <div class="status-item">
                <span class="status-label">Recall Published:</span>
                <span class="status-value status-good">{recall_published} / 1 required</span>
            </div>
        </div>

        <p style="color: #28a745; font-weight: bold;">
            You'll get a follow-up email once the draft is ready to review.
        </p>

        <p>In the meantime you can review the posts that will be included:</p>

        <p style="text-align: center;">
            <a href="{DASHBOARD_URL}/posts?status=published" class="cta-button">View Published Posts</a>
        </p>
        """

        html = self._build_html(subject, content)
        return self.send_notification(subject, html)

    def send_newsletter_cancelled_notification(
        self,
        published_count: int,
        required_count: int,
        shoppers_published: int = 0,
        recall_published: int = 0
    ) -> Dict[str, Any]:
        """
        Send notification that newsletter was cancelled due to insufficient published posts.

        Args:
            published_count: Number of posts that were published
            required_count: Number of posts that were required
            shoppers_published: Number of SHOPPERS posts published
            recall_published: Number of RECALL posts published
        """
        subject = "Newsletter Cancelled: Blogs Were Not Published"

        shoppers_needed = max(0, 6 - shoppers_published)
        recall_needed = max(0, 1 - recall_published)

        content = f"""
        <div class="urgency-high">
            <h2>Newsletter Run Cancelled</h2>
            <p>This week's newsletter run was <strong>cancelled</strong> because the required blog posts were not published in time. No draft was created.</p>
        </div>

        <div class="status-box">
            <h3 style="color: #dc3545;">Publishing Status at Deadline</h3>
            <div class="status-item">
                <span class="status-label">Posts Published:</span>
                <span class="status-value status-danger">{published_count} / {required_count} required</span>
            </div>
            <div class="status-item">
                <span class="status-label">Shoppers Published:</span>
                <span class="status-value">{shoppers_published} / 6 required</span>
            </div>
            <div class="status-item">
                <span class="status-label">Recall Published:</span>
                <span class="status-value">{recall_published} / 1 required</span>
            </div>
        </div>

        <p><strong>What was missing:</strong></p>
        <ul>
            {"<li>" + str(shoppers_needed) + " Shoppers article(s)</li>" if shoppers_needed > 0 else ""}
            {"<li>" + str(recall_needed) + " Recall article(s)</li>" if recall_needed > 0 else ""}
        </ul>

        <h3>Next Steps</h3>
        <ol>
            <li>Go to the dashboard and publish the remaining blog posts</li>
            <li>Create a new newsletter manually from the published posts</li>
            <li>Review and send the newsletter from the dashboard</li>
        </ol>

        <p style="text-align: center;">
            <a href="{DASHBOARD_URL}/posts" class="cta-button">Publish Blog Posts</a>
        </p>

        <p style="text-align: center; margin-top: 10px;">
            <a href="{DASHBOARD_URL}/newsletters" class="cta-button" style="background-color: #333;">Create Newsletter Manually</a>
        </p>
        """

        html = self._build_html(subject, content)
        return self.send_notification(subject, html)

    def send_newsletter_draft_ready_notification(
        self,
        newsletter_id: str,
        subject: str,
        post_count: int,
        shoppers_count: int = 0,
        recall_count: int = 0,
        post_titles: list = None
    ) -> dict:
        """
        Send notification that a draft newsletter is ready for subject line review.
        The team should review the auto-generated subject, edit if needed, then schedule/send.
        """
        email_subject = f"📬 Newsletter draft ready — review subject line before sending"

        titles_html = ""
        if post_titles:
            titles_html = "<ul style='margin: 10px 0; padding-left: 20px;'>"
            for t in post_titles:
                titles_html += f"<li style='margin: 4px 0; color: #555;'>{t}</li>"
            titles_html += "</ul>"

        content = f"""
        <h2 style="color: #222;">📬 Newsletter Draft Ready for Review</h2>

        <p>A draft newsletter has been created with <strong>{post_count} articles</strong>
        ({shoppers_count} shoppers, {recall_count} recall).</p>

        <div style="background: #f8f5f0; border-radius: 8px; padding: 16px; margin: 20px 0; border-left: 4px solid #e8a23a;">
            <p style="margin: 0 0 4px; font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px;">Auto-generated subject line</p>
            <p style="margin: 0; font-size: 18px; font-weight: bold; color: #222;">{subject}</p>
        </div>

        <p><strong>What to do:</strong></p>
        <ol>
            <li>Go to the Newsletters dashboard</li>
            <li>Review the subject line — edit it if you want</li>
            <li>Preview the newsletter content</li>
            <li>Click <strong>Schedule</strong> (Thursday 9 AM CST) or <strong>Send Now</strong></li>
        </ol>

        {f'<p><strong>Articles included:</strong></p>{titles_html}' if titles_html else ''}

        <p style="text-align: center; margin-top: 24px;">
            <a href="{DASHBOARD_URL}/newsletters" class="cta-button">Review & Send Newsletter</a>
        </p>

        <p style="color: #999; font-size: 12px; margin-top: 20px; text-align: center;">
            The newsletter will <strong>not</strong> send automatically. You must approve it on the dashboard.
        </p>
        """

        html = self._build_html(email_subject, content)
        return self.send_notification(email_subject, html)


# For testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send notification emails via SMTP")
    parser.add_argument("--type", "-t", required=True,
                        choices=["generated", "reminder", "warning", "cancelled", "requirements_met"],
                        help="Type of notification to send")
    parser.add_argument("--reminder-type", "-r",
                        choices=["tuesday_evening", "wednesday_morning", "wednesday_evening"],
                        help="Type of reminder (for reminder notifications)")
    parser.add_argument("--published", "-p", type=int, default=0,
                        help="Number of published posts")
    parser.add_argument("--shoppers", "-s", type=int, default=0,
                        help="Number of published shoppers posts")
    parser.add_argument("--recall", type=int, default=0,
                        help="Number of published recall posts")
    parser.add_argument("--dry-run", "--test", action="store_true", dest="dry_run",
                        help="Print the email instead of sending it")

    args = parser.parse_args()

    notifier = EmailNotifier(dry_run=args.dry_run)

    if args.type == "generated":
        result = notifier.send_blogs_generated_notification(
            posts_generated=args.published or 7,
            shoppers_count=args.shoppers or 6,
            recall_count=args.recall or 1
        )
    elif args.type == "reminder":
        result = notifier.send_reminder_notification(
            reminder_type=args.reminder_type or "tuesday_evening",
            published_count=args.published,
            required_count=7,
            shoppers_published=args.shoppers,
            recall_published=args.recall
        )
    elif args.type == "warning":
        result = notifier.send_final_warning_notification(
            published_count=args.published,
            required_count=7,
            shoppers_published=args.shoppers,
            recall_published=args.recall
        )
    elif args.type == "cancelled":
        result = notifier.send_newsletter_cancelled_notification(
            published_count=args.published,
            required_count=7,
            shoppers_published=args.shoppers,
            recall_published=args.recall
        )
    elif args.type == "requirements_met":
        result = notifier.send_requirements_met_notification(
            published_count=args.published,
            required_count=7,
            shoppers_published=args.shoppers,
            recall_published=args.recall
        )

    print(f"Result: {result}")
