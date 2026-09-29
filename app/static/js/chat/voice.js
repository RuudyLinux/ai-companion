// Text-to-speech for assistant replies: queue a job, poll it, then play the result.
import { attachAudioPlayer } from "./audio-player.js";

export function createVoice({ voiceSelect, effectSelect, speakingIndicator }) {
  const pending = new Map(); // messageId -> AbortController

  function note(slot, text, onRetry) {
    slot.innerHTML = `<span class="audio-skip-note" role="status">${window.escapeHtml(text)}</span>`;
    if (onRetry) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "audio-btn";
      retry.textContent = "↻";
      retry.title = "Try generating the voice again";
      retry.setAttribute("aria-label", "Retry voice generation");
      retry.addEventListener("click", onRetry);
      slot.appendChild(retry);
    }
  }

  async function synthesizeAndPlay(messageId, bubbleEl, existingSlot, { autoplay = true } = {}) {
    if (!messageId || !voiceSelect.value) return;
    const slot = existingSlot || document.createElement("div");
    if (!existingSlot) {
      slot.className = "bubble-audio";
      slot.dataset.audioSlot = "";
      bubbleEl.appendChild(slot);
    }

    pending.get(messageId)?.abort();
    const controller = new AbortController();
    pending.set(messageId, controller);
    const retry = () => synthesizeAndPlay(messageId, bubbleEl, slot, { autoplay: true });

    slot.innerHTML = `<span class="audio-skip-note" role="status"><span class="spinner"></span> Generating voice...</span>`;
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "audio-btn";
    cancelBtn.textContent = "✕";
    cancelBtn.title = "Cancel voice generation";
    cancelBtn.setAttribute("aria-label", "Cancel voice generation");
    slot.appendChild(cancelBtn);

    let jobId = null;
    cancelBtn.addEventListener("click", () => {
      controller.abort();
      if (jobId) fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }).catch(() => {});
    });

    try {
      const res = await fetch(`/api/messages/${messageId}/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_id: voiceSelect.value, tts_effect: effectSelect.value || null }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Voice generation failed."));
      let data = await res.json();

      if (data.skipped) {
        note(slot, data.reason || "No audio for this language.");
        return;
      }
      if (data.status !== "completed") {
        jobId = data.job_id;
        const job = await window.waitForJob(jobId, { signal: controller.signal });
        data = job.result;
      }
      const audio = attachAudioPlayer(slot, data.audio_url, data.duration, speakingIndicator);
      // autoplay may be blocked until the first user gesture; the play button still works
      if (autoplay) audio.play().catch(() => {});
    } catch (err) {
      note(slot, err.name === "AbortError" ? "Voice cancelled." : err.message || "Voice generation failed.", retry);
    } finally {
      if (pending.get(messageId) === controller) pending.delete(messageId);
    }
  }

  return { synthesizeAndPlay };
}

// Voice preview: static clip for builtin voices, otherwise a generated-once clip.
export async function playVoicePreview(voiceId, button) {
  const original = button.textContent;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span> Loading...';
  try {
    const res = await fetch(`/api/voices/${voiceId}/preview`, { method: "POST" });
    if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Couldn't load that preview."));
    let data = await res.json();
    if (data.status !== "completed") data = (await window.waitForJob(data.job_id)).result;
    await new Audio(data.audio_url).play();
  } catch (err) {
    if (window.showToast) window.showToast(err.message || "Couldn't load that preview.", "error");
  } finally {
    button.textContent = original;
    button.disabled = false;
  }
}
