export type AudioSource = "me" | "remote";

export interface AudioChunk {
  pcm16_b64: string;
  source: AudioSource;
}

function bytesToBase64(bytes: Int16Array) {
  const view = new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let binary = "";
  for (let index = 0; index < view.length; index += 1) binary += String.fromCharCode(view[index]);
  return btoa(binary);
}

const workletSource = `
const CHUNK = 1600;
const SOURCES = ["me", "remote"];

class SplitProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffers = [[], []];
  }
  process(inputs) {
    for (let input = 0; input < SOURCES.length; input++) {
      const channel = inputs[input] && inputs[input][0];
      if (!channel || !channel.length) continue;
      const buffer = this.buffers[input];
      for (const sample of channel) buffer.push(sample);
      while (buffer.length >= CHUNK) {
        const chunk = buffer.splice(0, CHUNK);
        const pcm = new Int16Array(CHUNK);
        for (let i = 0; i < CHUNK; i++) {
          const sample = Math.max(-1, Math.min(1, chunk[i]));
          pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
        this.port.postMessage({ pcm, source: SOURCES[input] }, [pcm.buffer]);
      }
    }
    return true;
  }
}
registerProcessor("aimeet-split", SplitProcessor);
`;

export async function createAudioPipeline(
  streams: { mic: MediaStream | null; tab: MediaStream | null },
  send: (chunk: AudioChunk) => void,
) {
  const context = new AudioContext({ sampleRate: 16000 });
  const moduleUrl = URL.createObjectURL(new Blob([workletSource], { type: "application/javascript" }));
  await context.audioWorklet.addModule(moduleUrl);
  const node = new AudioWorkletNode(context, "aimeet-split", { numberOfInputs: 2, numberOfOutputs: 0 });
  node.port.onmessage = (event: MessageEvent<{ pcm: Int16Array; source: AudioSource }>) =>
    send({ pcm16_b64: bytesToBase64(event.data.pcm), source: event.data.source });

  const sources: MediaStreamAudioSourceNode[] = [];
  const attach = (stream: MediaStream | null, input: number) => {
    if (!stream?.getAudioTracks().length) return;
    const source = context.createMediaStreamSource(stream);
    source.connect(node, 0, input);
    sources.push(source);
  };
  attach(streams.mic, 0);
  attach(streams.tab, 1);

  return () => {
    sources.forEach((source) => source.disconnect());
    node.disconnect();
    URL.revokeObjectURL(moduleUrl);
    void context.close();
  };
}
