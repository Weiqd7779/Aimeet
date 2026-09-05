export function clock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60).toString().padStart(2, "0");
  const r = (s % 60).toString().padStart(2, "0");
  return h > 0 ? `${h}:${m}:${r}` : `${m}:${r}`;
}

/** Drop ElevenLabs audio tags ([clears throat]) from a spoken script for on-screen captions. */
export function captionOf(speech: string | null | undefined) {
  return (speech ?? "").replace(/\[[^\]]*\]\s*/g, "").trim();
}

export function apiUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}
