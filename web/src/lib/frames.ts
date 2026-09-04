import type { FrameReason } from "./types";

type FrameSender = (jpeg_b64: string, reason: FrameReason) => void;

export class FrameSampler {
  private readonly video: HTMLVideoElement;
  private readonly send: FrameSender;
  private readonly canvas = document.createElement("canvas");
  private readonly diffCanvas = document.createElement("canvas");
  private previous: Uint8ClampedArray | null = null;
  private lastSentAt = 0;
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(video: HTMLVideoElement, send: FrameSender) {
    this.video = video;
    this.send = send;
    this.diffCanvas.width = 64;
    this.diffCanvas.height = 36;
  }

  // Capture is cheap and decoupled from reasoning: every frame is stamped and stored on the
  // server, and the reasoner later picks the frames that fall inside an utterance's time
  // span. So we send on a fixed cadence (plus an extra shot on pointing words) rather than
  // trying to guess which moments matter.
  static readonly PERIOD_MS = 2000;

  start() {
    this.timer = setInterval(() => this.sample(), FrameSampler.PERIOD_MS);
    void this.sample();
  }

  private sample(forceReason?: FrameReason) {
    if (this.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    const width = Math.min(1024, this.video.videoWidth || 1024);
    const height = Math.max(1, Math.round(width * (this.video.videoHeight / (this.video.videoWidth || width))));
    this.canvas.width = width;
    this.canvas.height = height;
    this.canvas.getContext("2d")?.drawImage(this.video, 0, 0, width, height);
    const jpeg_b64 = this.canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
    const diffContext = this.diffCanvas.getContext("2d");
    if (!diffContext) return;
    diffContext.drawImage(this.video, 0, 0, 64, 36);
    const current = diffContext.getImageData(0, 0, 64, 36).data;
    const changed = this.previous ? this.diff(current, this.previous) : 1;
    // `diff` vs `periodic` is now just metadata (helps scene grouping); every tick is sent.
    const reason = forceReason ?? (changed > 0.15 ? "diff" : "periodic");
    this.previous = new Uint8ClampedArray(current);
    this.send(jpeg_b64, reason);
    this.lastSentAt = Date.now();
  }

  private diff(current: Uint8ClampedArray, previous: Uint8ClampedArray) {
    let changed = 0;
    for (let index = 0; index < current.length; index += 4) {
      const currentLuma = 0.299 * current[index] + 0.587 * current[index + 1] + 0.114 * current[index + 2];
      const previousLuma = 0.299 * previous[index] + 0.587 * previous[index + 1] + 0.114 * previous[index + 2];
      if (Math.abs(currentLuma - previousLuma) > 32) changed += 1;
    }
    return changed / (current.length / 4);
  }

  trigger(reason: "deictic" | "manual") {
    this.sample(reason);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
