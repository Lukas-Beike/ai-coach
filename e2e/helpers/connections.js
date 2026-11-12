"use strict";

const { expect } = require("@playwright/test");

const CONNECTIONS = Object.freeze(["garmin", "wahoo", "intervals", "openai", "yazio", "calendar", "weather"]);

// Opens the named provider cards in Mehr › Anbindungen (all of them by default).
async function expandConnections(page, providers = CONNECTIONS) {
  await expect(page.locator('[data-more-segment-panel="connections"]')).toBeVisible();
  for (const provider of providers) {
    const card = page.locator(`#connection-${provider}`);
    if (!(await card.evaluate((element) => element.open))) await card.locator("summary").click();
    await expect(card).toHaveAttribute("open", "");
  }
}

module.exports = { expandConnections };
