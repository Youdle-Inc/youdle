#!/usr/bin/env python3
"""
Helper script for GitHub Actions to send notification emails.
Usage: python send_notifications.py <type> <published_count> <shoppers_published> <recall_published>
"""

import sys
from email_notifier import EmailNotifier

def main():
    if len(sys.argv) != 5:
        print("Usage: python send_notifications.py <met|cancelled> <published_count> <shoppers_published> <recall_published>")
        sys.exit(1)
    
    notification_type = sys.argv[1]
    published_count = int(sys.argv[2])
    shoppers_published = int(sys.argv[3])
    recall_published = int(sys.argv[4])
    
    notifier = EmailNotifier()
    
    if notification_type == "met":
        result = notifier.send_requirements_met_notification(
            published_count=published_count,
            required_count=7,
            shoppers_published=shoppers_published,
            recall_published=recall_published
        )
        print(f'Requirements met notification result: {result}')
    elif notification_type == "cancelled":
        result = notifier.send_newsletter_cancelled_notification(
            published_count=published_count,
            required_count=7,
            shoppers_published=shoppers_published,
            recall_published=recall_published
        )
        print(f'Cancellation notification result: {result}')
    else:
        print(f"Unknown notification type: {notification_type}")
        sys.exit(1)

    # Fail the workflow step on a send failure. SMTP gives us no delivery
    # dashboard, so a silent exit 0 here would hide a broken app password
    # until someone noticed the missing email days later.
    if not result.get("success"):
        print(f"Notification send failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

if __name__ == "__main__":
    main()