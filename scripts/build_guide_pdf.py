"""Print docs/guide/user_guide.html to docs/user_guide.pdf (A4) with Chromium."""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs" / "guide" / "user_guide.html"
PDF = ROOT / "docs" / "user_guide.pdf"


def count_pages(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf_bytes))


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.emulate_media(media="print", color_scheme="light")
        page.goto(HTML.as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_function(
            "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"
        )
        page.pdf(path=str(PDF), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    pages = count_pages(PDF.read_bytes())
    print(f"{PDF.name}: {pages} pages, {PDF.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
