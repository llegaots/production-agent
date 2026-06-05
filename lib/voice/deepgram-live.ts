/* ----------------------------------------------------------------------------
   Browser-side live capture. Streams mic audio directly to Deepgram over a
   WebSocket (authorized with a short-lived token minted by our server), surfaces
   interim + finalized transcript lines, and hands each recorded audio chunk back
   so the caller can persist it. Built to survive a multi-hour session: it pings
   KeepAlive, refreshes the token, and reconnects the socket without dropping the
   MediaRecorder.

   No framework deps — a React component drives it via the callbacks below.
---------------------------------------------------------------------------- */
import type { Speaker } from "@/lib/types";

const DG_WS_BASE = "wss://api.deepgram.com/v1/listen";
const DG_QUERY = new URLSearchParams({
  model: "nova-3",
  language: "en",
  interim_results: "true",
  diarize: "true",
  punctuate: "true",
  smart_format: "true",
  endpointing: "300",
}).toString();

const CHUNK_MS = 5000; // MediaRecorder timeslice → also the storage chunk size
const KEEPALIVE_MS = 8000;
const TOKEN_REFRESH_LEAD_S = 60; // refresh this many seconds before expiry

export type CaptureStatus =
  | "idle"
  | "connecting"
  | "recording"
  | "reconnecting"
  | "stopped"
  | "error";

export interface FinalLine {
  seq: number;
  at: string;
  speaker: Speaker;
  text: string;
}

export interface LiveCaptureOptions {
  sessionId: string;
  onInterim?: (text: string, speaker: Speaker) => void;
  onFinal?: (line: FinalLine) => void;
  onLevel?: (level: number) => void; // 0..1 mic level for the waveform
  onChunk?: (blob: Blob, seq: number) => void; // persist audio
  onStatus?: (status: CaptureStatus) => void;
  onError?: (message: string) => void;
}

interface DeepgramWord {
  word?: string;
  punctuated_word?: string;
  speaker?: number;
}
interface DeepgramResults {
  type?: string;
  is_final?: boolean;
  channel?: { alternatives?: { transcript?: string; words?: DeepgramWord[] }[] };
}

export class LiveCapture {
  private opts: LiveCaptureOptions;
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private socket: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private rafId = 0;
  private keepAlive = 0;
  private tokenTimer = 0;
  private lineSeq = 0;
  private chunkSeq = 0;
  /** Diarization gives integer speaker ids; the first speaker heard is assumed
   *  to be the rep (they open the conversation). Everyone else is the prospect. */
  private repSpeaker: number | null = null;
  private status: CaptureStatus = "idle";
  private stopping = false;

  constructor(opts: LiveCaptureOptions) {
    this.opts = opts;
  }

  getStatus(): CaptureStatus {
    return this.status;
  }

  /** Manager/rep can correct the rep↔prospect mapping if diarization guessed wrong. */
  flipSpeakers(): void {
    // Toggling the anchor flips every subsequent label; past lines stay as sent.
    this.repSpeaker = this.repSpeaker === null ? 1 : this.repSpeaker === 0 ? 1 : 0;
  }

  async start(): Promise<void> {
    this.setStatus("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
    } catch {
      this.fail("Microphone permission denied.");
      throw new Error("mic-denied");
    }
    this.startLevelMeter(this.stream);
    await this.connect();
    this.startRecorder();
  }

  pause(): void {
    if (this.recorder?.state === "recording") this.recorder.pause();
    this.setStatus("recording"); // keep socket warm; KeepAlive holds it open
  }

  resume(): void {
    if (this.recorder?.state === "paused") this.recorder.resume();
    this.setStatus("recording");
  }

  async stop(): Promise<void> {
    this.stopping = true;
    this.setStatus("stopped");
    this.clearTimers();
    if (this.rafId) cancelAnimationFrame(this.rafId);
    try {
      this.recorder?.stop();
    } catch {
      /* ignore */
    }
    // Flush + close Deepgram cleanly so trailing words are finalized.
    if (this.socket?.readyState === WebSocket.OPEN) {
      try {
        this.socket.send(JSON.stringify({ type: "CloseStream" }));
      } catch {
        /* ignore */
      }
    }
    this.socket?.close();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.audioCtx?.close().catch(() => {});
    this.opts.onLevel?.(0);
  }

  // ── Deepgram socket ────────────────────────────────────────────────────────

  private async fetchToken(): Promise<{ token: string; scheme: "bearer" | "token"; expiresIn: number }> {
    const res = await fetch(`/api/sessions/${this.opts.sessionId}/stt-token`, { method: "POST" });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.error || "Could not get a transcription token.");
    }
    return res.json();
  }

  private async connect(): Promise<void> {
    const { token, scheme, expiresIn } = await this.fetchToken();
    await new Promise<void>((resolve, reject) => {
      // Deepgram auth via WebSocket subprotocol: ["bearer", jwt] | ["token", apiKey].
      const ws = new WebSocket(`${DG_WS_BASE}?${DG_QUERY}`, [scheme, token]);
      this.socket = ws;

      ws.onopen = () => {
        if (this.stopping) return;
        this.setStatus("recording");
        this.startKeepAlive();
        resolve();
      };
      ws.onmessage = (ev) => this.handleMessage(ev);
      ws.onerror = () => reject(new Error("Deepgram connection failed."));
      ws.onclose = () => {
        this.clearKeepAlive();
        if (!this.stopping) this.scheduleReconnect();
      };
    });

    // Refresh shortly before expiry, then reconnect. Raw keys (expiresIn === 0)
    // never expire, so no refresh timer is needed.
    this.clearTokenTimer();
    if (expiresIn > 0) {
      const refreshIn = Math.max((expiresIn - TOKEN_REFRESH_LEAD_S) * 1000, 30_000);
      this.tokenTimer = window.setTimeout(() => void this.reconnect(), refreshIn);
    }
  }

  private async reconnect(): Promise<void> {
    if (this.stopping) return;
    this.setStatus("reconnecting");
    try {
      this.socket?.close();
    } catch {
      /* ignore */
    }
    try {
      await this.connect();
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.stopping) return;
    this.setStatus("reconnecting");
    window.setTimeout(() => void this.reconnect(), 2000);
  }

  private handleMessage(ev: MessageEvent): void {
    let msg: DeepgramResults;
    try {
      msg = JSON.parse(ev.data as string);
    } catch {
      return;
    }
    if (msg.type && msg.type !== "Results") return;
    const alt = msg.channel?.alternatives?.[0];
    const text = (alt?.transcript ?? "").trim();
    if (!text) return;
    const words = alt?.words ?? [];

    if (msg.is_final) {
      // Split the result into per-speaker turns so a rep↔prospect exchange in one
      // window becomes correctly-attributed separate lines (not one lumped line).
      const segments = this.splitBySpeaker(words);
      if (segments.length) {
        for (const seg of segments) {
          this.opts.onFinal?.({
            seq: this.lineSeq++,
            at: new Date().toISOString(),
            speaker: this.roleFor(seg.speaker),
            text: seg.text,
          });
        }
      } else {
        this.opts.onFinal?.({
          seq: this.lineSeq++,
          at: new Date().toISOString(),
          speaker: this.roleFor(null),
          text,
        });
      }
    } else {
      this.opts.onInterim?.(text, this.roleFor(this.dominantSpeaker(words)));
    }
  }

  /** Group consecutive words by diarized speaker into one line per speaker turn. */
  private splitBySpeaker(words: DeepgramWord[]): { speaker: number; text: string }[] {
    const segs: { speaker: number; text: string }[] = [];
    let cur: { speaker: number; text: string } | null = null;
    for (const w of words) {
      const token = (w.punctuated_word ?? w.word ?? "").trim();
      if (!token) continue;
      const sp = typeof w.speaker === "number" ? w.speaker : 0;
      if (!cur || cur.speaker !== sp) {
        cur = { speaker: sp, text: token };
        segs.push(cur);
      } else {
        cur.text += " " + token;
      }
    }
    return segs;
  }

  private dominantSpeaker(words: DeepgramWord[]): number | null {
    const counts = new Map<number, number>();
    for (const w of words) {
      if (typeof w.speaker === "number") counts.set(w.speaker, (counts.get(w.speaker) ?? 0) + 1);
    }
    let dominant: number | null = null;
    let best = -1;
    for (const [sp, n] of counts) {
      if (n > best) {
        best = n;
        dominant = sp;
      }
    }
    return dominant;
  }

  /** Map a diarized speaker index to a role. The first speaker heard is the rep
   *  (they knock and open the conversation); everyone else is the prospect. */
  private roleFor(speaker: number | null): Speaker {
    if (speaker === null) return this.repSpeaker === null ? "rep" : "prospect";
    if (this.repSpeaker === null) this.repSpeaker = speaker;
    return speaker === this.repSpeaker ? "rep" : "prospect";
  }

  // ── MediaRecorder ────────────────────────────────────────────────────────────

  private startRecorder(): void {
    if (!this.stream) return;
    // Pick whatever the browser supports: Chrome/Android → webm/opus,
    // iOS Safari → mp4/aac. Deepgram auto-detects the container either way.
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4;codecs=mp4a.40.2",
      "audio/mp4",
      "audio/aac",
    ];
    const mime = candidates.find((m) => MediaRecorder.isTypeSupported?.(m));
    const rec = mime
      ? new MediaRecorder(this.stream, { mimeType: mime })
      : new MediaRecorder(this.stream);
    this.recorder = rec;
    rec.ondataavailable = (e) => {
      if (!e.data || e.data.size === 0) return;
      const seq = this.chunkSeq++;
      // Feed Deepgram (when connected) and hand the chunk to the caller to store.
      if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(e.data);
      this.opts.onChunk?.(e.data, seq);
    };
    rec.start(CHUNK_MS);
  }

  // ── Mic level meter ────────────────────────────────────────────────────────

  private startLevelMeter(stream: MediaStream): void {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    this.audioCtx = new Ctx();
    const src = this.audioCtx.createMediaStreamSource(stream);
    const analyser = this.audioCtx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / buf.length);
      this.opts.onLevel?.(Math.min(1, rms * 2.5));
      this.rafId = requestAnimationFrame(tick);
    };
    tick();
  }

  // ── Timers / status ──────────────────────────────────────────────────────────

  private startKeepAlive(): void {
    this.clearKeepAlive();
    this.keepAlive = window.setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: "KeepAlive" }));
      }
    }, KEEPALIVE_MS);
  }

  private clearKeepAlive(): void {
    if (this.keepAlive) window.clearInterval(this.keepAlive);
    this.keepAlive = 0;
  }

  private clearTokenTimer(): void {
    if (this.tokenTimer) window.clearTimeout(this.tokenTimer);
    this.tokenTimer = 0;
  }

  private clearTimers(): void {
    this.clearKeepAlive();
    this.clearTokenTimer();
  }

  private setStatus(s: CaptureStatus): void {
    this.status = s;
    this.opts.onStatus?.(s);
  }

  private fail(message: string): void {
    this.setStatus("error");
    this.opts.onError?.(message);
  }
}
