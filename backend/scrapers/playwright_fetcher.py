import asyncio
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


class PlaywrightFetcher:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._browser is not None and self._context is not None

    async def _ensure_context(self):
        if self._context:
            return self._context

        async with self._lock:
            if self._context:
                return self._context

            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._launch_browser()
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            return self._context

    async def _launch_browser(self):
        try:
            return await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            if "Executable doesn't exist" not in str(exc):
                raise
            logger.warning("Playwright browser executable missing; installing Chromium at runtime.")
            await asyncio.to_thread(self._install_chromium)
            return await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )

    def _install_chromium(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )

    async def fetch(self, url: str, wait_ms: int = 1800) -> str:
        context = await self._ensure_context()
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(wait_ms)
            return await page.content()
        finally:
            await page.close()

    async def shutdown(self) -> None:
        async with self._lock:
            try:
                if self._context:
                    await self._context.close()
                if self._browser:
                    await self._browser.close()
                if self._playwright:
                    await self._playwright.stop()
            except Exception as exc:
                logger.warning("Playwright shutdown failed: %s", exc)
            finally:
                self._context = None
                self._browser = None
                self._playwright = None


playwright_fetcher = PlaywrightFetcher()
