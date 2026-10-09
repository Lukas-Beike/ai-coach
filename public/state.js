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
    chatResponseStarted: false,
    chatResponseScrollPending: false,
    chatResponseMessageId: null,
    chatProposalRefreshPending: false,
    chatProposalRefreshInFlight: false,
    chatProposalRefreshQueued: false,
    chatInitialScrollPending: true,
    chatScrollY: null,
    chatScrollRestoring: false,
    stateEventSource: null,
    stateEventReconnectTimer: null,
    stateEventRefreshTimer: null,
    stateEventRefreshAreas: new Set(),
    stateEventLastId: 0,
    stateEventBackoff: 1000,
    coachActionProposals: [],
    coachReceipts: [],
    chatQueue: [],
    chatQueueSequence: 0,
    profileDirty: false,
    checkinDirty: false,
    chatDraftDirty: false,
    checkinSelectedDate: null,
    planSegment: "overview",
    plannedTodayFocusPending: false,
    loadedAreas: new Set(),
    voiceRecorder: null,
    voiceStream: null,
    voiceTimer: null,
    voiceStartedAt: 0,
    voiceTranscribing: false,
    voiceAcquiring: false,
    localSync: { intervals: false, competitions: false, garmin: false, externalCalendar: false, weather: false, performance: false, intervalsFull: false, garminFull: false },
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
