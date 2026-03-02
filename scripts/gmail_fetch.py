#!/usr/bin/env python3
"""Standalone Gmail fetch for briefing.sh.

Outputs structured email data to stdout for injection into Claude prompt.
Exit code 0 even if Gmail is not configured (outputs empty string).
"""

import os
import sys

# Add project root to path
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

from d_brain.services.gmail import GmailClient


def main() -> None:
    credentials_path = os.environ.get("GMAIL_CREDENTIALS_PATH", os.path.join(PROJECT_DIR, "gcp-oauth.keys.json"))
    token_path = os.environ.get("GMAIL_TOKEN_PATH", os.path.join(PROJECT_DIR, "gmail-token.json"))

    client = GmailClient(credentials_path, token_path)

    if not client.enabled:
        # Gmail not configured — silent exit, briefing works without it
        return

    try:
        emails = client.fetch_emails(hours=24, unread_only=True, max_results=15)
        if emails:
            print(client.format_for_claude(emails))
    except Exception as e:
        # Print to stderr so briefing.sh can still work
        print(f"Gmail fetch error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
