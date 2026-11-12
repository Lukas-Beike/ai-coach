const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, FakeElement } = require("./frontend-harness.cjs");

const VOICE = ["VOICE_MIME_TYPES", "VOICE_MAX_DURATION_MS", "setVoiceStatus", "voiceIsRecording", "formatVoiceDuration", "stopVoiceCapture", "stopVoiceRecording", "transcribeVoice", "toggleVoiceInput"];

// A microphone and MediaRecorder that deliver one chunk of audio on stop. Every storage API is
// a spy, so any write of the recorded audio shows up in `stored`.
function voiceHarness({ secure = true, microphone = true, recorder = true, recordedBytes = 3 } = {}) {
  const log = [];
  const stored = [];
  const spy = (name) => ({ getItem: () => null, setItem: (key, value) => stored.push([name, key, value]), removeItem() {} });
  const nodes = { "#voiceStatus": new FakeElement("p"), "#messageInput": Object.assign(new FakeElement("textarea"), { dispatchEvent() {}, focus() {} }) };
  nodes["#voiceStatus"].classList.toggle = () => {};
  const track = { stop() { log.push("track stopped"); } };
  const state = { sessionGeneration: 0, voiceRecorder: null, voiceStream: null, voiceTimer: null, voiceAcquiring: false, voiceTranscribing: false };
  class FakeRecorder {
    constructor() { this.listeners = {}; this.state = "inactive"; this.mimeType = "audio/webm"; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      this.listeners.dataavailable({ data: new Blob([new Uint8Array(recordedBytes)]) });
      this.listeners.stop();
    }
  }
  const context = extractFunctions("coach.js", VOICE, {
    state, Blob, Event, Date,
    isSecureContext: secure,
    navigator: microphone ? { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track] }) } } : {},
    MediaRecorder: recorder ? Object.assign(FakeRecorder, { isTypeSupported: () => true }) : undefined,
    setInterval: () => 7, clearInterval() {},
    document: { visibilityState: "hidden" },
    localStorage: spy("localStorage"), sessionStorage: spy("sessionStorage"),
    indexedDB: { open: () => stored.push(["indexedDB"]) }, caches: { open: async () => stored.push(["caches"]) },
    $: (selector) => nodes[selector],
    toast: (message, isError) => log.push(["toast", message, Boolean(isError)]),
    updateVoiceButton() {},
    apiAudio: async (path, blob) => { log.push(["upload", path, blob.size, blob.type]); return { transcript: "Locker laufen" }; },
  });
  return { context, state, nodes, log, stored };
}

test("a browser without microphone support leaves voice off with a message and the app working", async () => {
  for (const options of [{ secure: false }, { microphone: false }, { recorder: false }]) {
    const { context, state, nodes, log } = voiceHarness(options);
    await context.toggleVoiceInput();
    const message = "Spracheingabe benötigt eine HTTPS-Verbindung und einen unterstützten Browser.";
    assert.deepEqual(log, [["toast", message, true]], JSON.stringify(options));
    assert.equal(nodes["#voiceStatus"].textContent, message);
    assert.deepEqual([state.voiceRecorder, state.voiceStream, state.voiceAcquiring], [null, null, false]);
  }
});

test("a recording is uploaded for transcription, edited in the draft, and never written to device storage", async () => {
  const { context, state, nodes, log, stored } = voiceHarness();
  await context.toggleVoiceInput();
  assert.equal(context.voiceIsRecording(), true);
  context.stopVoiceRecording();
  await new Promise((done) => setImmediate(done));
  assert.deepEqual(log.filter(([step]) => step === "upload"), [["upload", "/api/transcribe", 3, "audio/webm"]]);
  assert.equal(nodes["#messageInput"].value, "Locker laufen");
  assert.equal(nodes["#voiceStatus"].textContent, "Transkript eingefügt. Bitte prüfen und anschließend senden.");
  assert.deepEqual(stored, []);
  // The microphone is released and nothing of the recording stays in the client state.
  assert.ok(log.includes("track stopped"));
  assert.deepEqual([state.voiceRecorder, state.voiceStream, state.voiceTranscribing], [null, null, false]);
  assert.equal(Object.values(state).some((value) => value instanceof Blob), false);
});

test("an empty recording uploads nothing", async () => {
  const { context, nodes, log, stored } = voiceHarness({ recordedBytes: 0 });
  await context.toggleVoiceInput();
  context.stopVoiceRecording();
  assert.equal(log.some(([step]) => step === "upload"), false);
  assert.equal(nodes["#voiceStatus"].textContent, "Es wurde keine Sprache aufgenommen.");
  assert.deepEqual(stored, []);
});
