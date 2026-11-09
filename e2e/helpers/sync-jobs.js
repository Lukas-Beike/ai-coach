"use strict";

// The fixture never contacts a provider: answer the job queue and its poll in
// the page and return the posted job bodies.
async function stubSyncJobs(page) {
  const posted = [];
  await page.route("**/api/sync/jobs", async (route) => {
    posted.push(JSON.parse(route.request().postData() || "{}"));
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ id: `job-${posted.length}`, status: "queued" }) });
  });
  await page.route("**/api/sync/jobs/job-*", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "job", status: "completed", items: [] }) }));
  return posted;
}

module.exports = { stubSyncJobs };
