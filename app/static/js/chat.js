(function () {
  const { conversationId, companionId } = window.CHAT_CONFIG;

  const messagesEl = document.getElementById("messages"); // outer scroll container
  const messagesInnerEl = document.getElementById("messages-inner"); // actual bubble list
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const micBtn = document.getElementById("mic-btn");
  const voiceSelect = document.getElementById("voice-select");
  const effectSelect = document.getElementById("effect-select");
  const languageSelect = document.getElementById("language-select");
  const previewBtn = document.getElementById("preview-voice-btn");
  const typingIndicator = document.getElementById("typing-indicator");
  const speakingIndicator = document.getElementById("speaking-indicator");

  const sidebarList = document.getElementById("sidebar-list");
  const sidebarSearch = document.getElementById("sidebar-search-input");
  const sidebarTabs = document.querySelectorAll(".sidebar-tab");
  const chatShell = document.getElementById("chat-shell");
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarBackdrop = document.getElementById("sidebar-backdrop");
  const jumpToLatest = document.getElementById("jump-to-latest");

  let mediaRecorder = null;
  let recordedChunks = [];
  let currentTab = "active";

  // ---------------- mobile sidebar drawer ----------------
  function closeSidebar() {
    chatShell.classList.remove("sidebar-open");
  }
  sidebarToggle.addEventListener("click", () => chatShell.classList.toggle("sidebar-open"));
  sidebarBackdrop.addEventListener("click", closeSidebar);

  // ---------------- scroll: auto-follow while near bottom, else offer a "jump to latest" pill ----------------
  function isNearBottom() {
    return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;
  }

  function scrollToBottom(force) {
    if (!force && !isNearBottom()) return;
    messagesEl.scrollTop = messagesEl.scrollHeight;
    jumpToLatest.classList.remove("show");
  }

  messagesEl.addEventListener("scroll", () => {
    if (isNearBottom()) jumpToLatest.classList.remove("show");
  });

  jumpToLatest.addEventListener("click", () => scrollToBottom(true));

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------- audio playback ----------------
  function attachAudioPlayer(slotEl, audioUrl, durationSeconds) {
    slotEl.innerHTML = "";
    const audio = new Audio(audioUrl);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "audio-btn";
    btn.textContent = "▶";
    const time = document.createElement("span");
    time.className = "audio-time";
    time.textContent = durationSeconds ? `${durationSeconds.toFixed(1)}s` : "";

    btn.addEventListener("click", () => {
      if (audio.paused) {
        audio.play();
      } else {
        audio.pause();
      }
    });
    audio.addEventListener("play", () => {
      btn.textContent = "⏸";
      speakingIndicator.classList.add("show");
    });
    audio.addEventListener("pause", () => {
      btn.textContent = "▶";
      speakingIndicator.classList.remove("show");
    });
    audio.addEventListener("ended", () => {
      btn.textContent = "▶";
      speakingIndicator.classList.remove("show");
    });

    slotEl.appendChild(btn);
    slotEl.appendChild(time);
    return audio;
  }

  async function synthesizeAndPlay(messageId, bubbleEl, existingSlot) {
    const slot = existingSlot || document.createElement("div");
    if (!existingSlot) {
      slot.className = "bubble-audio";
      bubbleEl.appendChild(slot);
    }
    slot.innerHTML = `<span class="audio-skip-note">Generating voice...</span>`;

    try {
      const res = await fetch(`/api/messages/${messageId}/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: messageId,
          voice_id: voiceSelect.value,
          tts_effect: effectSelect.value || null,
        }),
      });
      const data = await res.json();

      if (data.skipped) {
        slot.innerHTML = `<span class="audio-skip-note">${escapeHtml(data.reason || "No audio for this language.")}</span>`;
        return;
      }
      if (data.error) return;

      const audio = attachAudioPlayer(slot, data.audio_url, data.duration);
      audio.play().catch(() => {}); // autoplay may be blocked until first user gesture — that's fine, button still works
    } catch (err) {
      console.error("Speech synthesis failed", err);
    }
  }

  function addBubble(role, text, messageId) {
    const div = document.createElement("div");
    div.className = `bubble ${role}`;
    div.dataset.messageId = messageId || "";
    div.textContent = text;
    messagesInnerEl.appendChild(div);
    scrollToBottom(true);
    return div;
  }

  // ---------------- send / stream ----------------
  async function sendMessage(e) {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    sendBtn.disabled = true;
    typingIndicator.classList.add("show");

    addBubble("user", text);
    const assistantBubble = addBubble("assistant", "");
    assistantBubble.classList.add("streaming");

    try {
      const lang = languageSelect.value === "auto" ? null : languageSelect.value;
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, message: text, preferred_language: lang }),
      });

      if (!res.ok || !res.body) throw new Error(await res.text());

      const assistantMessageId = res.headers.get("X-Assistant-Message-Id");
      assistantBubble.dataset.messageId = assistantMessageId || "";

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let assembled = "";
      let firstChunk = true;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (firstChunk) {
          typingIndicator.classList.remove("show");
          firstChunk = false;
        }
        const chunk = decoder.decode(value, { stream: true });
        assembled += chunk;
        const wasNearBottom = isNearBottom();
        assistantBubble.firstChild
          ? (assistantBubble.childNodes[0].textContent = assembled)
          : (assistantBubble.textContent = assembled);
        if (wasNearBottom) {
          scrollToBottom(true);
        } else {
          jumpToLatest.classList.add("show");
        }
      }

      assistantBubble.classList.remove("streaming");

      if (assembled.trim() && assistantMessageId) {
        await synthesizeAndPlay(assistantMessageId, assistantBubble);
      }

      loadConversations(); // refresh sidebar (title/updated_at may have changed)
    } catch (err) {
      assistantBubble.classList.remove("streaming");
      assistantBubble.textContent = `[error: could not get a reply — ${err.message}]`;
    } finally {
      typingIndicator.classList.remove("show");
      sendBtn.disabled = false;
    }
  }

  form.addEventListener("submit", sendMessage);

  previewBtn.addEventListener("click", () => {
    const opt = voiceSelect.selectedOptions[0];
    if (!opt) return;
    const previewUrl = opt.dataset.preview;
    if (previewUrl) new Audio(previewUrl).play();
  });

  // ---------------- mic (record -> local Whisper STT) ----------------
  if (navigator.mediaDevices && window.MediaRecorder) {
    micBtn.addEventListener("click", async () => {
      if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => recordedChunks.push(e.data);
        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          micBtn.classList.remove("listening");
          micBtn.textContent = "⏳";
          const blob = new Blob(recordedChunks, { type: "audio/webm" });
          const formData = new FormData();
          formData.append("audio", blob, "recording.webm");
          try {
            const res = await fetch("/api/stt", { method: "POST", body: formData });
            const data = await res.json();
            if (data.text) input.value = input.value ? `${input.value} ${data.text}` : data.text;
          } catch (err) {
            console.error("Transcription failed", err);
          }
          micBtn.textContent = "🎤";
        };
        mediaRecorder.start();
        micBtn.classList.add("listening");
        micBtn.textContent = "● Listening...";
      } catch (err) {
        console.error("Mic access denied or unavailable", err);
      }
    });
  } else {
    micBtn.style.display = "none";
  }

  // ---------------- sidebar: history + search ----------------
  function renderConversationItem(c) {
    const active = c.id === conversationId;
    const el = document.createElement("div");
    el.className = `convo-item${active ? " active" : ""}`;
    el.innerHTML = `
      <div class="convo-title">${c.pinned ? '<span class="pin-mark">📌</span> ' : ""}${escapeHtml(c.title)}</div>
      <div class="convo-meta"><span>${escapeHtml(c.companion_name)}</span><span>${new Date(c.updated_at).toLocaleDateString()}</span></div>
      <div class="convo-actions">
        <button type="button" data-action="pin">${c.pinned ? "Unpin" : "Pin"}</button>
        <button type="button" data-action="rename">Rename</button>
        <button type="button" data-action="${c.archived ? "restore" : "archive"}">${c.archived ? "Restore" : "Archive"}</button>
        <button type="button" data-action="export">Export</button>
        <button type="button" data-action="delete">Delete</button>
      </div>
    `;
    el.addEventListener("click", (e) => {
      if (e.target.dataset.action) return;
      window.location.href = `/chat/conversation/${c.id}`;
    });

    el.querySelector('[data-action="pin"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/conversations/${c.id}/pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: !c.pinned }),
      });
      loadConversations();
    });

    el.querySelector('[data-action="rename"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const title = prompt("Rename conversation:", c.title);
      if (title === null) return;
      await fetch(`/api/conversations/${c.id}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      loadConversations();
    });

    el.querySelector('[data-action$="archive"], [data-action="restore"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/conversations/${c.id}/archive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: !c.archived }),
      });
      loadConversations();
    });

    el.querySelector('[data-action="export"]').addEventListener("click", (e) => {
      e.stopPropagation();
      window.location.href = `/api/conversations/${c.id}/export`;
    });

    el.querySelector('[data-action="delete"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this conversation permanently?")) return;
      await fetch(`/api/conversations/${c.id}`, { method: "DELETE" });
      loadConversations();
      if (c.id === conversationId) window.location.href = `/chat/${companionId}`;
    });

    return el;
  }

  async function loadConversations() {
    const res = await fetch(`/api/conversations?archived=${currentTab === "archived"}`);
    const items = await res.json();
    sidebarList.innerHTML = "";
    if (items.length === 0) {
      sidebarList.innerHTML = `<p class="empty-hint">No conversations here yet.</p>`;
      return;
    }
    items.forEach((c) => sidebarList.appendChild(renderConversationItem(c)));
  }

  async function runSearch(query) {
    if (!query.trim()) {
      loadConversations();
      return;
    }
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const results = await res.json();
    sidebarList.innerHTML = "";
    if (results.length === 0) {
      sidebarList.innerHTML = `<p class="empty-hint">No matches.</p>`;
      return;
    }
    const q = query.toLowerCase();
    results.forEach((r) => {
      const el = document.createElement("a");
      el.className = "convo-item";
      el.href = `/chat/conversation/${r.conversation_id}`;
      const idx = r.snippet.toLowerCase().indexOf(q);
      const highlighted =
        idx === -1
          ? escapeHtml(r.snippet)
          : escapeHtml(r.snippet.slice(0, idx)) +
            `<mark>${escapeHtml(r.snippet.slice(idx, idx + query.length))}</mark>` +
            escapeHtml(r.snippet.slice(idx + query.length));
      el.innerHTML = `
        <div class="convo-title">${escapeHtml(r.title)}</div>
        <div class="convo-meta" style="white-space:normal;">${highlighted}</div>
      `;
      sidebarList.appendChild(el);
    });
  }

  let searchTimer = null;
  sidebarSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(sidebarSearch.value), 250);
  });

  sidebarTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      sidebarTabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      currentTab = tab.dataset.tab;
      sidebarSearch.value = "";
      loadConversations();
    });
  });

  // historical assistant bubbles rendered on page load: wire up their "play voice" buttons
  // (not auto-generated/played — only the live just-streamed reply auto-plays, to avoid
  // every old message in a reopened chat blasting audio at once)
  document.querySelectorAll(".bubble.assistant[data-message-id]").forEach((bubble) => {
    const btn = bubble.querySelector("[data-play-historical]");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const slot = bubble.querySelector("[data-audio-slot]");
      synthesizeAndPlay(bubble.dataset.messageId, bubble, slot);
    });
  });

  loadConversations();
})();
