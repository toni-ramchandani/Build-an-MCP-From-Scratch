"""Browser automation utilities using Playwright.

This module provides helper functions for managing browser pages and interactions
using Playwright's async API.
"""

import base64
from typing import Dict
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# Global state for browser management
_playwright_instance = None
_browser: Browser | None = None
_context: BrowserContext | None = None
_pages: Dict[str, Page] = {}
_page_counter = 0


async def _ensure_browser() -> Browser:
    """Ensure a browser instance is running and return it."""
    global _playwright_instance, _browser, _context

    if _browser is None:
        _playwright_instance = await async_playwright().start()
        _browser = await _playwright_instance.chromium.launch(headless=True)
        _context = await _browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

    return _browser


async def new_page() -> str:
    """Create a new browser page and return its unique ID."""
    global _page_counter, _pages

    await _ensure_browser()
    assert _context is not None

    page = await _context.new_page()
    _page_counter += 1
    page_id = f"page_{_page_counter}"
    _pages[page_id] = page

    return page_id


async def get_page(page_id: str) -> Page:
    """Get a page by its ID. Raises KeyError if not found."""
    if page_id not in _pages:
        raise KeyError(f"Page '{page_id}' not found")
    return _pages[page_id]


async def close_page(page_id: str) -> None:
    """Close a page by its ID."""
    page = get_page(page_id)  # Raises KeyError if not found
    await page.close()
    del _pages[page_id]


async def page_screenshot_base64(page_id: str, full_page: bool = False) -> str:
    """Take a screenshot of the page and return it as a base64 data URL."""
    page = await get_page(page_id)
    screenshot_bytes = await page.screenshot(full_page=full_page, type="png")
    b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_data}"


async def cleanup() -> None:
    """Close all pages and cleanup browser resources."""
    global _browser, _context, _playwright_instance, _pages

    # Close all pages
    for page in _pages.values():
        await page.close()
    _pages.clear()

    # Close context and browser
    if _context:
        await _context.close()
        _context = None

    if _browser:
        await _browser.close()
        _browser = None

    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None
