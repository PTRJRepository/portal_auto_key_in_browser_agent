import { WebSocketServer, type WebSocket } from "ws";

import type { AgentEvent } from "./types.js";

export class WebsocketHub {
  private readonly clients = new Set<WebSocket>();

  constructor(private readonly server: WebSocketServer) {
    this.server.on("connection", (socket) => {
      this.clients.add(socket);
      socket.on("close", () => {
        this.clients.delete(socket);
      });
    });
  }

  public broadcast(event: AgentEvent): void {
    const payload = JSON.stringify(event);
    for (const socket of this.clients) {
      if (socket.readyState === socket.OPEN) {
        socket.send(payload);
      }
    }
  }
}

