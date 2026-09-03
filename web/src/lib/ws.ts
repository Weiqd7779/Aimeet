import type { ClientMessage, ServerEvent } from "./types";

type EventHandler = (event: ServerEvent) => void;
type ConnectionHandler = (connected: boolean) => void;

export class LiveSocket {
  private socket: WebSocket | null = null;
  private readonly url: string;
  private readonly onEvent: EventHandler;
  private readonly onConnection: ConnectionHandler;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  constructor(url: string, onEvent: EventHandler, onConnection: ConnectionHandler) {
    this.url = url;
    this.onEvent = onEvent;
    this.onConnection = onConnection;
  }

  connect() {
    this.intentionalClose = false;
    this.open();
  }

  private open() {
    this.socket = new WebSocket(this.url);
    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.onConnection(true);
    };
    this.socket.onmessage = (message) => {
      try {
        this.onEvent(JSON.parse(message.data) as ServerEvent);
      } catch {
        this.onEvent({ type: "error", payload: { detail: "Invalid server event" } });
      }
    };
    this.socket.onclose = () => {
      this.onConnection(false);
      if (!this.intentionalClose && this.reconnectAttempts < 3) {
        this.reconnectAttempts += 1;
        this.reconnectTimer = setTimeout(() => this.open(), 500 * this.reconnectAttempts);
      }
    };
  }

  send(message: ClientMessage) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  close() {
    this.intentionalClose = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }
}
