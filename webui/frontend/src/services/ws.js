// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * WebSocket client with auto-reconnect and state resume.
 */
export class WSClient {
  constructor(url, options = {}) {
    this.url = url;
    this.maxRetries = options.maxRetries ?? 10;
    this.backoffMs = 1000;
    this.maxBackoffMs = 30000;
    this.handlers = {};
    this.lastSequence = null;
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.backoffMs = 1000;
      if (this.lastSequence) {
        this.ws.send(JSON.stringify({ type: "resume", from: this.lastSequence }));
      }
    };
    this.ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      this.lastSequence = msg.sequence;
      this.handlers[msg.type]?.(msg);
    };
    this.ws.onclose = () => {
      console.warn(`WS closed; reconnecting in ${this.backoffMs}ms`);
      setTimeout(() => this.connect(), this.backoffMs);
      this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
    };
    this.ws.onerror = () => {
      this.ws.close();
    };
  }

  on(type, handler) {
    this.handlers[type] = handler;
  }

  send(data) {
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}
