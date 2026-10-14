import numpy as np
import pytest

from autofish.first_click_trigger.audio_input import AudioDeviceInfo, AudioInput
from autofish.first_click_trigger.ring_buffer import AudioRingBuffer


# ---- AudioInput ----


def test_list_devices_filters_and_sorts_virtual_first(fake_sd):
    devices = AudioInput.list_devices()
    names = [d.name for d in devices]
    assert names == ["BlackHole 2ch", "MacBook Pro Microphone", "USB Mic 6ch"]
    bh = devices[0]
    assert isinstance(bh, AudioDeviceInfo)
    assert bh.key == "sd:0" and bh.index == 0
    assert bh.is_input and bh.is_virtual_capture and not bh.is_loopback
    assert bh.channels == 2 and bh.samplerate == 8000.0
    assert not devices[1].is_virtual_capture


def test_preferred_capture_key(fake_sd):
    assert AudioInput.preferred_capture_key() == "sd:0"
    fake_sd.devices[0]["name"] = "Line In"
    assert AudioInput.preferred_capture_key() is None


def test_constructor_probes_device_without_opening_stream(fake_sd):
    a = AudioInput(device=None)
    assert a.samplerate == 8000 and a.channels == 2
    b = AudioInput(device="4")
    assert b.samplerate == 44100 and b.channels == 2
    c = AudioInput(device=1, samplerate=16000, blocksize=256)
    assert c.samplerate == 16000 and c.channels == 1 and c.blocksize == 256
    assert fake_sd.streams == []


def test_start_opens_stream_once_and_read_returns_mono(fake_sd):
    a = AudioInput(device=0)
    assert a.read() is None
    a.start()
    a.start()
    assert len(fake_sd.streams) == 1
    s = fake_sd.streams[0]
    assert s.started and s.device == 0 and s.samplerate == 8000 and s.channels == 2
    left = np.linspace(-1, 1, 64, dtype=np.float32)
    s.callback(np.stack([left, np.zeros_like(left)], axis=1), 64, {}, None)
    block = a.read()
    assert block.dtype == np.float32 and block.shape == (64,)
    np.testing.assert_allclose(block, left / 2, atol=1e-6)
    assert a.read() is None
    a.stop()


def test_unread_blocks_keep_newest_eight(fake_sd):
    a = AudioInput(device=0)
    a.start()
    s = fake_sd.streams[0]
    for i in range(10):
        s.push(np.full(4, float(i), dtype=np.float32))
    got = []
    while (b := a.read()) is not None:
        got.append(float(b[0]))
    assert got == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    a.stop()


def test_long_record_keeps_raw_channels(fake_sd):
    a = AudioInput(device=0)
    a.start()
    s = fake_sd.streams[0]
    s.push(np.ones(10, dtype=np.float32))
    a.begin_record()
    assert a.record_frames == 0 and a.record_snapshot() == []
    for _ in range(12):
        s.push(np.full(100, 0.5, dtype=np.float32))
    assert a.record_frames == 1200
    assert len(a.record_snapshot()) == 12
    raw = a.end_record()
    assert raw.shape == (1200, 2) and raw.dtype == np.float32
    assert a.record_frames == 0
    assert a.end_record() is None
    a.begin_record()
    assert a.end_record() is None
    a.stop()


def test_stop_aborts_stream_and_clears_queue(fake_sd):
    a = AudioInput(device=0)
    a.start()
    s = fake_sd.streams[0]
    s.push(np.ones(32, dtype=np.float32))
    a.stop()
    assert s.aborted and s.closed
    assert a.read() is None
    a.stop()


@pytest.mark.parametrize(
    "device, needle",
    [(2, "多输出"), (3, "无输入声道")],
)
def test_start_rejects_output_only_or_aggregate(fake_sd, device, needle):
    a = AudioInput(device=device)
    with pytest.raises(RuntimeError, match=needle):
        a.start()
    assert fake_sd.streams == []


# ---- AudioRingBuffer ----


def test_ring_empty_and_partial():
    r = AudioRingBuffer(10)
    assert r.capacity == 10
    out = r.last(5)
    assert out.dtype == np.float32 and out.size == 0
    r.extend(np.arange(4, dtype=np.float32))
    r.extend(np.zeros(0, dtype=np.float32))
    np.testing.assert_array_equal(r.last(100), [0, 1, 2, 3])
    np.testing.assert_array_equal(r.last(2), [2, 3])


def test_ring_wraps_in_time_order():
    r = AudioRingBuffer(10)
    for start in range(0, 25, 3):
        r.extend(np.arange(start, start + 3, dtype=np.float32))
    np.testing.assert_array_equal(r.last(10), np.arange(17, 27))
    np.testing.assert_array_equal(r.last(4), [23, 24, 25, 26])


def test_ring_oversized_block_keeps_tail_and_returns_copy():
    r = AudioRingBuffer(10)
    r.extend(np.arange(3, dtype=np.float32))
    r.extend(np.arange(100, 125, dtype=np.float32))
    out = r.last(10)
    np.testing.assert_array_equal(out, np.arange(115, 125))
    out[:] = -1
    np.testing.assert_array_equal(r.last(10), np.arange(115, 125))
