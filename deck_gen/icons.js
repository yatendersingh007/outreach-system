// Pre-render a fixed set of react-icons to gold PNGs (256px, transparent bg)
// into deck_gen/icons/*.png. Idempotent: skips icons that already exist.
// Run: node icons.js   (build_deck.js loads the PNGs; it does not need react/sharp)
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");
const fs = require("fs");
const path = require("path");

const GOLD = "#C5A84A";
const OUT = path.join(__dirname, "icons");

const MAP = {
  "calculator": fa.FaCalculator,
  "layer-group": fa.FaLayerGroup,
  "chart-line": fa.FaChartLine,
  "magnifying-glass-dollar": fa.FaMagnifyingGlassDollar,
  "file-lines": fa.FaFileLines,
  "coins": fa.FaCoins,
  "users": fa.FaUsers,
  "clock": fa.FaClock,
  "shield-halved": fa.FaShieldHalved,
  "scale-balanced": fa.FaScaleBalanced,
};

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  let made = 0;
  for (const [name, Comp] of Object.entries(MAP)) {
    const outPath = path.join(OUT, name + ".png");
    if (fs.existsSync(outPath)) continue;
    if (!Comp) { console.error("MISSING component for " + name); continue; }
    // react-icons paths use fill="currentColor"; set both color + fill for rasterizers.
    const svg = ReactDOMServer.renderToStaticMarkup(
      React.createElement(Comp, { color: GOLD, fill: GOLD, size: "256" })
    );
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    fs.writeFileSync(outPath, png);
    made++;
  }
  console.log(`icons ready in ${OUT} (${made} generated, ${Object.keys(MAP).length} total)`);
}

main().catch((e) => { console.error("ICON_ERROR " + e.message); process.exit(3); });
