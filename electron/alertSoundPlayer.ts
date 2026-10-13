import { BrowserWindow } from "electron";
import type { AlertSoundTone } from "./alertSoundFiles";

export type AlertSoundPayload = { tone: AlertSoundTone; audio?: string };

/** Self-contained: serialized into the sandboxed sound window, with no Node access. */
async function playSoundInBrowser(payload: AlertSoundPayload, validateOnly: boolean): Promise<number> {
  const host = window as Window & { railwatchAudio?: AudioContext };
  const context = host.railwatchAudio ?? (host.railwatchAudio = new AudioContext());
  if (!validateOnly && context.state === "suspended") await context.resume();
  if (payload.tone === "custom") {
    const bytes = Uint8Array.from(atob(payload.audio || ""), (char) => char.charCodeAt(0));
    let buffer: AudioBuffer;
    try {
      buffer = await context.decodeAudioData(bytes.buffer);
    } catch {
      throw new Error("无法播放此音频，请选择有效的 WAV、MP3、OGG 或 M4A 文件。");
    }
    if (!Number.isFinite(buffer.duration) || buffer.duration <= 0 || buffer.duration > 15) {
      throw new Error("自定义提示音长度须在 15 秒以内。");
    }
    if (!validateOnly) {
      const source = context.createBufferSource();
      const gain = context.createGain();
      source.buffer = buffer;
      gain.gain.value = 0.35;
      source.connect(gain);
      gain.connect(context.destination);
      source.onended = () => { source.disconnect(); gain.disconnect(); };
      source.start();
    }
    return Math.ceil(buffer.duration * 1000);
  }
  const notes: Record<string, { frequency: number; at: number; duration: number; volume: number; type: OscillatorType }[]> = {
    beep: [{ frequency: 880, at: 0, duration: 0.22, volume: 0.08, type: "sine" }],
    chime: [
      { frequency: 1046.5, at: 0, duration: 0.3, volume: 0.055, type: "sine" },
      { frequency: 784, at: 0.3, duration: 0.4, volume: 0.045, type: "sine" },
    ],
    double: [
      { frequency: 880, at: 0, duration: 0.13, volume: 0.07, type: "sine" },
      { frequency: 1174.7, at: 0.22, duration: 0.16, volume: 0.07, type: "sine" },
    ],
    alarm: [0, 1, 2, 3].map((index) => ({
      frequency: index % 2 ? 784 : 1046.5, at: index * 0.2,
      duration: 0.17, volume: 0.055, type: "triangle" as const,
    })),
  };
  const selected = notes[payload.tone] ?? notes.beep;
  if (!validateOnly) for (const note of selected) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const start = context.currentTime + note.at;
    const end = start + note.duration;
    oscillator.type = note.type;
    oscillator.frequency.value = note.frequency;
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(note.volume, start + 0.012);
    gain.gain.setValueAtTime(note.volume, end - 0.035);
    gain.gain.linearRampToValueAtTime(0, end);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    oscillator.start(start);
    oscillator.stop(end);
  }
  return Math.ceil(Math.max(...selected.map((note) => note.at + note.duration)) * 1000);
}

export class AlertSoundPlayer {
  private window: BrowserWindow | null = null;
  private ready: Promise<void> | null = null;
  private generation = 0;

  prepare(): void {
    if (this.window && !this.window.isDestroyed()) return;
    const created = new BrowserWindow({
      show: false, width: 1, height: 1,
      webPreferences: {
        sandbox: true, nodeIntegration: false, contextIsolation: true,
        autoplayPolicy: "no-user-gesture-required",
      },
    });
    this.window = created;
    this.ready = created.loadURL("about:blank");
    // Keep startup failures handled even when a pending playback is cancelled.
    void this.ready.catch(() => { if (this.window === created) this.stop(); });
  }

  async play(payload: AlertSoundPayload, validateOnly = false): Promise<number> {
    this.prepare();
    const window = this.window!;
    const generation = this.generation;
    try {
      await this.ready;
      if (generation !== this.generation || window.isDestroyed()) return 0;
      const duration = await window.webContents.executeJavaScript(
        `(${playSoundInBrowser.toString()})(${JSON.stringify(payload)}, ${validateOnly});`, true,
      );
      if (generation !== this.generation || window.isDestroyed()) return 0;
      if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0 || duration > 15000) {
        throw new Error("提示音播放失败，请重试。");
      }
      return duration;
    } catch (error) {
      if (generation !== this.generation || window.isDestroyed()) return 0;
      throw error;
    }
  }

  stop(): void {
    this.generation++;
    if (this.window && !this.window.isDestroyed()) this.window.destroy();
    this.window = null;
    this.ready = null;
  }
}
