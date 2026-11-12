const confirmationDialog = $("#confirmationDialog");
const confirmationForm = $("#confirmationDialogForm");
const confirmationInput = $("#confirmationDialogInput");
confirmationForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const expectedText = confirmationDialog?.dataset.expectedText || "";
  if (expectedText && confirmationInput?.value !== expectedText) {
    confirmationInput?.setCustomValidity("Bestätigungstext stimmt nicht überein.");
    confirmationInput?.reportValidity();
    confirmationInput?.focus();
    return;
  }
  confirmationInput?.setCustomValidity("");
  settleConfirmation(expectedText ? confirmationInput.value : true);
  confirmationDialog?.close();
});
$("#confirmationDialogCancel")?.addEventListener("click", () => {
  settleConfirmation(false);
  confirmationDialog?.close();
});
confirmationDialog?.addEventListener("close", () => settleConfirmation(false));

document.querySelectorAll(".nav-item").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const linkedRoute = String(link.getAttribute("href") || "").replace(/^#/, "").trim();
  void AppRouter.navigate(linkedRoute || link.dataset.route, { historyMode: "push" });
}));
const { renderAdaptivePlanning, renderExternalCalendar, renderPlanned, renderLibrary, renderCompetitions, renderCompetitionReadStatus, focusPlannedToday, bindPlanNavigation, bindExternalCalendar } = AppPlanViews.create({ $, state, dateLabel, formatTime, formatDuration, formatPace, formatWhole, distanceLabel, activitySportLabel, svgNode, api, showAccessibleDialog, appendHistoryPageButton, AppRouter, dateFromKey, localDateKey, addDateKey, weatherNumber, weatherIconFor, weatherDirection, plannedEventDate, timezoneDateKey, calendarDisplayValue });
bindPlanNavigation();
document.querySelectorAll("[data-analysis-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate(`analysis/${link.dataset.analysisSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-more-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate(`more/${link.dataset.moreSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", () => restoreDialogFocus(dialog)));

$("#loginForm").addEventListener("submit", login);
$("#loginPasswordToggle").addEventListener("click", toggleLoginPassword);
installLoginDialogGuards();
setupCoachEvents();
$("#appearanceSelect").addEventListener("change", (event) => {
  const appearance = applyAppearance(event.currentTarget.value);
  try { localStorage.setItem(APPEARANCE_KEY, appearance); } catch { }
});
// A setup link that names a provider opens that provider's card.
document.addEventListener("click", (event) => {
  const link = event.target.closest?.('a[href="#more/connections"][data-connection]');
  if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate("more/connections", { historyMode: "push" }).then((shown) => { if (shown) openConnectionCard(link.dataset.connection); });
});
$("#garminSyncButton").addEventListener("click", syncGarmin);
bindExternalCalendar(syncExternalCalendar);
bindPlanRefresh();
$("#weatherSyncButton").addEventListener("click", syncWeather);
$("#yazioCheckButton").addEventListener("click", checkYazioConnection);
bindProviderChecks();
$("#wahooConnectButton").addEventListener("click", connectWahoo);
$("#wahooDisconnectButton").addEventListener("click", disconnectWahoo);
$("#wahooSyncButton").addEventListener("click", syncWahoo);
$("#wahooFullResyncButton").addEventListener("click", () => fullResync(providerIds().wahoo));
for (const provider of Object.keys(CREDENTIAL_FORMS)) {
  $("#" + credentialFormIds(provider).form).addEventListener("submit", (event) => saveProviderCredentials(event, provider));
  $("#" + credentialFormIds(provider).form).addEventListener("input", () => syncCredentialPasswordRow(provider));
  for (const field of CREDENTIAL_FORMS[provider]) {
    $("#" + credentialFieldIds(field).clear).addEventListener("click", () => clearProviderCredential(field, provider));
  }
}
$("#garmin-login-form").addEventListener("submit", submitGarminLogin);
$("#garmin-mfa-form").addEventListener("submit", submitGarminMfa);
$("#garmin-mfa-cancel").addEventListener("click", cancelGarminMfa);
$("#garmin-disconnect").addEventListener("click", disconnectGarmin);
$("#garmin-metric-export-toggle").addEventListener("click", (event) => toggleMetricExport(event.currentTarget));
$("#garminFullResyncButton").addEventListener("click", () => fullResync(providerIds().garmin));
$("#profileForm").addEventListener("submit", saveProfile);
$("#firstThresholdAdopt").addEventListener("click", adoptFirstThreshold);
$("#retryBodyGarmin").addEventListener("click", retryBodyGarmin);
// The zone editor sits inside the profile section list but saves its own form (#2262).
$("#profileForm").addEventListener("input", (event) => {
  if (event.target.form !== event.currentTarget) return;
  state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true);
});
// A closed profile section or a closed editor in it cannot show its invalid field: open them first.
$("#profileForm").addEventListener("invalid", (event) => {
  event.target.closest?.("details")?.setAttribute("open", "");
  const editor = event.target.closest?.(".zone-editor[hidden]");
  if (editor) editor.hidden = false;
}, true);
$("#modelSelect").addEventListener("change", (event) => saveSelectSetting(event, "model", "model", "Aktiv"));
$("#serviceTierSelect").addEventListener("change", (event) => saveSelectSetting(event, "service-tier", "service_tier", "Geschwindigkeit"));
$("#thinkingLevelSelect").addEventListener("change", (event) => saveSelectSetting(event, "thinking-level", "thinking_level", "Thinking Level"));
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#zoneSettings").addEventListener("toggle", (event) => { if (event.currentTarget.open) void loadZones(); });
$("#zoneEnvironment").addEventListener("change", renderZoneEditor);
$("#zoneSportTabs").addEventListener("click", (event) => { const sport = event.target.closest("[data-zone-sport]")?.dataset.zoneSport; if (sport) showZoneSport(sport); });
$("#zoneOverview").addEventListener("click", (event) => {
  const edit = event.target.closest("[data-zone-edit]");
  if (edit) openZoneEditor(edit);
});
$("#zoneFromBeginning").addEventListener("change", toggleZoneFromBeginning);
$("#zoneForm").addEventListener("submit", saveZones);
$("#zoneRemoveButton").addEventListener("click", removeZones);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#diagnosticsDeleteButton")?.addEventListener("click", deleteDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#logsDownloadButton").addEventListener("click", downloadServerLogs);
$("#logsDeleteButton")?.addEventListener("click", deleteServerLogs);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#privacySection").addEventListener("toggle", (event) => { if (event.currentTarget.open) void loadGpsTracks(); });
$("#gpsTracksToggle").addEventListener("change", saveGpsTracks);
$("#gpsTracksDeleteButton").addEventListener("click", deleteGpsTracks);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", () => { downloadDatabaseBackup().catch((error) => toast(error.message, true)); });
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    savePwaActivity();
    saveStateSnapshot();
    stopChatStatusPoll();
  } else {
    checkPwaReturn();
    // One check on return catches a Coach job started while this tab was hidden.
    scheduleChatStatusPoll(0);
    scheduleMobileViewportLayout();
  }
  handleSyncVisibility();
});
document.addEventListener("pointerdown", handlePwaInteraction, { passive: true });
document.addEventListener("focusin", scheduleMobileViewportLayout);
document.addEventListener("focusout", scheduleMobileViewportLayout);
globalThis.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("orientationchange", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("pageshow", () => {
  connectStateEvents();
  scheduleMobileViewportLayout();
  if (state.chatInitialScrollPending && AppRouter.baseRoute() === "coach") scrollChatToLatest();
}, { passive: true });
globalThis.visualViewport?.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
globalThis.visualViewport?.addEventListener("scroll", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("pagehide", savePwaActivity);
globalThis.addEventListener("pagehide", saveStateSnapshot);
globalThis.addEventListener("pagehide", disconnectStateEvents);
globalThis.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedChanges()) return;
  event.preventDefault();
});
registerServiceWorker();
setupConnectivityStatus();
renderNotificationStatus();
setupSyncStatusMonitoring();
scheduleMobileViewportLayout();
AppRouter.configure({
  hasUnsavedChanges,
  confirmDiscardChanges,
  discardUnsavedChanges,
  renderActiveRoute,
  renderStatus,
  restoreRouteScroll,
  ensureRouteData,
});
void AppRouter.syncFromHash();
void bootstrapAuth();

$("#competitionRetry").addEventListener("click", () => load("/api/bootstrap?local=1", ["profile"]));
