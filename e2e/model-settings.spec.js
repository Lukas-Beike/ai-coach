const { test, expect } = require("@playwright/test");

test("model and speed selection persist with capability checks @responsive", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => AppRouter.navigate("more/coach", { historyMode: "replace" }));
  await page.locator("#modelSettingsTarget").evaluate(el => el.closest("details").open = true);
  const model = page.locator("#modelSelect");
  const speed = page.locator("#serviceTierSelect");
  await expect(model).toHaveValue("gpt-6-luna");
  await expect(speed).toHaveValue("fast");
  await expect(page.locator("#thinkingLevelSelect")).toHaveValue("medium");
  await expect(speed.locator("option")).toHaveCount(2);
  await model.selectOption("gpt-6.1-sol");
  await expect(model).toBeEnabled();
  await expect(speed.locator("option")).toHaveCount(3);
  await speed.selectOption("ultrafast");
  await expect(speed).toBeEnabled();
  await page.reload();
  await page.locator("#modelSettingsTarget").evaluate(el => el.closest("details").open = true);
  await expect(model).toHaveValue("gpt-6.1-sol");
  await expect(speed).toHaveValue("ultrafast");
  await model.selectOption("gpt-6-luna");
  await expect(speed).toHaveValue("fast");
  await expect(speed.locator("option")).toHaveCount(2);
});

test("each task names its rejected model and a keyless planning model locks only its quick actions @responsive", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => {
    const options = [
      { id: "gpt-6-luna", label: "GPT-6 Luna", provider: "openai" },
      { id: "claude-opus", label: "Opus", provider: "anthropic", model: "claude-opus-5-5", rejected: "claude-opus-5-6" },
    ];
    state.data.model = { ...state.data.model, selected: "gpt-6-luna", options, tasks: {
      conversation: { model: "gpt-6-luna", thinking_level: "medium", ready: true },
      planning: { model: "claude-opus", thinking_level: "medium", ready: false },
      nutrition: { model: "gpt-6-luna", thinking_level: "medium", ready: true },
    } };
    renderModel(state.data.model);
    updateChatControls();
  });
  await expect(page.locator("#planningModelNotice")).toHaveText("claude-opus-5-6 abgelehnt – Coach nutzt claude-opus-5-5.");
  await expect(page.locator("#modelNotice")).toBeHidden();
  await expect(page.locator("#nutritionModelNotice")).toBeHidden();
  await expect(page.locator("#quickAnalysisButton")).toBeDisabled();
  // The copies in the composer's "+" menu are locked as well.
  await expect(page.locator('#composerPlusMenu [data-request-kind="plan_week"]')).toBeDisabled();
  await expect(page.locator("#quickMorningCheckinButton")).toBeEnabled();
  await page.locator("#messageInput").fill("Wie war mein Schlaf?");
  await expect(page.locator("#sendButton")).toBeEnabled();
});

test("each task block names in an info popover when its model is used @responsive", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.evaluate(() => AppRouter.navigate("more/coach", { historyMode: "replace" }));
  await page.locator("#modelSettingsTarget").evaluate((el) => { el.closest("details").open = true; });
  const pair = page.locator(".task-model-pair").first();
  await expect(page.locator("#modelSelect")).toHaveValue("gpt-6-luna");
  const offset = () => pair.evaluate((node) => [node.offsetTop, node.offsetHeight]);
  const before = await offset();
  for (const [task, text] of [
    ["Conversation", "auch den Morgen-Check-in, und für „Besprechen“, „Lösen“ und „Strukturieren“ im Kalender"],
    ["Planning", "„Analyse & Plan“ und im „+“-Menü sowie „Mit dem Coach analysieren“ im Kalender"],
    ["Nutrition", "„Nährwerttabelle fotografieren“ und die Websuche nach fehlenden Nährwerten"],
  ]) {
    const button = page.locator(`[popovertarget="modelInfo${task}"]`);
    const info = page.locator(`#modelInfo${task}`);
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(info).toBeVisible();
    await expect(info).toContainText(text);
    await expect(button).toHaveAttribute("aria-expanded", "true");
    if (task === "Planning") await page.screenshot({ path: testInfo.outputPath("model-info-planning.png") });
    await page.keyboard.press("Escape");
    await expect(info).toBeHidden();
  }
  // The info buttons do not move the model and thinking pair.
  expect(await offset()).toEqual(before);
});
