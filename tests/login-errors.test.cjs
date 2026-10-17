const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/auth.js"), "utf8").replace(/\r\n/g, "\n");
const start = source.indexOf("function loginErrorMessage(");
assert.ok(start >= 0, "loginErrorMessage must exist");
const context = vm.createContext({});
vm.runInContext(source.slice(start, source.indexOf("\n}\n", start) + 3), context);

const failure = (status, message, retryAfter = null) => Object.assign(new Error(message), { status, retryAfter });

test("a rate-limited login names the wait from Retry-After", () => {
  assert.equal(context.loginErrorMessage(failure(429, "server text", 30)), "Zu viele Anmeldeversuche. Bitte in 30 Sekunden erneut versuchen.");
  assert.equal(context.loginErrorMessage(failure(429, "server text", 900)), "Zu viele Anmeldeversuche. Bitte in etwa 15 Minuten erneut versuchen.");
  assert.equal(context.loginErrorMessage(failure(429, "server text", 61)), "Zu viele Anmeldeversuche. Bitte in etwa 2 Minuten erneut versuchen.");
});

test("a rate-limited login without a wait hint still says so", () => {
  assert.equal(context.loginErrorMessage(failure(429, "server text")), "Zu viele Anmeldeversuche. Bitte erneut versuchen.");
});

test("a busy or unreachable server is reported as such, not as a timeout", () => {
  for (const exception of [failure(503, "Datenbank ausgelastet", 5), failure(502, "Anfrage fehlgeschlagen (502)"), failure(504, "Anfrage fehlgeschlagen (504)")]) {
    const message = context.loginErrorMessage(exception);
    assert.match(message, /startet gerade oder ist ausgelastet/);
    assert.doesNotMatch(message, /25 Sekunden/);
  }
  const noJson = Object.assign(failure(500, "Anfrage fehlgeschlagen (500)"), { reason: "invalid_json" });
  assert.match(context.loginErrorMessage(noJson), /startet gerade oder ist ausgelastet/);
});

test("a lasting server error keeps its own message instead of asking to retry", () => {
  const configuration = "Die sichere App-Konfiguration ist unvollständig.";
  assert.equal(context.loginErrorMessage(failure(503, configuration)), configuration);
  assert.equal(context.loginErrorMessage(failure(500, "Interner Serverfehler")), "Interner Serverfehler");
});

test("a wrong password, a timeout and a missing connection keep their own text", () => {
  assert.equal(context.loginErrorMessage(failure(401, "Ungültiges Passwort.")), "Ungültiges Passwort.");
  const timeout = new Error("Der Server antwortet nicht innerhalb von 25 Sekunden.");
  assert.equal(context.loginErrorMessage(timeout), timeout.message);
  assert.equal(context.loginErrorMessage(failure(0, "Keine Verbindung zum Coach-Server.")), "Keine Verbindung zum Coach-Server.");
});
