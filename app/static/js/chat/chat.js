// Chat page entry point: wires the modules together and owns the send/stop/regenerate flow.
import { initConversations } from "./conversations.js";
import { initScroll, initSidebarDrawer } from "./sidebar.js";
import { cancelReply, streamReply } from "./streaming.js";
import { initMic } from "./stt.js";
import { createVoice, playVoicePreview } from "./voice.js";

const { conversationId, companionId } = window.CHAT_CONFIG;
const $ = (id) => document.getElementById(id);

const messagesEl = $("messages");
const messagesInnerEl = $("messages-inner");
const form = $("chat-form");
const input = $("chat-input");
const sendBtn = $("send-btn");
const stopBtn = $("stop-btn");
const micBtn = $("mic-btn");
const voiceSelect = $("voice-select");
const effectSelect = $("effect-select");
const languageSelect = $("language-select");
const typingIndicator = $("typing-indicator");
const speakingIndicator = $("speaking-indicator");
const replyActions = $("reply-actions");
const regenerateBtn = $("regenerate-btn");

initSidebarDrawer({ chatShell: $("chat-shell"), toggle: $("sidebar-toggle"), backdrop: $("sidebar-backdrop") });
const scroll = initScroll({ messagesEl, jumpToLatest: $("jump-to-latest") });
const voice = createVoice({ voiceSelect, effectSelect, speakingIndicator });
const conversations = initConversations({
  listEl: $("sidebar-list"),
  searchInput: $("sidebar-search-input"),
  tabs: document.querySelectorAll(".sidebar-tab"),
  conversationId,
  companionId,
});
initMic(micBtn, input);

let active = null; // { controller, messageId } while a reply is streaming

function preferredLanguage() {
  return languageSelect.value === "auto" ? null : languageSelect.value;
}

function setBusy(busy) {
  sendBtn.hidden = busy;
  stopBtn.hidden = !busy;
  micBtn.disabled = busy;
  typingIndicator.classList.toggle("show", busy);
  if (busy) replyActions.hidden = true;
}

function addBubble(role, text, messageId) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.dataset.messageId = messageId || "";
  const textEl = document.createElement("span");
  textEl.className = "bubble-text";
  textEl.textContent = text;
  div.appendChild(textEl);
  messagesInnerEl.appendChild(div);
  scroll.scrollToBottom(true);
  return div;
}

function markBubble(bubble, status, note) {
  bubble.dataset.status = status;
  bubble.classList.toggle("failed", status === "failed");
  bubble.querySelector(".bubble-note")?.remove();
  if (note) {
    const noteEl = document.createElement("div");
    noteEl.className = "bubble-note";
    noteEl.setAttribute("role", status === "failed" ? "alert" : "status");
    noteEl.textContent = note;
    bubble.appendChild(noteEl);
  }
}

// Offer Retry (after a failure) or Regenerate (after a finished reply) for the latest reply.
function updateReplyActions() {
  const last = messagesInnerEl.lastElementChild;
  const show = !active && last && last.classList.contains("assistant");
  replyActions.hidden = !show;
  if (show) regenerateBtn.textContent = last.dataset.status === "failed" ? "↻ Retry" : "↻ Regenerate";
}

async function runReply(url, body, bubble) {
  const controller = new AbortController();
  active = { controller, messageId: null };
  setBusy(true);
  bubble.classList.add("streaming");
  const textEl = bubble.querySelector(".bubble-text");
  let assembled = "";

  const outcome = await streamReply(url, body, {
    signal: controller.signal,
    onStart: (event) => {
      active.messageId = event.message_id;
      bubble.dataset.messageId = event.message_id;
    },
    onDelta: (text) => {
      typingIndicator.classList.remove("show");
      const wasNearBottom = scroll.isNearBottom();
      assembled += text;
      textEl.textContent = assembled;
      scroll.follow(wasNearBottom);
    },
  });

  bubble.classList.remove("streaming");
  if (outcome.messageId) bubble.dataset.messageId = outcome.messageId;
  active = null;
  setBusy(false);

  if (outcome.status === "completed") {
    markBubble(bubble, "completed");
    if (assembled.trim()) voice.synthesizeAndPlay(bubble.dataset.messageId, bubble);
  } else if (outcome.status === "cancelled") {
    markBubble(bubble, "cancelled", assembled.trim() ? "Stopped." : "Stopped before replying.");
  } else {
    markBubble(bubble, "failed", outcome.error || "Couldn't get a reply.");
  }
  updateReplyActions();
  conversations.load(); // title/updated_at may have changed
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (active) return;
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addBubble("user", text);
  const bubble = addBubble("assistant", "");
  runReply("/api/chat", { conversation_id: conversationId, message: text, preferred_language: preferredLanguage() }, bubble);
});

stopBtn.addEventListener("click", () => {
  if (!active) return;
  cancelReply(active.messageId);
  active.controller.abort();
});

regenerateBtn.addEventListener("click", () => {
  if (active) return;
  const last = messagesInnerEl.lastElementChild;
  if (last && last.classList.contains("assistant")) last.remove();
  const bubble = addBubble("assistant", "");
  runReply("/api/chat/regenerate", { conversation_id: conversationId, preferred_language: preferredLanguage() }, bubble);
});

$("preview-voice-btn").addEventListener("click", (e) => {
  if (voiceSelect.value) playVoicePreview(voiceSelect.value, e.currentTarget);
});

// Historical replies: voice is generated on demand only — reopening a chat must not
// make every old message start talking at once.
document.querySelectorAll(".bubble.assistant[data-message-id]").forEach((bubble) => {
  const btn = bubble.querySelector("[data-play-historical]");
  if (!btn) return;
  btn.addEventListener("click", () => {
    voice.synthesizeAndPlay(bubble.dataset.messageId, bubble, bubble.querySelector("[data-audio-slot]"));
  });
});

updateReplyActions();
scroll.scrollToBottom(true);
conversations.load();
