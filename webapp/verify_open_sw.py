"""Verify: (1) opening a real .pptx into the viewer, (2) service worker
offline reload: second visit must boot the engine with the network off."""
import asyncio, os
from playwright.async_api import async_playwright

OUT = "/home/hatch/workspace/domoxml-web-work/webapp/shots"
BASE = "http://localhost:8321/?pyodide=http://localhost:8321/pyodide/"
PPTX = "/home/hatch/workspace/online-presence/linkedin-domoxml-image/pipeline.pptx"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: print("PAGEERROR", str(e)[:200]))
        await pg.goto(BASE, wait_until="load", timeout=60000)
        await pg.wait_for_selector('img[alt="Slide 1 preview"]', timeout=180000)
        print("first load: engine ready")

        # --- Open a real PPTX ---
        await pg.set_input_files('input[type="file"]', PPTX)
        await pg.wait_for_timeout(6000)
        name = await pg.evaluate("document.querySelector('header input')?.value")
        print("deck name after open:", name)
        await pg.screenshot(path=f"{OUT}/09-open-pptx.png")
        print("open-pptx shot done")

        # --- Service worker: control + offline reload ---
        sw = await pg.evaluate("navigator.serviceWorker.controller ? 'controlled' : 'none'")
        print("SW controller:", sw)
        await pg.reload(wait_until="load")
        await pg.wait_for_timeout(1500)
        sw2 = await pg.evaluate("navigator.serviceWorker.controller ? 'controlled' : 'none'")
        print("SW controller after reload:", sw2)
        await ctx.set_offline(True)
        await pg.reload(wait_until="load")
        try:
            await pg.wait_for_selector('img[alt="Slide 1 preview"]', timeout=90000)
            print("OFFLINE reload: engine booted and rendered from cache")
        except Exception as e:
            print("OFFLINE reload FAILED:", str(e)[:140])
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/10-offline-reload.png")
        await ctx.set_offline(False)
        await b.close()

asyncio.run(main())
