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
        await pg.wait_for_timeout(5000)
        print("handler:", await worker.evaluate("() => self.onmessage.toString().slice(0, 160)"))
        out = await worker.evaluate(f"""async () => {{
          self.__heard = [];
          const ev = new MessageEvent("message", {{ data: {{ type: "boot",
            pyBase: "{BASE}/py/", pyodideIndexURL: "{BASE}/pyodide/" }} }});
          self.dispatchEvent(ev);
          return "dispatched";
        }}""")
        print(out)
        for i in range(4):
            await pg.wait_for_timeout(8000)
            n = await worker.evaluate("() => performance.getEntriesByType('resource').length")
            br = await worker.evaluate("() => typeof self.domoxmlTakumiBridge")
            print(f"t={(i+1)*8}s resources={n} bridge={br}")
            if br == "function":
                break
        await b.close()

asyncio.run(main())
