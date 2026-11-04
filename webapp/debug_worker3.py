import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost:8325"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 800})
        worker_task = asyncio.create_task(pg.wait_for_event("worker", timeout=30000))
        await pg.goto(f"{BASE}/?pyodide={BASE}/pyodide/", wait_until="load", timeout=60000)
        worker = await worker_task
        await pg.wait_for_timeout(4000)
        text = await pg.evaluate("document.body.innerText.slice(0,200)")
        print("PAGE:", [ln for ln in text.split("\n") if "ngine" in ln])

        async def step(name, expr, timeout_s=60):
            try:
                out = await asyncio.wait_for(worker.evaluate(expr), timeout=timeout_s)
                print(name, "=>", out)
            except asyncio.TimeoutError:
                print(name, "=> TIMEOUT (still pending)")
            except Exception as e:
                print(name, "=> EVAL ERROR:", str(e)[:220])

        await step("fetch manifest", f"""async () => {{
          const r = await fetch("{BASE}/py/bundle-manifest.json");
          return "status " + r.status;
        }}""", 20)
        await step("import pyodide.mjs", f"""async () => {{
          const m = await import("{BASE}/pyodide/pyodide.mjs");
          return "keys: " + Object.keys(m).join(",");
        }}""", 60)
        await step("loadPyodide minimal", f"""async () => {{
          const m = await import("{BASE}/pyodide/pyodide.mjs");
          const py = await m.loadPyodide({{ indexURL: "{BASE}/pyodide/" }});
          return "loaded, 1+1=" + py.runPython("1+1");
        }}""", 90)
        await b.close()

asyncio.run(main())
