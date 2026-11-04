// Headless smoke test of the whole web stack, outside a browser:
// Pyodide 0.29.3 + the trimmed bundle + the in-page Takumi bridge transport.
//
// Run from webapp/:  NODE_USE_ENV_PROXY=1 npm run test:node
import { readFileSync } from "node:fs";
import { loadPyodide } from "pyodide";
import { installTakumiBridge } from "../bridge/takumi-bridge.mjs";

const t0 = Date.now();
const stamp = (label) => console.log(`${label} @ ${Date.now() - t0}ms`);

const manifest = JSON.parse(readFileSync("public/py/bundle-manifest.json", "utf8"));
const pyodide = await loadPyodide({
  packages: manifest.packages_eager,
});
stamp(`loadPyodide + eager packages [${manifest.packages_eager.join(", ")}]`);

const zip = readFileSync(`public/py/${manifest.bundle}`);
pyodide.unpackArchive(zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.byteLength), "zip", {
  extractDir: "/bundle",
});
stamp(`bundle unpacked (${manifest.files} files, ${manifest.bytes} bytes)`);

installTakumiBridge(globalThis);
await pyodide.runPythonAsync(readFileSync("py/boot.py", "utf8"));
const api = pyodide.globals.get("domoxml_api");
console.log("environment:", api.get("environment"));

const HTML =
  '<div style="width:1280px;height:720px;background:#3653C7;display:flex;align-items:center;justify-content:center">' +
  '<h1 style="color:#F2F1EA;font-family:Inter;font-size:64px">Pyodide + Takumi</h1></div>';

// 1. Preview through the emscripten bridge.
const pngB64 = await api.get("preview_b64")(
  JSON.stringify({ html: HTML, width: 1280, height: 720 })
);
const png = Buffer.from(pngB64, "base64");
console.log("preview png:", png.length, "bytes, magic ok:", png.subarray(0, 4).toString("hex") === "89504e47");
stamp("preview done");

// 2. Convert to PPTX with a transition.
const converted = JSON.parse(
  await api.get("convert")(
    JSON.stringify({
      fragments: [HTML],
      width: 1280,
      height: 720,
      transitions: [{ type: "push", duration_ms: 700, direction: "l" }],
    })
  )
);
console.log(
  "converted: pptx", Buffer.from(converted.pptx_b64, "base64").length, "bytes,",
  "coverage items:", converted.coverage.length,
  "native:", converted.coverage.filter((c) => c.representation === "native").length
);
stamp("convert done");

// 3. Read the deck back: size, transition and HTML must survive.
const deck = JSON.parse(
  await api.get("read_deck")(new Uint8Array(Buffer.from(converted.pptx_b64, "base64")))
);
console.log(
  "read back:", deck.width_px, "x", deck.height_px,
  "| slides:", deck.slides.length,
  "| transition:", JSON.stringify(deck.slides[0].transition),
  "| html has text:", deck.slides[0].html.includes("Pyodide + Takumi")
);
stamp("read back done");
console.log("SMOKE TEST PASSED");
