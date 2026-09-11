""" One-off helper: opens a real (headed) browser, lets you log in manually,
then saves the resulting session (cookies + localStorage) to a storage_state
JSON file the crawler's "storage_state" auth method can load directly.

Usage:
    python export_session.py <login_url> <output_path>

Example:
    python export_session.py https://app.example.com/login auth/app.example.com.json

Then in auth.json:
    {
      "app.example.com": {
        "method": "storage_state",
        "storage_state": "auth/app.example.com.json"
      }
    }

Sessions expire - if the crawler starts hitting login walls again after a
while, just re-run this to refresh the file.
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright


async def main(login_url, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(login_url)

        print("A browser window has opened. Log in there as you normally would.")
        input("Once you're fully logged in, come back here and press Enter... ")

        await context.storage_state(path=output_path)
        print(f"Saved session to {output_path}")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python export_session.py <login_url> <output_path>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
