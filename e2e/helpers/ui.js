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

// Steps the calendar's week view to the week that holds dateKey.
async function showCalendarDay(page, dateKey) {
  for (let step = 0; step < 60; step += 1) {
    if (await page.locator(`.planned-day[data-date="${dateKey}"]`).count()) return;
    const shown = await page.locator(".planned-week").getAttribute("data-week-key");
    await page.locator(`.planned-week-step[data-week-step="${dateKey < shown ? -1 : 1}"]`).click();
  }
  throw new Error(`calendar day ${dateKey} is outside the shown weeks`);
}

// Steps the week view to the first calendar entry that matches: a name part, a planned
// or recorded workout profile, or a unit after today still pending for a provider.
async function showCalendarEntry(page, match) {
  const wanted = typeof match === "string" ? { name: match } : match;
  const dateKey = await page.evaluate((criteria) => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const entry = (state.data?.training_calendar || []).find((item) => item && plannedEventDate(item)
      && (!criteria.name || String(item.name || "").includes(criteria.name))
      && (!criteria.profile || (criteria.profile === "planned" ? Boolean(item.workout_profile) && !item.is_completed_activity : JSON.stringify(item).includes('"source":"recorded"')))
      && (!criteria.pending || (item.push_pending?.[criteria.pending] && plannedEventDate(item) > today)));
    return entry ? plannedEventDate(entry) : "";
  }, wanted);
  if (!dateKey) throw new Error(`no calendar entry matches ${JSON.stringify(wanted)}`);
  await showCalendarDay(page, dateKey);
}

// Puts synthetic completed sessions on today's calendar day and renders the week (#2258).
async function renderCalendarSessions(page, sessions) {
  await page.evaluate(async (items) => {
    await AppRouter.navigate("plan/overview", { historyMode: "replace" });
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    // The calendar places a completed session by its local start, so it moves to today at its own time.
    state.data.training_calendar = items.map((item) => ({ ...item, date: today, is_completed_activity: true, started_at_local: `${today}T${String(item.started_at_local || "").slice(11) || "08:00:00"}` }));
    renderPlanned(state.data.training_calendar);
  }, sessions);
}

// Opens a completed session's card and its "Details"; returns the details element.
async function openSessionDetails(page, name) {
  const card = page.locator(".planned-entry.is-completed").filter({ hasText: name }).first();
  await card.evaluate((element) => { element.open = true; });
  const more = card.locator(".planned-activity-more");
  await more.locator(":scope > summary").click();
  return more;
}

module.exports = {
  renderCalendarSessions,
  openSessionDetails,
  showCalendarDay,
  showCalendarEntry,
  contrastRatio,
  rectOf,
  isFullyAbove,
  countRequests,
};
