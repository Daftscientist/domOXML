import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost:8325"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page()
        wt = asyncio.create_task(pg.wait_for_event("worker", timeout=30000))
        await pg.goto(f"{BASE}/?pyodide={BASE}/pyodide/", wait_until="load", timeout=60000)
        worker = await wt
        await pg.wait_for_timeout(6000)
        for expr in [
            "typeof self.onmessage",
            "typeof self.domoxmlTakumiBridge",
            "Object.keys(self).filter(k => /takumi|pyodide|domoxml/i.test(k)).join(',')",
            "document === undefined ? 'worker-scope' : 'window'",
            "performance.getEntriesByType('resource').length",
        ]:
            try:
                print(expr, "=>", await worker.evaluate(f"() => String({expr})"))
            except Exception as e:
                print(expr, "=> ERR", str(e)[:140])
        await b.close()

asyncio.run(main())
