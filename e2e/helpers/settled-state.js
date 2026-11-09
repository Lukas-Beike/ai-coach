"use strict";

const { expect } = require("@playwright/test");

// Waits until the page has finished its own startup traffic: the initial state load and any
// follow-up load are done, and the server's sync versions match what the page already shows.
// A version the page has not loaded yet makes it reload that area (and re-request its
// views) at an unpredictable moment, so tests that count requests or act on cached
// messages start from this state.
// Justified internal probe: none of this is visible in the DOM, and the loads are not
// distinguishable network responses.
async function waitForSettledState(page) {
  await expect.poll(() => page.evaluate(async () => {
    const status = await api("/api/sync/status");
    return state.initialStateLoaded
      && !state.loadPromise
      && state.pendingLoads.size === 0
      && !state.deferredLoad
      && !state.syncPoll.controller
      && !status.running
      && changedSyncAreas(status.state_versions).length === 0;
  })).toBe(true);
}

module.exports = { waitForSettledState };
