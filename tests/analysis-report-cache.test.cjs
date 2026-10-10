const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/analysis.js"), "utf8");
const start = source.indexOf("const analysisReportCache = new Map();");
const end = source.indexOf("\nasync function loadAnalysisReports", start);
const TRAINING_RECORDS = "/api/analysis/training-records";

function createContext(calls) {
  const context = vm.createContext({
    state: { data: { state_versions: { training: 1 } } },
    api: async (requestPath) => {
      calls.push(requestPath);
      return { path: requestPath, call: calls.length };
    },
  });
  vm.runInContext(source.slice(start, end), context);
  return context;
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
