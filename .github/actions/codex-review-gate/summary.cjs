'use strict';

function parseCodeReviewSummary(body) {
  const row = String(body || '')
    .split(/\r?\n/)
    .find((line) => /\*\*Code Review\*\*/i.test(line));
  if (!row) {
    return undefined;
  }

  const cells = row.split('|').map((cell) => cell.trim());
  const reviewCell = cells.findIndex((cell) => /\*\*Code Review\*\*/i.test(cell));
  if (reviewCell < 0 || cells.length <= reviewCell + 2) {
    return undefined;
  }

  const statusCell = cells[reviewCell + 1];
  const commitCell = cells[reviewCell + 2];
  const commit = commitCell.match(/`([0-9a-f]{7,40})`/i)?.[1]?.toLowerCase();
  if (!commit) {
    return undefined;
  }

  const completedAtText = statusCell.match(/<relative-time\b[^>]*\bdatetime=["']([^"']+)["']/i)?.[1];
  return {
    commit,
    status: /\*\*Completed\*\*/i.test(statusCell) ? 'completed' : 'pending',
    completedAt: completedAtText ? Date.parse(completedAtText) : Number.NaN,
  };
}

function commitMatchesHead(commit, headSha) {
  return (
    typeof commit === 'string' &&
    /^[0-9a-f]{40}$/i.test(commit) &&
    typeof headSha === 'string' &&
    /^[0-9a-f]{40}$/i.test(headSha) &&
    headSha.toLowerCase() === commit.toLowerCase()
  );
}

function timestampAtSecond(value) {
  const timestamp = typeof value === 'number' ? value : Date.parse(value || '');
  return Number.isFinite(timestamp) ? Math.floor(timestamp / 1000) : Number.NaN;
}

function isAtOrAfterTimestamp(value, minimum) {
  const actual = timestampAtSecond(value);
  const threshold = timestampAtSecond(minimum);
  return Number.isFinite(actual) && Number.isFinite(threshold) && actual >= threshold;
}

module.exports = {
  commitMatchesHead,
  isAtOrAfterTimestamp,
  parseCodeReviewSummary,
  timestampAtSecond,
};
