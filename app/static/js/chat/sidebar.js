// Mobile drawer + "follow the conversation" scrolling with a jump-to-latest pill.
export function initSidebarDrawer({ chatShell, toggle, backdrop }) {
  toggle.addEventListener("click", () => {
    const open = chatShell.classList.toggle("sidebar-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  backdrop.addEventListener("click", () => {
    chatShell.classList.remove("sidebar-open");
    toggle.setAttribute("aria-expanded", "false");
  });
}

export function initScroll({ messagesEl, jumpToLatest }) {
  const isNearBottom = () => messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;

  function scrollToBottom(force) {
    if (!force && !isNearBottom()) return;
    messagesEl.scrollTop = messagesEl.scrollHeight;
    jumpToLatest.classList.remove("show");
  }

  messagesEl.addEventListener("scroll", () => {
    if (isNearBottom()) jumpToLatest.classList.remove("show");
  });
  jumpToLatest.addEventListener("click", () => scrollToBottom(true));

  // while streaming: follow if the user is at the bottom, otherwise offer the pill
  function follow(wasNearBottom) {
    if (wasNearBottom) scrollToBottom(true);
    else jumpToLatest.classList.add("show");
  }

  return { isNearBottom, scrollToBottom, follow };
}
