// Sidebar conversation list: load, search, tabs, and per-conversation actions.
export function initConversations({ listEl, searchInput, tabs, conversationId, companionId }) {
  let currentTab = "active";
  const escapeHtml = window.escapeHtml;

  async function action(url, options, failure) {
    try {
      const res = await fetch(url, options);
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, failure));
      return true;
    } catch (err) {
      if (window.showToast) window.showToast(err.message || failure, "error");
      return false;
    }
  }

  const postJson = (body) => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  function renderConversationItem(c) {
    const active = c.id === conversationId;
    const el = document.createElement("div");
    el.className = `convo-item${active ? " active" : ""}`;
    el.tabIndex = 0;
    el.setAttribute("role", "link");
    el.innerHTML = `
      <div class="convo-title">${c.pinned ? '<span class="pin-mark">📌</span> ' : ""}${escapeHtml(c.title)}</div>
      <div class="convo-meta"><span>${escapeHtml(c.companion_name)}</span><span>${new Date(c.updated_at).toLocaleDateString()}</span></div>
      <div class="convo-actions">
        <button type="button" data-action="pin">${c.pinned ? "Unpin" : "Pin"}</button>
        <button type="button" data-action="rename">Rename</button>
        <button type="button" data-action="archive">${c.archived ? "Restore" : "Archive"}</button>
        <button type="button" data-action="export">Export</button>
        <button type="button" data-action="delete">Delete</button>
      </div>
    `;
    const open = () => (window.location.href = `/chat/conversation/${c.id}`);
    el.addEventListener("click", (e) => {
      if (!e.target.dataset.action) open();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target === el) open();
    });

    const on = (name, handler) =>
      el.querySelector(`[data-action="${name}"]`).addEventListener("click", async (e) => {
        e.stopPropagation();
        await handler();
      });

    on("pin", async () => {
      if (await action(`/api/conversations/${c.id}/pin`, postJson({ value: !c.pinned }), "Couldn't pin.")) load();
    });
    on("rename", async () => {
      const title = prompt("Rename conversation:", c.title);
      if (title === null || !title.trim()) return;
      if (await action(`/api/conversations/${c.id}/rename`, postJson({ title: title.trim() }), "Couldn't rename."))
        load();
    });
    on("archive", async () => {
      if (await action(`/api/conversations/${c.id}/archive`, postJson({ value: !c.archived }), "Couldn't update."))
        load();
    });
    on("export", async () => {
      window.location.href = `/api/conversations/${c.id}/export`;
    });
    on("delete", async () => {
      if (!confirm("Delete this conversation and its voice messages permanently?")) return;
      if (!(await action(`/api/conversations/${c.id}`, { method: "DELETE" }, "Couldn't delete."))) return;
      if (c.id === conversationId) window.location.href = `/chat/${companionId}`;
      else load();
    });
    return el;
  }

  function showHint(text) {
    listEl.innerHTML = `<p class="empty-hint">${escapeHtml(text)}</p>`;
  }

  async function load() {
    try {
      const res = await fetch(`/api/conversations?archived=${currentTab === "archived"}`);
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Couldn't load conversations."));
      const items = await res.json();
      listEl.innerHTML = "";
      if (items.length === 0) return showHint("No conversations here yet.");
      items.forEach((c) => listEl.appendChild(renderConversationItem(c)));
    } catch (err) {
      showHint(err.message);
    }
  }

  async function runSearch(query) {
    if (!query.trim()) return load();
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Search failed."));
      const results = await res.json();
      listEl.innerHTML = "";
      if (results.length === 0) return showHint("No matches.");
      const q = query.toLowerCase();
      results.forEach((r) => {
        const el = document.createElement("a");
        el.className = "convo-item";
        el.href = `/chat/conversation/${encodeURIComponent(r.conversation_id)}`;
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
        listEl.appendChild(el);
      });
    } catch (err) {
      showHint(err.message);
    }
  }

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(searchInput.value), 250);
  });

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      currentTab = tab.dataset.tab;
      searchInput.value = "";
      load();
    });
  });

  return { load };
}
