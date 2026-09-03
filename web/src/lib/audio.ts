function bytesToBase64(bytes: Int16Array) {
  const view = new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let binary = "";
  for (let index = 0; index < view.length; index += 1) binary += String.fromCharCode(view[index]);
  return btoa(binary);
}

function floatToPcm16(input: Float32Array) {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

const workletSource = `
class Pcm16Processor extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = []; this.size = 1600; }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (const sample of channel) this.buffer.push(sample);
    while (this.buffer.length >= this.size) {
      const chunk = this.buffer.splice(0, this.size);
      const pcm = new Int16Array(chunk.length);
      for (let i = 0; i < chunk.length; i++) {
        const sample = Math.max(-1, Math.min(1, chunk[i]));
        pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      this.port.postMessage(pcm, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor("aimeet-pcm16", Pcm16Processor);
`;

export async function createAudioPipeline(
  stream: MediaStream,
  send: (pcm16_b64: string) => void,
) {
  const context = new AudioContext({ sampleRate: 16000 });
  const source = context.createMediaStreamSource(stream);
  let processor: AudioWorkletNode | ScriptProcessorNode;
  let moduleUrl: string | undefined;
  try {
    moduleUrl = URL.createObjectURL(new Blob([workletSource], { type: "application/javascript" }));
    await context.audioWorklet.addModule(moduleUrl);
    const node = new AudioWorkletNode(context, "aimeet-pcm16");
    node.port.onmessage = (event: MessageEvent<Int16Array>) => send(bytesToBase64(event.data));
    processor = node;
  } catch {
    const node = context.createScriptProcessor(4096, 1, 1);
    node.onaudioprocess = (event) => {
      send(bytesToBase64(floatToPcm16(event.inputBuffer.getChannelData(0))));
    };
    processor = node;
  }
  source.connect(processor);
  processor.connect(context.destination);
  return () => {
    source.disconnect();
    processor.disconnect();
    if (moduleUrl) URL.revokeObjectURL(moduleUrl);
    void context.close();
  };
}
