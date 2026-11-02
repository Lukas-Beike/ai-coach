const { test, expect } = require("@playwright/test");

test("plan notes remain readable in the Coach receipt @responsive", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => {
    state.data.messages = [{
      id: 9123, role: "assistant", content: "Der Plan ist gespeichert.",
      coach_changes: { labels: ["Trainingsplan geändert"], undoable: false, undone_at: null,
        plan_check_notes: [
          { code: "run_spike", dates: ["2026-11-02"], severity: "warning" },
          { code: "back_to_back_hard", dates: ["2026-11-03", "2026-11-04"], severity: "notice" },
          { code: "calendar_load", dates: ["2026-11-05"], severity: "notice" },
        ] },
    }];
    renderMessages(state.data.messages, true);
  });
  const notes = page.locator(".message-plan-note");
  await expect(notes).toHaveCount(3);
  await expect(notes.first()).toContainText("Warnung: Laufsprung · 02.11.2026 · Beobachtungsstudie");
  await expect(notes.first()).toHaveClass(/is-warning/);
  await expect(notes.nth(1)).toContainText("Hinweis: Harte Tage in Folge");
  await expect(notes.nth(2)).toContainText("Hinweis: Kalender und Einheit");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  expect(overflow).toBe(false);
});
