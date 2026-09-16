"""Скриншоты основных экранов для самопроверки (нужен запущенный tests/offline_server.py)."""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ".impeccable/review")
OUT.mkdir(parents=True, exist_ok=True)


async def shoot(browser, name, width, height, actions):
    ctx = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, reduced_motion="reduce")
    page = await ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    await actions(page)
    await page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } window.scrollTo(0, 0); }""")
    await page.wait_for_timeout(500)
    await page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    await ctx.close()
    return name, [e for e in errors if "Failed to load resource" not in e][:5]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        async def home(page):
            await page.goto(BASE + "/")
            await page.wait_for_timeout(600)

        async def home_ambiguous(page):
            await page.goto(BASE + "/")
            await page.fill("input[role=combobox]", "Евразийский")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)

        async def building(page):
            await page.goto(BASE + "/u/Q127745?fresh=1")
            await page.wait_for_timeout(2500)

        async def profile(page):
            await page.goto(BASE + "/u/Q127745")
            await page.wait_for_selector("text=Фонд фотографий")
            await page.wait_for_selector(".progress:not(.is-building)", timeout=45000)
            await page.wait_for_timeout(1500)

        async def fact_hover(page):
            await profile(page)
            await page.hover(".fact--confirmed")
            await page.wait_for_timeout(400)

        async def record(page):
            await profile(page)
            await page.click(".ccard__open")
            await page.wait_for_timeout(700)

        async def fact_tap(page):
            await profile(page)
            await page.click(".fact--confirmed[data-clickable=true] .fact__value")
            await page.wait_for_timeout(700)

        async def terms(page):
            await page.goto(BASE + "/privacy")
            await page.wait_for_timeout(400)

        jobs = [
            ("desktop-home", 1440, 900, home),
            ("desktop-ambiguous", 1440, 900, home_ambiguous),
            ("desktop", 1440, 900, profile),
            ("desktop-fact-hover", 1440, 900, fact_hover),
            ("desktop-record", 1440, 900, record),
            ("mobile-home", 390, 844, home),
            ("mobile", 390, 844, profile),
            ("mobile-record", 390, 844, record),
            ("mobile-fact-tap", 390, 844, fact_tap),
            ("desktop-privacy", 1440, 900, terms),
        ]
        for name, w, h, fn in jobs:
            print(await shoot(browser, name, w, h, fn))
        await browser.close()


asyncio.run(main())
