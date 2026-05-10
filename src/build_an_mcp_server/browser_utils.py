from __future__ import annotations

import base64

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import ServerSettings

_playwright_instance = None
_browser: Browser | None = None
_context: BrowserContext | None = None
_pages: dict[str, Page] = {}
_page_counter = 0


async def _ensure_browser() -> Browser:
    global _playwright_instance, _browser, _context

    if _browser is None:
        _playwright_instance = await async_playwright().start()
        _browser = await _playwright_instance.chromium.launch(headless=True)
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 720},
        )

    return _browser


async def new_page() -> str:
    global _page_counter

    await _ensure_browser()
    assert _context is not None

    page = await _context.new_page()
    _page_counter += 1
    page_id = f"page_{_page_counter}"
    _pages[page_id] = page
    return page_id


async def get_page(page_id: str) -> Page:
    if page_id not in _pages:
        raise KeyError(f"Page '{page_id}' not found")
    return _pages[page_id]


async def close_page(page_id: str) -> None:
    page = await get_page(page_id)
    await page.close()
    del _pages[page_id]


async def page_screenshot_base64(page_id: str, full_page: bool = False) -> str:
    page = await get_page(page_id)
    screenshot_bytes = await page.screenshot(full_page=full_page, type="png")
    b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_data}"


async def cleanup() -> None:
    global _browser, _context, _playwright_instance

    for page in list(_pages.values()):
        await page.close()
    _pages.clear()

    if _context is not None:
        await _context.close()
        _context = None

    if _browser is not None:
        await _browser.close()
        _browser = None

    if _playwright_instance is not None:
        await _playwright_instance.stop()
        _playwright_instance = None


def register_browser_capabilities(
    mcp: FastMCP,
    settings: ServerSettings,
) -> None:
    """Register minimal browser capabilities for the Chapter 4 runtime."""

    @mcp.tool()
    async def browser_health_check() -> CallToolResult:
        try:
            page_id = await new_page()
            page = await get_page(page_id)
            await page.goto("data:text/html,<title>Browser Test</title><h1>OK</h1>")
            title = await page.title()
            await close_page(page_id)
        except Exception as exc:
            return CallToolResult(
                content=[TextContent(type="text", text=str(exc))],
                isError=True,
            )

        return CallToolResult(
            content=[TextContent(type="text", text="Browser automation is working.")],
            structuredContent={"status": "healthy", "title": title},
        )
