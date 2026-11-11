const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const TRAINING_RECORDS = "/api/analysis/training-records";

function createContext(calls) {
  return extractFunctions("analysis.js", ["analysisReportCache", "analysisReportVersionKey", "requestAnalysisReport", "invalidateAnalysisReport", "clearAnalysisReportCache"], {
    state: { data: { state_versions: { training: 1 } } },
    DATA_LOAD_TIMEOUT_MS: 15_000,
    api: async (requestPath, options) => {
      // Analysis reports time out into a retry state instead of a permanent loading line (#1783).
      assert.equal(options?.timeoutMs, 15_000);
      calls.push(requestPath);
      return { path: requestPath, call: calls.length };
    },
  });
}

test("training records are reused for the same state version until invalidated", async () => {
  const calls = [];
  const context = createContext(calls);

  const first = await context.requestAnalysisReport(TRAINING_RECORDS);
  const second = await context.requestAnalysisReport(TRAINING_RECORDS);
  assert.equal(calls.length, 1);
  assert.equal(second, first);

  context.invalidateAnalysisReport(TRAINING_RECORDS);
  const afterMaintenance = await context.requestAnalysisReport(TRAINING_RECORDS);
  assert.equal(calls.length, 2);
  assert.notEqual(afterMaintenance, first);
});

test("invalidation drops only the named report", async () => {
  const calls = [];
  const context = createContext(calls);

  await context.requestAnalysisReport(TRAINING_RECORDS);
  await context.requestAnalysisReport("/api/analysis/endurance");
  context.invalidateAnalysisReport(TRAINING_RECORDS);
  await context.requestAnalysisReport("/api/analysis/endurance");

  assert.deepEqual(calls, [TRAINING_RECORDS, "/api/analysis/endurance"]);
});
