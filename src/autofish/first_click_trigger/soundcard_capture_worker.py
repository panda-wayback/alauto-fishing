"""子进程：默认/指定扬声器 WASAPI 环回 → stdout float32 单声道。

对齐 excode/recorder.py：44100、双声道采集、mean 成单声道。
主进程（含 OpenCV）内直接 soundcard.record 易崩，故开发态走本脚本。
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        print(
            "usage: soundcard_capture_worker.py <mic_id|DEFAULT> <sr> <blocksize> <channels>",
            file=sys.stderr,
        )
        return 2
    mic_id, sr_s, bs_s, ch_s = args[0], args[1], args[2], args[3]
    try:
        sr = int(sr_s)
        blocksize = int(bs_s)
        channels = int(ch_s)
    except ValueError:
        print("sr/blocksize/channels 须为整数", file=sys.stderr)
        return 2

    import numpy as np

    warm = np.random.randn(512, 512).astype(np.float32)
    _ = warm @ warm.T

    # 与 excode/recorder.py 相同：先 sounddevice 再 soundcard
    try:
        import sounddevice as _sd  # noqa: F401
    except ImportError:
        _sd = None

    try:
        import soundcard as sc
    except ImportError as exc:
        print(f"需要 soundcard：{exc}", file=sys.stderr)
        return 1

    try:
        if mic_id == "DEFAULT":
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=speaker.name, include_loopback=True)
            if not getattr(mic, "isloopback", False):
                for m in sc.all_microphones(include_loopback=True):
                    if getattr(m, "isloopback", False) and speaker.name in m.name:
                        mic = m
                        break
        else:
            mic = sc.get_microphone(mic_id, include_loopback=True)
    except Exception as exc:  # noqa: BLE001
        print(f"无法打开环回设备（{mic_id}）：{exc}", file=sys.stderr)
        return 1

    ch = min(2, max(1, channels))
    out = sys.stdout.buffer
    try:
        with mic.recorder(samplerate=sr, channels=ch) as rec:
            while True:
                try:
                    block = rec.record(numframes=blocksize)
                except Exception as exc:  # noqa: BLE001
                    print(f"record 失败：{exc}", file=sys.stderr)
                    return 1
                arr = np.asarray(block, dtype=np.float32)
                if arr.ndim > 1 and arr.shape[1] > 1:
                    mono = arr.mean(axis=1).astype(np.float32)
                else:
                    mono = arr.reshape(-1).astype(np.float32)
                try:
                    out.write(mono.tobytes())
                    out.flush()
                except BrokenPipeError:
                    return 0
    except Exception as exc:  # noqa: BLE001
        print(f"recorder 失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
