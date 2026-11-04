import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost:8325"

INIT = """
window.__wlog = [];
const OrigWorker = window.Worker;
window.Worker = class extends OrigWorker {
  constructor(url, opts) {
    super(url, opts);
    window.__wlog.push("created " + url);
    const origPost = this.postMessage.bind(this);
    this.postMessage = (msg, ...rest) => {
      window.__wlog.push("posted " + JSON.stringify(msg).slice(0, 120));
      return origPost(msg, ...rest);
    };
    this.addEventListener("message", (e) => {
      window.__wlog.push("recv " + JSON.stringify(e.data).slice(0, 120));
    });
    this.addEventListener("error", (e) => {
      window.__wlog.push("WORKER ERROR " + (e.message || e.type));
    });
  }
};
"""

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 800})
        await pg.add_init_script(INIT)
        pg.on("console", lambda m: print("CONSOLE", m.type, m.text[:160]))
        await pg.goto(f"{BASE}/?pyodide={BASE}/pyodide/", wait_until="load", timeout=60000)
        for i in range(4):
            await pg.wait_for_timeout(10000)
            log = await pg.evaluate("window.__wlog")
            print(f"--- t={(i+1)*10}s")
            for line in log:
                print("   ", line)
        await b.close()

asyncio.run(main())
