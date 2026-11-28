/** In-memory ownership survives record refreshes and replaceable action forms. */
export class PendingOperation {
  body: object | null = null;
  busy = false;

  async run<T>(body: object, send: (body: object) => Promise<T>): Promise<T | null> {
    if (this.busy) return null;
    if (this.body && this.body !== body) throw new Error('operation_pending');
    this.body = body;
    this.busy = true;
    try {
      const result = await send(this.body);
      this.body = null;
      return result;
    } finally {
      this.busy = false;
    }
  }

  clear() { this.body = null; }
}
