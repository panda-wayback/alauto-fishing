"""系统音选区播放：录制系统输出、波形展示、拖选区间播放。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import soundcard as sc
import sounddevice as sd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector


SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_FRAMES = 1024


class AudioRecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("系统音选区播放")
        self.root.geometry("920x560")
        self.root.minsize(720, 480)

        self.audio: np.ndarray | None = None
        self.sample_rate = SAMPLE_RATE
        self.recording = False
        self._record_chunks: list[np.ndarray] = []
        self._record_thread: threading.Thread | None = None
        self.sel_start = 0.0
        self.sel_end = 0.0
        self._play_stop = threading.Event()

        self._build_ui()
        self._draw_empty()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill=tk.X)

        ttk.Label(top, text="系统音选区", font=("Microsoft YaHei UI", 14, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(
            top,
            text="录制当前系统播放的声音（非麦克风）。录音后在波形上拖拽选择区间再播放",
            foreground="#555",
        ).pack(anchor=tk.W, pady=(2, 0))

        self.fig = Figure(figsize=(9, 3.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.92, bottom=0.18)

        canvas_frame = ttk.Frame(self.root, padding=(12, 0))
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=canvas_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.span = SpanSelector(
            self.ax,
            self._on_select,
            "horizontal",
            useblit=True,
            interactive=True,
            drag_from_anywhere=True,
            props=dict(facecolor="#3d9cf0", alpha=0.28),
            handle_props=dict(linewidth=1.5),
        )

        info = ttk.Frame(self.root, padding=(12, 6))
        info.pack(fill=tk.X)
        self.lbl_sel = ttk.Label(info, text="选区: --")
        self.lbl_sel.pack(side=tk.LEFT)
        self.lbl_dur = ttk.Label(info, text="总长: --")
        self.lbl_dur.pack(side=tk.RIGHT)

        btns = ttk.Frame(self.root, padding=12)
        btns.pack(fill=tk.X)

        self.btn_record = ttk.Button(btns, text="开始录音", command=self.toggle_record)
        self.btn_record.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_play_sel = ttk.Button(
            btns, text="播放选区", command=self.play_selection, state=tk.DISABLED
        )
        self.btn_play_sel.pack(side=tk.LEFT, padx=6)

        self.btn_play_all = ttk.Button(
            btns, text="播放全部", command=self.play_all, state=tk.DISABLED
        )
        self.btn_play_all.pack(side=tk.LEFT, padx=6)

        self.btn_stop = ttk.Button(
            btns, text="停止播放", command=self.stop_playback, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT, padx=6)

        self.btn_clear = ttk.Button(
            btns, text="清除", command=self.clear_audio, state=tk.DISABLED
        )
        self.btn_clear.pack(side=tk.LEFT, padx=6)

        self.lbl_status = ttk.Label(
            self.root,
            text="点击「开始录音」录制系统正在播放的声音",
            padding=(12, 0, 12, 12),
        )
        self.lbl_status.pack(fill=tk.X)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _fmt(t: float) -> str:
        m = int(t // 60)
        s = t - m * 60
        return f"{m}:{s:05.2f}"

    @staticmethod
    def _to_mono(audio: np.ndarray) -> np.ndarray:
        if audio.ndim == 1:
            return audio
        return audio.mean(axis=1)

    def _duration(self) -> float:
        if self.audio is None or len(self.audio) == 0:
            return 0.0
        return len(self.audio) / self.sample_rate

    def _set_status(self, text: str) -> None:
        self.lbl_status.configure(text=text)

    def _set_has_audio(self, has: bool) -> None:
        state = tk.NORMAL if has else tk.DISABLED
        self.btn_play_sel.configure(state=state)
        self.btn_play_all.configure(state=state)
        self.btn_clear.configure(state=state)

    def _find_loopback(self):
        speaker = sc.default_speaker()
        try:
            mic = sc.get_microphone(id=speaker.name, include_loopback=True)
            if getattr(mic, "isloopback", False):
                return mic, speaker.name
        except Exception:  # noqa: BLE001
            pass

        for mic in sc.all_microphones(include_loopback=True):
            if getattr(mic, "isloopback", False) and speaker.name in mic.name:
                return mic, speaker.name

        loopbacks = [
            m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)
        ]
        if loopbacks:
            return loopbacks[0], loopbacks[0].name

        raise RuntimeError("未找到系统环回设备，无法录制系统音")

    def _draw_empty(self) -> None:
        self.ax.clear()
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(-1, 1)
        self.ax.set_xlabel("时间 (秒)")
        self.ax.set_ylabel("振幅")
        self.ax.text(
            0.5,
            0.5,
            "录音后将在此显示波形",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color="#888",
        )
        self.ax.grid(True, alpha=0.25)
        self.canvas.draw_idle()

    def _draw_waveform(self) -> None:
        assert self.audio is not None
        data = self._to_mono(self.audio)
        t = np.arange(len(data)) / self.sample_rate

        max_points = 8000
        if len(data) > max_points:
            step = len(data) // max_points
            t_plot = t[::step]
            y_plot = data[::step]
        else:
            t_plot, y_plot = t, data

        self.ax.clear()
        self.ax.plot(t_plot, y_plot, color="#5eb3f5", linewidth=0.8)
        self.ax.set_xlim(0, t[-1] if len(t) else 1)
        peak = float(np.max(np.abs(data))) if len(data) else 1.0
        ylim = max(peak * 1.1, 0.1)
        self.ax.set_ylim(-ylim, ylim)
        self.ax.set_xlabel("时间 (秒)")
        self.ax.set_ylabel("振幅")
        self.ax.grid(True, alpha=0.25)

        self.span = SpanSelector(
            self.ax,
            self._on_select,
            "horizontal",
            useblit=True,
            interactive=True,
            drag_from_anywhere=True,
            props=dict(facecolor="#3d9cf0", alpha=0.28),
            handle_props=dict(linewidth=1.5),
        )
        if self.sel_end > self.sel_start:
            self.span.extents = (self.sel_start, self.sel_end)

        self.canvas.draw_idle()
        self.lbl_dur.configure(text=f"总长: {self._fmt(t[-1] if len(t) else 0)}")

    def _on_select(self, xmin: float, xmax: float) -> None:
        if self.audio is None:
            return
        duration = self._duration()
        a = max(0.0, min(xmin, xmax))
        b = min(duration, max(xmin, xmax))
        self.sel_start, self.sel_end = a, b
        self.lbl_sel.configure(
            text=f"选区: {self._fmt(a)} → {self._fmt(b)}  ({self._fmt(b - a)})"
        )

    def toggle_record(self) -> None:
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _record_loop(self, loopback) -> None:
        try:
            with loopback.recorder(
                samplerate=self.sample_rate, channels=CHANNELS
            ) as recorder:
                while self.recording:
                    chunk = recorder.record(numframes=BLOCK_FRAMES)
                    if chunk is not None and len(chunk):
                        self._record_chunks.append(np.asarray(chunk, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            self.root.after(
                0, lambda: messagebox.showerror("录音错误", f"录制系统音失败：\n{exc}")
            )
            self.root.after(0, self._abort_recording)

    def _abort_recording(self) -> None:
        self.recording = False
        self.btn_record.configure(text="开始录音")
        self._set_status("录音失败，请检查系统音频设备")

    def _start_recording(self) -> None:
        self.stop_playback()
        self._record_chunks = []
        try:
            loopback, device_name = self._find_loopback()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("系统音错误", str(exc))
            return

        self.recording = True
        self.btn_record.configure(text="停止录音")
        self._set_has_audio(False)
        self._set_status(f"正在录制系统音…（{device_name}）")

        self._record_thread = threading.Thread(
            target=self._record_loop, args=(loopback,), daemon=True
        )
        self._record_thread.start()

    def _stop_recording(self) -> None:
        self.recording = False
        if self._record_thread is not None:
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

        self.btn_record.configure(text="开始录音")

        if not self._record_chunks:
            self._set_status("未录到有效音频，请先播放系统声音再录音")
            return

        self.audio = np.concatenate(self._record_chunks, axis=0)
        duration = self._duration()
        self.sel_start = 0.0
        self.sel_end = duration
        self._draw_waveform()
        self._on_select(self.sel_start, self.sel_end)
        self._set_has_audio(True)
        self._set_status("录音完成，拖拽波形选择区间后可播放选区")

    def play_selection(self) -> None:
        if self.audio is None:
            return
        self._play_range(self.sel_start, self.sel_end)

    def play_all(self) -> None:
        if self.audio is None:
            return
        self._play_range(0.0, self._duration())

    def _play_range(self, start: float, end: float) -> None:
        if self.audio is None:
            return
        if end - start < 0.02:
            self._set_status("选区太短，请拖宽一些")
            return

        self.stop_playback()
        i0 = int(start * self.sample_rate)
        i1 = int(end * self.sample_rate)
        clip = self.audio[i0:i1].copy()

        self._play_stop.clear()
        self.btn_stop.configure(state=tk.NORMAL)
        self._set_status(f"播放中: {self._fmt(start)} → {self._fmt(end)}")

        def worker() -> None:
            try:
                sd.play(clip, self.sample_rate, blocking=True)
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self._set_status(f"播放失败: {exc}"))
            finally:
                self.root.after(0, self._on_play_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _on_play_finished(self) -> None:
        self.btn_stop.configure(state=tk.DISABLED)
        if self._play_stop.is_set():
            self._set_status("已停止播放")
        else:
            self._set_status("播放结束")

    def stop_playback(self) -> None:
        self._play_stop.set()
        try:
            sd.stop()
        except Exception:  # noqa: BLE001
            pass
        self.btn_stop.configure(state=tk.DISABLED)

    def clear_audio(self) -> None:
        self.stop_playback()
        self.audio = None
        self.sel_start = 0.0
        self.sel_end = 0.0
        self.lbl_sel.configure(text="选区: --")
        self.lbl_dur.configure(text="总长: --")
        self._set_has_audio(False)
        self._draw_empty()
        self._set_status("已清除，可以重新录音")

    def _on_close(self) -> None:
        if self.recording:
            self._stop_recording()
        self.stop_playback()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    AudioRecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
