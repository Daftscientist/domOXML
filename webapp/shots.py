"""Full visual pass over the built app (engine pointed at the local mirror)."""
import asyncio, os
from playwright.async_api import async_playwright

OUT = "/home/hatch/workspace/domoxml-web-work/webapp/shots"
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:8321/?pyodide=http://localhost:8321/pyodide/"

async def wait_engine(pg, timeout=180000):
    # A rendered stage image means: Pyodide booted, bundle imported, the
    # Takumi bridge ran, and a PNG came back.
    await pg.wait_for_selector('img[alt="Slide 1 preview"]', timeout=timeout)
    await pg.wait_for_timeout(2500)

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        pg.on("pageerror", lambda e: print("PAGEERROR", str(e)[:200]))
        await pg.goto(BASE, wait_until="load", timeout=60000)
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/01-desktop-light-boot.png")
        print("boot shot")
        await wait_engine(pg)
        print("engine ready, previews rendered")
        await pg.screenshot(path=f"{OUT}/02-desktop-light.png")
        # zoom into the stage area for a close look at the slide render
        await pg.screenshot(path=f"{OUT}/02b-stage-zoom.png", clip={"x": 330, "y": 60, "width": 760, "height": 560})
        # second slide
        await pg.get_by_text("1 / 3").wait_for()
        await pg.locator("button[aria-label='Next slide']").click()
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/02c-slide2.png")
        await pg.locator("button[aria-label='Previous slide']").click()
        await pg.wait_for_timeout(1500)
        # Slide (transitions) tab
        await pg.get_by_role("tab", name="Slide").click()
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/02d-inspector-slide.png")
        # Deck tab
        await pg.get_by_role("tab", name="Deck").click()
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/02e-inspector-deck.png")
        await pg.get_by_role("tab", name="HTML").click()
        # Dark theme
        await pg.get_by_role("button", name="Toggle colour theme").click()
        await pg.wait_for_timeout(900)
        await pg.screenshot(path=f"{OUT}/03-desktop-dark.png")
        print("desktop shots done")
        # Export end-to-end (convert through the worker, dialog shows coverage)
        await pg.get_by_role("button", name="Toggle colour theme").click()
        await pg.wait_for_timeout(500)
        async with pg.expect_download(timeout=60000) as dl:
            await pg.get_by_role("button", name="Export .pptx").first.click()
        download = await dl.value
        print("downloaded:", download.suggested_filename)
        await pg.get_by_text("Export complete").wait_for(timeout=30000)
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/07-export-dialog.png")
        await pg.get_by_role("button", name="Done").click()
        # Present mode
        await pg.get_by_role("button", name="Present").first.click()
        await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/08-present.png")
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(400)
        await pg.close()
        print("present shot done")

        # Mobile
        m = await b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                             is_mobile=True, has_touch=True)
        m.on("pageerror", lambda e: print("M PAGEERROR", str(e)[:200]))
        await m.goto(BASE, wait_until="load", timeout=60000)
        await wait_engine(m)
        await m.screenshot(path=f"{OUT}/04-mobile-preview.png")
        await m.get_by_role("button", name="Edit").click()
        await m.wait_for_timeout(800)
        await m.screenshot(path=f"{OUT}/05-mobile-edit.png")
        await m.get_by_role("button", name="Slides").click()
        await m.wait_for_timeout(800)
        await m.screenshot(path=f"{OUT}/06-mobile-slides.png")
        await m.close()
        await b.close()
        print("all shots done")

asyncio.run(main())
