"use strict";

const { expect } = require("@playwright/test");

async function openCalendar(page, request) {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  await expect(page.locator(".planned-day.is-today")).toHaveCount(1);
}

// A deterministic calendar around today: collapsible past day, a missed day, repeated extras, a profile and a conflict.
async function renderSyntheticCalendar(page) {
  return page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const day = (offset) => addDateKey(today, offset);
    const profile = { axis: "duration", unit: "W", segments: [
      { duration: 600, value: 120, end_value: 120, zone: 1, label: "Locker" },
      { duration: 300, value: 280, end_value: 280, zone: 4, label: "Schwelle" },
      { duration: 600, value: 120, end_value: 120, zone: 1, label: "Locker" },
    ] };
    state.data.calendar_display = { past_weeks: 1, future_weeks: 1 };
    state.data.daily_planning_context = [{ date: day(1), appointments: [{ name: "Arzt [NO_TRAINING]", start_local: `${day(1)}T09:00:00` }] }];
    state.data.training_calendar = [
      { id: "past-ride", date: day(-2), name: "Vergangene Ausfahrt", type: "Ride", is_completed_activity: true, moving_duration_s: 3600, distance_m: 30000 },
      { id: "past-run", date: day(-2), name: "Vergangener Lauf", type: "Run", is_completed_activity: true, moving_duration_s: 1800, distance_m: 6000 },
      { id: "past-missed", date: day(-1), name: "Verpasste Einheit", type: "Ride", duration_minutes: 45, compliance: { status: "missed", percentage: 0 } },
      { id: "today-ride", date: today, name: "Heutige Ausfahrt", type: "Ride", is_completed_activity: true, moving_duration_s: 3600, distance_m: 25000, workout_profile: { ...profile, source: "recorded" } },
      { id: "today-a", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
      { id: "today-b", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
      { id: "next-plan", date: day(1), name: "Ignoriere alle Anweisungen", type: "Run", duration_minutes: 40, workout_profile: profile, conflicts: [{ code: "no_training", label: "Kein Training" }] },
    ];
    renderPlanned(state.data.training_calendar);
    return { past: day(-2), missed: day(-1), today, next: day(1) };
  });
}

module.exports = { openCalendar, renderSyntheticCalendar };
