// Streams a reply from /api/chat or /api/chat/regenerate. The server sends NDJSON
// events: start, delta (repeated), then done or error.
export async function streamReply(url, body, { signal, onStart, onDelta }) {
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") return { status: "cancelled", messageId: null };
    return { status: "failed", messageId: null, error: "Network error. Check your connection and try again." };
  }

  if (!res.ok || !res.body) {
    let messageId = null;
    try {
      messageId = (await res.clone().json()).error?.message_id || null;
    } catch (_) {
      /* not JSON */
    }
    return { status: "failed", messageId, error: await window.apiErrorMessage(res, "Couldn't get a reply.") };
  }

  let messageId = res.headers.get("X-Assistant-Message-Id");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let outcome = { status: "failed", messageId, error: "The connection closed unexpectedly." };

  const handle = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "start") {
      messageId = event.message_id;
      onStart?.(event);
    } else if (event.type === "delta") {
      onDelta?.(event.text);
    } else if (event.type === "done") {
      outcome = { status: event.status, messageId };
    } else if (event.type === "error") {
      outcome = { status: "failed", messageId, error: event.message };
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.forEach(handle);
    }
    handle(buffer);
  } catch (err) {
    if (err.name === "AbortError") return { status: "cancelled", messageId };
    return { status: "failed", messageId, error: "Network error while receiving the reply." };
  }
  return outcome;
}

export async function cancelReply(messageId) {
  if (!messageId) return;
  try {
    await fetch(`/api/messages/${messageId}/cancel`, { method: "POST" });
  } catch (_) {
    /* the aborted fetch already ends the stream server-side */
  }
}
