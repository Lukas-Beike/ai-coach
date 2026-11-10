// Renders the PWA PNG icons from public/icon.svg with the Chromium that Playwright installs.
// Usage: node scripts/generate_pwa_icons.mjs
// The maskable icon is full-bleed (no corner radius) with the artwork scaled to 80 percent
// of the canvas so it stays inside the 40 percent safe-zone circle.
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const source = readFileSync(new URL("../public/icon.svg", import.meta.url), "utf8");
const artwork = source.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<rect[^>]*\/>/, "").replace("</svg>", "");
const maskable = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="#102a2a"/><g transform="translate(256 256) scale(0.8) translate(-256 -256)">${artwork}</g></svg>`;
const targets = [
  ["icon-192.png", 192, source],
  ["icon-512.png", 512, source],
  ["icon-maskable-512.png", 512, maskable],
];

const browser = await chromium.launch();
try {
  for (const [name, size, svg] of targets) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await page.setContent(`<body style="margin:0;background:transparent"><img width="${size}" height="${size}" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">`);
    await page.locator("img").evaluate((img) => img.decode());
    writeFileSync(new URL(`../public/${name}`, import.meta.url), await page.screenshot({ omitBackground: true, type: "png" }));
    await page.close();
  }
} finally {
  await browser.close();
}
