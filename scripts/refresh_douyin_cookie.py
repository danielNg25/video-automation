#!/usr/bin/env python3
"""Refresh Douyin cookies for the download API.

Usage:
    python scripts/refresh_douyin_cookie.py

Steps to manually refresh cookies:
    1. Open https://www.douyin.com in your browser
    2. Log in to your account
    3. Open Developer Tools (F12) → Network tab
    4. Reload the page and find any request to douyin.com
    5. Copy the Cookie header value
    6. Paste it into config/douyin_cookie.txt

This script can be extended to automate cookie extraction
using browser automation (e.g., playwright) if needed.
"""

from pathlib import Path


def main():
    cookie_file = Path("config/douyin_cookie.txt")
    cookie_file.parent.mkdir(parents=True, exist_ok=True)

    if cookie_file.exists():
        cookie = cookie_file.read_text().strip()
        if cookie:
            print(f"Current cookie file: {cookie_file}")
            print(f"Cookie length: {len(cookie)} chars")
            print(f"Preview: {cookie[:50]}...")
            return

    print("No cookie found.")
    print()
    print("To set up cookies:")
    print("1. Open https://www.douyin.com in your browser")
    print("2. Log in to your Douyin account")
    print("3. Open Developer Tools (F12) → Network tab")
    print("4. Reload the page and find a request to douyin.com")
    print("5. Copy the Cookie header value")
    print(f"6. Save it to: {cookie_file.resolve()}")
    print()
    cookie = input("Paste your cookie here (or press Enter to skip): ").strip()
    if cookie:
        cookie_file.write_text(cookie)
        print(f"Cookie saved to {cookie_file}")
    else:
        print("Skipped. You can manually create the cookie file later.")


if __name__ == "__main__":
    main()
