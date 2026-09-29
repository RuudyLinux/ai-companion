// Small play/pause control bound to one audio URL; toggles the "Speaking..." indicator.
export function attachAudioPlayer(slotEl, audioUrl, durationSeconds, speakingIndicator) {
  slotEl.innerHTML = "";
  const audio = new Audio(audioUrl);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "audio-btn";
  btn.textContent = "▶";
  btn.setAttribute("aria-label", "Play voice reply");
  const time = document.createElement("span");
  time.className = "audio-time";
  time.textContent = durationSeconds ? `${Number(durationSeconds).toFixed(1)}s` : "";

  const setPlaying = (playing) => {
    btn.textContent = playing ? "⏸" : "▶";
    btn.setAttribute("aria-label", playing ? "Pause voice reply" : "Play voice reply");
    speakingIndicator.classList.toggle("show", playing);
  };

  btn.addEventListener("click", () => (audio.paused ? audio.play().catch(() => {}) : audio.pause()));
  audio.addEventListener("play", () => setPlaying(true));
  audio.addEventListener("pause", () => setPlaying(false));
  audio.addEventListener("ended", () => setPlaying(false));
  audio.addEventListener("error", () => {
    setPlaying(false);
    time.textContent = "audio unavailable";
  });

  slotEl.appendChild(btn);
  slotEl.appendChild(time);
  return audio;
}
