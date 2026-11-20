// Runs ELK (layered, orthogonal) for several option variants.
// stdin : {"graph": <ELK graph>, "variants": [<layoutOptions>, ...]}
// stdout: [{"variant": {...}, "layout": <ELK result>} | {"variant": {...}, "error": "..."}]
// Needs elkjs: `npm install elkjs` in any folder, then set ELKJS_DIR to that folder's node_modules/elkjs.
const ELK = require(require("path").join(process.env.ELKJS_DIR, "lib", "elk.bundled.js"));
const elk = new ELK();

(async () => {
  const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
  const out = [];
  for (const variant of input.variants) {
    const graph = JSON.parse(JSON.stringify(input.graph));
    graph.layoutOptions = { ...graph.layoutOptions, ...variant };
    try {
      out.push({ variant, layout: await elk.layout(graph) });
    } catch (e) {
      out.push({ variant, error: String(e) });
    }
  }
  process.stdout.write(JSON.stringify(out));
})();
