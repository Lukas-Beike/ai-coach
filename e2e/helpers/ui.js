"use strict";

// Shared browser-test helpers. Pure Node functions: they read computed styles
// and geometry that the spec collected through page.evaluate / Playwright APIs.

const COMPOSER_TOLERANCE_PX = 0.5;

function channelLuminance(value) {
  const normalized = value / 255;
  return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(cssColor) {
  const [red, green, blue] = cssColor.match(/[\d.]+/g).slice(0, 3).map(Number).map(channelLuminance);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

// WCAG contrast ratio for two CSS rgb()/rgba() color strings, e.g. the
// `color` and `backgroundColor` values returned by getComputedStyle.
function contrastRatio(foreground, background) {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  return (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
}

async function rectOf(locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("Element has no bounding box; it is not rendered");
  return {
    top: box.y,
    bottom: box.y + box.height,
    left: box.x,
    right: box.x + box.width,
    width: box.width,
    height: box.height,
  };
}

// True when the element sits entirely above the composer and inside the viewport top edge.
async function isFullyAbove(locator, composerLocator) {
  const [rect, composer] = await Promise.all([rectOf(locator), rectOf(composerLocator)]);
  return rect.bottom <= composer.top + COMPOSER_TOLERANCE_PX && rect.top >= 0;
}

// Counts page requests whose URL matches a substring or RegExp, from the
// moment of the call until stop() is invoked.
function countRequests(page, pattern) {
  let count = 0;
  const matches = (url) => {
    if (typeof pattern === "string") return url.includes(pattern);
    pattern.lastIndex = 0;
    return pattern.test(url);
  };
  const onRequest = (request) => {
    if (matches(request.url())) count += 1;
  };
  page.on("request", onRequest);
  return {
    count: () => count,
    stop: () => {
      page.off("request", onRequest);
    },
  };
}

module.exports = {
  contrastRatio,
  rectOf,
  isFullyAbove,
  countRequests,
};
