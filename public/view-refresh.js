globalThis.AppViewRefresh = (() => {
  function create({ api, waitForJob, getRoute, getRequest, getViewKey = () => null, reload, button, status }) {
    let running = false;
    const isCurrent = (route, requestKey) => getRoute() === route
      && JSON.stringify({ request: getRequest(route), viewKey: getViewKey(route) }) === requestKey;

    return async function refresh() {
      if (running) return;
      const route = getRoute();
      const request = getRequest(route);
      if (!request) return;
      const requestKey = JSON.stringify({ request, viewKey: getViewKey(route) });
      running = true;
      button.disabled = true;
      button.classList.add("busy");
      button.setAttribute("aria-busy", "true");
      status.textContent = "Aktualisierung läuft …";
      try {
        let result = await api(request.path, { method: "POST", body: JSON.stringify(request.body) });
        const jobId = result?.id || result?.job_id || result?.job?.id;
        if (jobId) result = await waitForJob(jobId);
        if (!isCurrent(route, requestKey)) return;

        const outcome = result?.status;
        if (outcome === "failed" || outcome === "error") {
          throw new Error(result.error_detail || result.message || "Aktualisierung fehlgeschlagen.");
        }
        if (["ok", "complete", "completed", "partial", "local"].includes(outcome)) {
          await reload(route, request);
          if (!isCurrent(route, requestKey)) return;
          status.textContent = outcome === "partial" ? "Teilweise aktualisiert." : outcome === "local" ? "Lokale Daten aktualisiert." : "Aktualisiert.";
          return;
        }
        if (outcome === "already_running") {
          status.textContent = "Aktualisierung läuft bereits.";
          return;
        }
        throw new Error("Der Aktualisierungsstatus ist unbekannt.");
      } catch (error) {
        if (isCurrent(route, requestKey)) status.textContent = `Aktualisierung fehlgeschlagen: ${error.message}`;
      } finally {
        if (!isCurrent(route, requestKey)) status.textContent = "";
        running = false;
        button.disabled = false;
        button.classList.remove("busy");
        button.removeAttribute("aria-busy");
      }
    };
  }

  return Object.freeze({ create });
})();
