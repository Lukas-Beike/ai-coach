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
const { renderAdaptivePlanning, renderExternalCalendar, renderTrainingPlans, renderPlanned, renderLibrary, renderCompetitions, focusPlannedToday, bindPlanNavigation, bindExternalCalendar } = AppPlanViews.create({ $, state, dateLabel, formatTime, formatDuration, formatPace, formatWhole, distanceLabel, activitySportLabel, analysisSvg, api, showAccessibleDialog, appendHistoryPageButton, AppRouter, dateFromKey, localDateKey, addDateKey, weatherNumber, weatherIconFor, weatherDirection, plannedEventDate, timezoneDateKey, calendarDisplayValue, openCheckinEditor, checkinSummary });
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
installLoginDialogGuards();
setupCoachEvents();
$("#appearanceSelect").addEventListener("change", (event) => {
  const appearance = applyAppearance(event.currentTarget.value);
  try { localStorage.setItem(APPEARANCE_KEY, appearance); } catch { }
});
$("#setupBannerDismiss").addEventListener("click", dismissSetupBanner);
// Setup links lead to the collapsed Anbindungen section; open it so the hints are visible.
document.addEventListener("click", (event) => {
  if (!event.target.closest?.('a[href="#more/connections"]')) return;
  const section = document.querySelector('details[data-more-segment-panel="connections"]');
  if (section) section.open = true;
});
$("#systemIntervalsSyncButton").addEventListener("click", syncNow);
$("#systemIntervalsFullResyncButton").addEventListener("click", () => fullResync("intervals"));
$("#garminSyncButton").addEventListener("click", syncGarmin);
bindExternalCalendar(syncExternalCalendar);
$("#weatherSyncButton").addEventListener("click", syncWeather);
$("#garminFullResyncButton").addEventListener("click", () => fullResync("garmin"));
$("#profileForm").addEventListener("submit", saveProfile);
$("#checkinForm").addEventListener("submit", saveCheckin);
$("#checkinCloseButton").addEventListener("click", () => $("#checkinDialog")?.close());
$("#profileCheckinButton").addEventListener("click", () => openCheckinEditor());
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true); });
$("#checkinForm").addEventListener("input", () => { state.checkinDirty = true; setDirtyIndicator("checkinDirtyIndicator", true); });
$("#modelSelect").addEventListener("change", saveModel);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#diagnosticsDeleteButton")?.addEventListener("click", deleteDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#logsDownloadButton").addEventListener("click", downloadServerLogs);
$("#logsDeleteButton")?.addEventListener("click", deleteServerLogs);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#changeHistoryRefreshButton").addEventListener("click", loadChangeHistory);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", () => { downloadDatabaseBackup().catch((error) => toast(error.message, true)); });
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") savePwaActivity();
  else {
    checkPwaReturn();
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
