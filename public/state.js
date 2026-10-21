globalThis.AppState = (() => {
  function secureToken(prefix) {
    const cryptoApi = globalThis.crypto;
    if (typeof cryptoApi?.randomUUID === "function") return `${prefix}-${cryptoApi.randomUUID()}`;
    if (typeof cryptoApi?.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      cryptoApi.getRandomValues(bytes);
      return `${prefix}-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
    }
    throw new Error("Secure random generator unavailable");
  }

  const state = {
    data: null,
    route: null,
    initialStateLoaded: false,
    loadSequence: 0,
    loadPromise: null,
    pendingLoads: new Map(),
    loadingAreas: new Set(),
    // Server versions a background reload was requested for, until that load settles.
    requestedStateVersions: {},
    // Background reloads waiting for a running Coach turn to finish.
    deferredLoad: null,
    replaceDataOnLoad: false,
    sessionGeneration: 0,
    chatGeneration: 0,
    chatContentVersion: 0,
    rejectedMessages: [],
    busy: false,
    chatStream: null,
    chatStreamText: "",
    chatRequest: null,
    chatServerOperationId: null,
    chatStatusTimer: null,
    chatStatusPollInFlight: null,
    chatStatusRecheck: false,
    // The last Coach event ended a turn, so a "running" status may still be closing.
    chatStatusTurnEnded: false,
    chatResponseStarted: false,
    chatResponseScrollPending: false,
    chatResponseMessageId: null,
    chatProposalRefreshPending: false,
    chatProposalRefreshInFlight: false,
    chatProposalRefreshQueued: false,
    chatInitialScrollPending: true,
    // The Coach shows messages from the device cache until the fresh chat load ends.
    chatCacheSyncing: false,
    chatScrollY: null,
    chatScrollRestoring: false,
    chatFollowLatest: true,
    chatUnseenContent: false,
    stateEventSource: null,
    stateEventReconnectTimer: null,
    stateEventRefreshTimer: null,
    stateEventRefreshAreas: new Set(),
    stateEventLastId: 0,
    stateEventBackoff: 1000,
    // The stream announced itself ("ready") and was heard from recently.
    stateEventReady: false,
    stateEventActivityAt: 0,
    // True once a stream has caught up with the server, so a later reconnect replays real changes.
    stateEventBaselined: false,
    coachActionProposals: [],
    coachActionUnknownIds: new Set(),
    coachReceipts: [],
    chatQueue: [],
    chatQueueSequence: 0,
    profileDirty: false,
    profileBaseline: null,
    chatDraftDirty: false,
    planSegment: "overview",
    plannedTodayFocusPending: false,
    loadedAreas: new Set(),
    voiceRecorder: null,
    voiceStream: null,
    voiceTimer: null,
    voiceStartedAt: 0,
    voiceTranscribing: false,
    voiceAcquiring: false,
    localSync: { intervals: false, competitions: false, garmin: false, externalCalendar: false, weather: false, performance: false, intervalsFull: false, garminFull: false, wahoo: false, wahooFull: false },
    notificationKeys: new Set(),
    quickTemplatesVisible: false,
    activityTracked: false,
    syncPoll: {
      controller: null,
      timer: null,
      operationId: null,
      channel: null,
      leaseToken: secureToken("tab"),
    },
  };

  function setField(key, value) {
    if (!Object.hasOwn(state, key)) throw new Error(`Unknown state key: ${key}`);
    state[key] = value;
    return value;
  }

  function setRoute(route) {
    return setField("route", route);
  }

  function setPlanSegment(segment) {
    return setField("planSegment", segment);
  }

  return Object.freeze({ state, secureToken, setRoute, setPlanSegment });
})();

const state = AppState.state;
