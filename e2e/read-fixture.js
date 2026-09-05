// Browser contract tests reuse freshly generated read-only API projections.
// Runtime smoke tests remain on the real HTTP/SQLCipher path in coach.spec.js.
const paths = ["/api/bootstrap?local=1", "/api/chat/history?limit=100", "/api/activities?limit=250", "/api/plan?local=1", "/api/weather?local=1", "/api/library?limit=100", "/api/performance", "/api/feedback", "/api/profile", "/api/chat/status", "/api/sync/status"];

async function captureReadFixture(request) {
  const data = new Map();
  for (const path of paths) {
    const response = await request.get(path);
    if (!response.ok()) throw new Error(`Fixture projection unavailable: ${path} (${response.status()})`);
    data.set(path.split("?")[0], await response.json());
  }
  return data;
}

async function installReadFixture(page, data) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "GET" && data.has(path)) {
      await route.fulfill({ json: data.get(path) });
    } else await route.continue();
  });
}

module.exports = { captureReadFixture, installReadFixture };
