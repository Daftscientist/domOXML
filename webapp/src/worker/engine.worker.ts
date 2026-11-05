// Engine worker: Pyodide + the domOXML bundle + the Takumi bridge, all off
// the UI thread. The UI never waits on this file to draw itself; it boots,
// reports status, then answers preview / convert / readDeck requests.
import { installTakumiBridge, takumiBridge } from "../../bridge/takumi-bridge.mjs";

type BootMessage = { type: "boot"; pyBase: string; pyodideIndexURL: string };

const status = (phase: string, detail?: string) =>
  (self as DedicatedWorkerGlobalScope).postMessage({ type: "status", phase, detail });

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let api: any = null;
let bootState: "idle" | "booting" | "booted" = "idle";

// Surface worker-side failures to the page instead of hanging silently.
self.addEventListener("error", (event) =>
  status("error", event.message || "Engine worker error"),
);
self.addEventListener("unhandledrejection", (event) =>
  status("error", event.reason instanceof Error ? event.reason.message : String(event.reason)),
);

async function boot(msg: BootMessage) {
  if (bootState !== "idle") return;
  bootState = "booting";
  try {
    status("starting", "Loading the Python runtime");
    // Pyodide ships as an ES module on the CDN; Vite must not try to bundle it.
    const { loadPyodide } = await import(/* @vite-ignore */ `${msg.pyodideIndexURL}pyodide.mjs`);

    const manifestResponse = await fetch(`${msg.pyBase}bundle-manifest.json`);
    if (!manifestResponse.ok) throw new Error("Could not fetch the domOXML bundle manifest");
    const manifest = await manifestResponse.json();

    status("packages", "Downloading Python packages");
    const pyodide = await loadPyodide({
      indexURL: msg.pyodideIndexURL,
      // Packages download and install as part of runtime initialisation
      // instead of in a second pass afterwards.
      packages: manifest.packages_eager,
    });

    status("bundle", "Unpacking domOXML");
    const zipResponse = await fetch(`${msg.pyBase}${manifest.bundle}`);
    if (!zipResponse.ok) throw new Error("Could not fetch the domOXML bundle");
    const zip = await zipResponse.arrayBuffer();
    pyodide.unpackArchive(zip, "zip", { extractDir: "/bundle" });

    installTakumiBridge(self);
    const bootSource = await (await fetch(`${msg.pyBase}boot.py`)).text();
    await pyodide.runPythonAsync(bootSource);
    api = pyodide.globals.get("domoxml_api");
    bootState = "booted";
    status("ready");
  } catch (error) {
    bootState = "idle";
    status("error", error instanceof Error ? error.message : String(error));
  }
}

self.onmessage = async (event: MessageEvent) => {
  const msg = event.data;
  if (msg.type === "boot") {
    void boot(msg);
    return;
  }
  const { id, type, payload } = msg;
  const reply = (ok: boolean, result?: unknown, error?: string, transfer: Transferable[] = []) =>
    (self as DedicatedWorkerGlobalScope).postMessage({ type: "result", id, ok, result, error }, transfer);
  try {
    if (!api) throw new Error("Engine is still starting");
    if (type === "preview") {
      const png: Uint8Array = await api.get("preview")(JSON.stringify(payload));
      const copy = new Uint8Array(png); // detach from the Pyodide heap view before transfer
      reply(true, copy, undefined, [copy.buffer as ArrayBuffer]);
    } else if (type === "convert") {
      const text: string = await api.get("convert")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "capturePages") {
      const text: string = await api.get("capture_pages")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "capturePlan") {
      const text: string = await api.get("capture_plan")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "convertCaptured") {
      const text: string = await api.get("convert_captured")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "slideIr") {
      const text: string = await api.get("slide_ir")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "normalize") {
      const text: string = await api.get("normalize")(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "takumiRaster") {
      // Rasterise one page (a whole slide, or one staged isolated node)
      // with Takumi, in this worker, without involving Python.
      const text: string = await takumiBridge(JSON.stringify(payload));
      reply(true, JSON.parse(text));
    } else if (type === "readDeck") {
      const text: string = await api.get("read_deck")(payload);
      reply(true, JSON.parse(text));
    } else {
      throw new Error(`Unknown request: ${type}`);
    }
  } catch (error) {
    reply(false, undefined, error instanceof Error ? error.message : String(error));
  }
};

// Announce that the message handler is live. The page sends its boot
// message in reply: posting boot the instant the Worker object exists can
// race module evaluation in some browsers and the message is lost, which
// would otherwise hang the engine silently.
(self as DedicatedWorkerGlobalScope).postMessage({ type: "hello" });
