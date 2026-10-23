"use strict";

const { expect } = require("@playwright/test");

async function expandConnections(page) {
  const section = page.locator('details[data-more-segment-panel="connections"]');
  await expect(section).toBeVisible();
  if (!(await section.evaluate((element) => element.open))) await section.locator("summary").first().click();
  await expect(section).toHaveAttribute("open", "");
}

module.exports = { expandConnections };
