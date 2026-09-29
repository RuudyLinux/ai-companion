// Mic button: record with MediaRecorder, transcribe with local Whisper via /api/stt.
const MAX_RECORDING_MS = 110 * 1000; // server limit is MAX_AUDIO_SECONDS (120 s by default)

export function initMic(micBtn, input) {
  if (!(navigator.mediaDevices && window.MediaRecorder)) {
    micBtn.style.display = "none";
    return;
  }
  let mediaRecorder = null;
  let chunks = [];
  let stopTimer = null;

  const setIdle = () => {
    micBtn.classList.remove("listening");
    micBtn.textContent = "🎤";
    micBtn.disabled = false;
    micBtn.setAttribute("aria-label", "Record a voice message");
  };

  async function transcribe(blob) {
    micBtn.textContent = "⏳";
    micBtn.disabled = true;
    const formData = new FormData();
    formData.append("audio", blob, "recording.webm");
    try {
      const res = await fetch("/api/stt", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await window.apiErrorMessage(res, "Transcription failed."));
      const data = await res.json();
      if (data.text) input.value = input.value ? `${input.value} ${data.text}` : data.text;
      else if (window.showToast) window.showToast("No speech detected. Try again.", "error");
      input.focus();
    } catch (err) {
      if (window.showToast) window.showToast(err.message, "error");
    } finally {
      setIdle();
    }
  }

  micBtn.addEventListener("click", async () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (window.showToast) window.showToast("Microphone access was denied or is unavailable.", "error");
      return;
    }
    chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
    mediaRecorder.onstop = () => {
      clearTimeout(stopTimer);
      stream.getTracks().forEach((t) => t.stop());
      transcribe(new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" }));
    };
    mediaRecorder.start();
    stopTimer = setTimeout(() => mediaRecorder.state === "recording" && mediaRecorder.stop(), MAX_RECORDING_MS);
    micBtn.classList.add("listening");
    micBtn.textContent = "● Listening...";
    micBtn.setAttribute("aria-label", "Stop recording");
  });
}
