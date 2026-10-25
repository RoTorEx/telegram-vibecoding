/* No secrets or authorization flags are persisted in browser storage. */
"use strict";
const $ = (id) => document.getElementById(id);
const tg = window.Telegram?.WebApp;
const requestId = new URLSearchParams(location.search).get("request");
let bm;

async function api(method, data) {
  const response = await fetch("./api/" + method, {
    method: "POST", credentials: "omit", cache: "no-store",
    headers: {"Content-Type": "application/json", "X-Telegram-Init-Data": tg.initData},
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request rejected. Reopen the bot button.");
  return result;
}

function authenticate(reason) {
  return new Promise((resolve, reject) => bm.authenticate({reason}, (ok, token) => {
    if (ok && token) resolve(token);
    else reject(new Error("Biometric confirmation was cancelled or unavailable. Nothing was authorized."));
  }));
}

async function signature(secret, challenge) {
  if (!/^[a-f0-9]{64}$/.test(secret)) throw new Error("Device key is unavailable. Enroll through SSH.");
  const bytes = Uint8Array.from(secret.match(/../g), (x) => parseInt(x, 16));
  const key = await crypto.subtle.importKey("raw", bytes, {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
  bytes.fill(0);
  const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(challenge));
  return Array.from(new Uint8Array(signed), (x) => x.toString(16).padStart(2, "0")).join("");
}

async function decide(decision) {
  $("approve").disabled = $("cancel").disabled = true;
  try {
    const proof = await api("proof", {request: requestId, device: bm.deviceId, decision});
    let secret = await authenticate(decision === "approve" ? "Authorize only the agent request shown on this page" : "Reject this agent request");
    const signed = await signature(secret, proof.challenge);
    secret = "";
    const result = await api("confirm", {proof: proof.proof, signature: signed});
    $("actions").hidden = true;
    $("status").textContent = result.status === "approved" ? "Confirmed. The bot will process only this request. You can return to the chat." : "Rejected. This request will not run.";
  } catch (error) {
    $("status").textContent = error.message;
    $("approve").disabled = $("cancel").disabled = false;
  }
}

async function describe(action) {
  const payload = JSON.parse(action.payload);
  if (action.kind === "input") {
    const target = payload.context.target;
    $("target").textContent = target.name + "\n" + target.cwd + (target.session_id ? "\nSession: " + target.session_id : "\nCreate a new session");
    $("content").textContent = payload.rows.map((row) => {
      const message = JSON.parse(row.body).message;
      let text = message.text || message.caption || "";
      if (message.voice) text += "\n[Voice recording: " + message.voice.duration + " seconds; Telegram message " + message.message_id + "]";
      if (message.photo || message.document) text += "\n[Image attachment; Telegram message " + message.message_id + "]";
      return text;
    }).join("\n\n");
    const first = JSON.parse(payload.rows[0].body).message;
    if (payload.rows[0].mode === "chat" && first.text && payload.context.questions?.length) {
      const question = payload.context.questions[0];
      const previous = payload.context.answers[question.id] || {};
      const explanation = question.payload.questions.map((q) => q.question || q.header || q.title || "").join("\n");
      $("content").textContent = "In reply to:\n" + explanation + (Object.keys(previous).length ? "\nPrevious choices:\n" + JSON.stringify(previous, null, 2) : "") + "\n\nYour input:\n" + $("content").textContent;
    }
    for (let index = 0; index < payload.rows.length; index++) {
      const message = JSON.parse(payload.rows[index].body).message;
      if (!message.voice && !message.photo && !message.document) continue;
      const response = await fetch("./api/media", {
        method: "POST", credentials: "omit", cache: "no-store",
        headers: {"Content-Type": "application/json", "X-Telegram-Init-Data": tg.initData},
        body: JSON.stringify({request: action.id, index}),
      });
      if (!response.ok) throw new Error("Cannot preview this attachment. Nothing was authorized; reopen the bot button.");
      const media = document.createElement(message.voice ? "audio" : "img");
      media.src = URL.createObjectURL(await response.blob());
      if (message.voice) media.controls = true;
      else media.alt = "Image in this request";
      $("media").append(media);
    }
  } else {
    const target = payload.target || {};
    $("target").textContent = (payload.label || "Answer agent question") + (target.name ? "\n" + target.name : "") + (target.cwd ? "\n" + target.cwd : "") + (target.id ? "\nSession: " + target.id : "");
    if (action.kind === "answer") {
      $("content").textContent = payload.question.payload.questions.map((q) => q.question || q.header || q.title || "").join("\n") + "\n\nYour answer: " + payload.value;
    } else $("content").textContent = JSON.stringify(payload.body, null, 2);
  }
}

$("approve").onclick = () => decide("approve");
$("cancel").onclick = () => decide("cancel");
$("enrollment").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const granted = bm.isAccessGranted || await new Promise((resolve) => bm.requestAccess({reason: "Confirm individual agent requests on this phone"}, resolve));
    if (!granted) throw new Error("Biometric access was not granted. Enable it in Telegram settings.");
    const result = await api("enroll", {device: bm.deviceId, code: $("code").value.trim()});
    $("code").value = "";
    const saved = await new Promise((resolve) => bm.updateBiometricToken(result.secret, resolve));
    result.secret = "";
    if (!saved) throw new Error("The phone could not save its key. Revoke this device through SSH before enrolling again.");
    $("enrollment").hidden = true;
    $("status").textContent = "Phone enrolled. Each request still requires its own confirmation.";
    if (requestId) $("actions").hidden = false;
  } catch (error) { $("status").textContent = error.message; }
  finally { button.disabled = false; }
};

async function start() {
  if (!tg?.initData || !tg.BiometricManager || !crypto.subtle) throw new Error("Open this page from the bot on a supported Telegram phone, over trusted HTTPS.");
  tg.ready();
  tg.expand();
  bm = tg.BiometricManager;
  await new Promise((resolve) => bm.init(resolve));
  if (!bm.isBiometricAvailable) throw new Error("Biometrics are unavailable on this device. No password or account-only bypass is provided.");
  if (requestId) {
    const action = await api("view", {request: requestId});
    await describe(action);
    $("request").hidden = false;
    if (action.status !== "pending" || action.expires * 1000 <= Date.now()) throw new Error("This request has already been handled or expired. It cannot be confirmed again.");
    $("status").textContent = "Review this exact request, then confirm with biometrics.";
    $("actions").hidden = !bm.isBiometricTokenSaved;
  } else $("status").textContent = "Enroll a phone using a code obtained independently through SSH.";
  $("enrollment").hidden = bm.isBiometricTokenSaved;
  if (!requestId && bm.isBiometricTokenSaved) $("status").textContent = "This phone has a device key. Return to the chat and open a request confirmation button.";
}
start().catch((error) => { $("status").textContent = error.message; });
