"""回测页：长录音、会话列表、模板库、波形回测。"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from autofish.first_click_trigger.paths import (
    delete_library_template,
    delete_session_dir,
    is_bundled_template,
    list_session_dirs,
    rename_library_template,
    resolve_template_path,
    set_active_template,
    template_source_label,
)
from tools.busy_worker import FnWorker
from tools.shell_log import append_log
from tools.shell_theme import TEXT_MUTED
from tools.sound_panel import FirstClickTriggerPanel
from tools.template_combo import fill_template_combo
from tools.waveform_select import WaveformSelectWidget


class AudioBacktestPanel(QWidget):
    """回测页：长录音、会话列表、模板库、波形回测。"""

    def __init__(
        self,
        host: FirstClickTriggerPanel,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._logs: deque[str] = deque(maxlen=200)
        self._last_session_root: Path | None = None
        self._last_session_wave: object | None = None
        self._last_session_sr: int = 0
        self._last_session_ranges: list[tuple[float, float]] = []
        self._busy_worker: FnWorker | None = None
        self._busy_dialog: QProgressDialog | None = None

        self._build_ui()
        self.refresh_lists()
        host.on_library_changed(self.refresh_lists)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

    def refresh_lists(self) -> None:
        self._refresh_sessions()
        self._refresh_templates()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        top = QWidget()
        layout = QVBoxLayout(top)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)

        row_sess = QHBoxLayout()
        self.btn_sess_rec = QPushButton("开始长录音")
        self.btn_sess_rec.setToolTip("需先在「声音开钓配置」页监听（未监听会自动尝试开启）")
        self.btn_sess_rec.clicked.connect(self._on_session_rec_clicked)
        row_sess.addWidget(self.btn_sess_rec)
        row_sess.addWidget(QLabel("会话"))
        self.cmb_session = QComboBox()
        self.cmb_session.currentIndexChanged.connect(self._on_session_combo)
        row_sess.addWidget(self.cmb_session, 1)
        self.btn_sess_refresh = QPushButton("刷新")
        self.btn_sess_refresh.clicked.connect(self.refresh_lists)
        row_sess.addWidget(self.btn_sess_refresh)
        self.btn_sess_del = QPushButton("删除会话")
        self.btn_sess_del.setToolTip("删除当前选中的长录音会话")
        self.btn_sess_del.clicked.connect(self._delete_session)
        row_sess.addWidget(self.btn_sess_del)
        layout.addLayout(row_sess)

        row_tmpl = QHBoxLayout()
        row_tmpl.addWidget(QLabel("模板库"))
        self.cmb_template = QComboBox()
        self.cmb_template.currentIndexChanged.connect(self._on_template_combo)
        row_tmpl.addWidget(self.cmb_template, 1)
        self.btn_tmpl_play = QPushButton("试听")
        self.btn_tmpl_play.clicked.connect(self._play_template)
        row_tmpl.addWidget(self.btn_tmpl_play)
        self.btn_tmpl_rename = QPushButton("改名")
        self.btn_tmpl_rename.clicked.connect(self._rename_template)
        row_tmpl.addWidget(self.btn_tmpl_rename)
        self.btn_tmpl_del = QPushButton("删除")
        self.btn_tmpl_del.clicked.connect(self._delete_template)
        row_tmpl.addWidget(self.btn_tmpl_del)
        layout.addLayout(row_tmpl)

        self.wave = WaveformSelectWidget()
        self.wave.setMinimumHeight(110)
        self.wave.selection_changed.connect(self._on_wave_selection)
        layout.addWidget(self.wave)

        row_act = QHBoxLayout()
        self.btn_zoom_sel = QPushButton("缩放到选区")
        self.btn_zoom_sel.clicked.connect(self.wave.zoom_to_selection)
        row_act.addWidget(self.btn_zoom_sel)
        self.btn_zoom_all = QPushButton("显示全部")
        self.btn_zoom_all.clicked.connect(self.wave.zoom_all)
        row_act.addWidget(self.btn_zoom_all)
        self.btn_play_sel = QPushButton("试听选区")
        self.btn_play_sel.clicked.connect(self._play_selection)
        row_act.addWidget(self.btn_play_sel)
        self.btn_add_tpl = QPushButton("选区入库为模板")
        self.btn_add_tpl.setToolTip("自动命名并设为当前模板")
        self.btn_add_tpl.clicked.connect(self._add_template_from_selection)
        row_act.addWidget(self.btn_add_tpl)
        self.btn_backtest = QPushButton("回测查找")
        self.btn_backtest.clicked.connect(self._backtest_session)
        row_act.addWidget(self.btn_backtest)
        row_act.addStretch(1)
        self.lbl_sel = QLabel("选区：—")
        self.lbl_sel.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        row_act.addWidget(self.lbl_sel)
        layout.addLayout(row_act)

        row_mark = QHBoxLayout()
        self.btn_add_range = QPushButton("标注水花")
        self.btn_add_range.clicked.connect(self._add_selection_as_mark)
        row_mark.addWidget(self.btn_add_range)
        self.btn_clear_marks = QPushButton("清空标注")
        self.btn_clear_marks.clicked.connect(self._clear_marks)
        row_mark.addWidget(self.btn_clear_marks)
        row_mark.addStretch(1)
        layout.addLayout(row_mark)

        self.lbl_sess = QLabel("蓝=选区 · 绿=人工水花 · 橙=回测命中")
        self.lbl_sess.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        layout.addWidget(self.lbl_sess)
        layout.addStretch(1)

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        top_scroll.setWidget(top)
        splitter.addWidget(top_scroll)

        log_wrap = QWidget()
        log_l = QVBoxLayout(log_wrap)
        log_l.setContentsMargins(0, 4, 0, 0)
        log_title = QLabel("日志（可拖边上沿改高度）")
        log_title.setStyleSheet(f"font-weight:600; color:{TEXT_MUTED}; font-size:12px;")
        log_l.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(100)
        log_l.addWidget(self.log, 1)
        splitter.addWidget(log_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 200])
        root.addWidget(splitter)

    def _refresh_sessions(self) -> None:
        cur = self.cmb_session.currentData()
        self.cmb_session.blockSignals(True)
        self.cmb_session.clear()
        self.cmb_session.addItem("（未选择）", None)
        sel = 0
        for i, p in enumerate(list_session_dirs(), start=1):
            self.cmb_session.addItem(p.name, p)
            if cur is not None and isinstance(cur, Path) and p == cur:
                sel = i
            elif self._last_session_root is not None and p == self._last_session_root:
                sel = i
        self.cmb_session.setCurrentIndex(sel)
        self.cmb_session.blockSignals(False)

    def _refresh_templates(self) -> None:
        path = fill_template_combo(self.cmb_template)
        bundled = is_bundled_template(path) if path is not None else False
        self.btn_tmpl_rename.setEnabled(not bundled and path is not None)
        self.btn_tmpl_del.setEnabled(not bundled and path is not None)

    def _run_busy(
        self,
        title: str,
        fn: Callable[[], object],
        on_ok: Callable[[object], None],
    ) -> None:
        """后台跑耗时任务 + 模态等待条，避免卡死整窗。"""
        if self._busy_worker is not None and self._busy_worker.isRunning():
            self._log("请等待当前任务完成…")
            return
        dlg = QProgressDialog(title, None, 0, 0, self)
        dlg.setWindowTitle("请稍候")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setRange(0, 0)
        dlg.show()
        self._busy_dialog = dlg

        worker = FnWorker(fn, self)

        def _done(result: object) -> None:
            dlg.close()
            self._busy_dialog = None
            self._busy_worker = None
            try:
                on_ok(result)
            except Exception as exc:  # noqa: BLE001
                self._log(f"{title}后处理失败：{exc}")

        def _fail(msg: str) -> None:
            dlg.close()
            self._busy_dialog = None
            self._busy_worker = None
            self.btn_sess_rec.setEnabled(True)
            self._log(f"{title}失败：{msg}")

        worker.ok.connect(_done)
        worker.err.connect(_fail)
        self._busy_worker = worker
        worker.start()

    def _on_session_combo(self, _idx: int) -> None:
        root = self.cmb_session.currentData()
        if not isinstance(root, Path):
            return
        if self._last_session_root == root and self._last_session_wave is not None:
            return

        def work() -> object:
            from autofish.first_click_trigger.session_eval import load_session

            return (root, *load_session(root))

        def done(result: object) -> None:
            r, wave, sr, ranges = result  # type: ignore[misc]
            self._apply_loaded_session(r, wave, int(sr), list(ranges))
            self._log(f"已加载会话 {r.name}")

        self._run_busy(f"加载会话 {root.name}…", work, done)

    def _on_session_rec_clicked(self) -> None:
        try:
            trigger = self._host.start_listen_if_needed()
        except Exception as exc:  # noqa: BLE001
            self._log(str(exc))
            return
        try:
            if trigger.is_session_recording:
                self.btn_sess_rec.setEnabled(False)

                def work() -> object:
                    return trigger.stop_session_recording()

                def done(result: object) -> None:
                    self.btn_sess_rec.setEnabled(True)
                    out = result  # type: ignore[assignment]
                    assert isinstance(out, dict)
                    paths = out["paths"]
                    self._apply_loaded_session(
                        paths.root,
                        out["wave"],
                        int(out["samplerate"]),
                        list(out["ranges"]),
                    )
                    report = out.get("report")
                    if isinstance(report, dict) and report.get("hits"):
                        self.wave.set_hits(list(report["hits"]))
                        self.lbl_sess.setText(
                            f"已保存 · 回测命中 {len(report['hits'])} 处（橙）"
                        )
                    text = str(out.get("report_text") or "")
                    if text:
                        self._log(text)
                    elif not trigger.has_template:
                        self._log("已保存录音；选区入库后再回测")
                    self.btn_sess_rec.setText("开始长录音")
                    self.refresh_lists()
                    for i in range(self.cmb_session.count()):
                        if self.cmb_session.itemData(i) == paths.root:
                            self.cmb_session.setCurrentIndex(i)
                            break

                self._run_busy("保存录音并回测…", work, done)
            else:
                trigger.start_session_recording()
                self.btn_sess_rec.setText("停止并保存")
                self.wave.clear()
                self.lbl_sess.setText("长录音中…")
        except Exception as exc:  # noqa: BLE001
            self.btn_sess_rec.setEnabled(True)
            self._log(f"长录音失败：{exc}")

    def _backtest_session(self) -> None:
        if self._last_session_root is None or self._last_session_wave is None:
            self._log("请先长录音或选择会话")
            return
        try:
            if self._last_session_ranges:
                self._persist_ranges(self._last_session_ranges)
        except Exception:
            pass
        try:
            trigger = self._host.ensure_trigger()
            path = resolve_template_path()
            if not trigger.has_template and path is not None:
                trigger.load_template(path)
            if not trigger.has_template:
                self._log("没有模板：请从选区入库")
                return
            root = self._last_session_root

            def work() -> object:
                return trigger.backtest_last_or_dir(root)

            def done(result: object) -> None:
                report = result  # type: ignore[assignment]
                assert isinstance(report, dict)
                hits = list(report.get("hits") or [])
                self.wave.set_hits(hits)
                self.lbl_sess.setText(
                    f"回测命中 {len(hits)} 处（橙）· 人工水花 "
                    f"{len(self._last_session_ranges)} 段"
                )
                text = str(report.get("report_text") or "")
                if text:
                    self._log(text)

            self._run_busy("回测查找中…", work, done)
        except Exception as exc:  # noqa: BLE001
            self._log(f"回测失败：{exc}")

    def _delete_session(self) -> None:
        root = self.cmb_session.currentData()
        if not isinstance(root, Path):
            self._log("请先选择要删除的会话")
            return
        t = self._host.trigger
        if t is not None and t.is_session_recording:
            self._log("长录音进行中，请先停止再删除")
            return
        if (
            QMessageBox.question(self, "删除会话", f"删除 {root.name}？不可恢复")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            delete_session_dir(root)
            if self._last_session_root == root:
                self._last_session_root = None
                self._last_session_wave = None
                self._last_session_ranges = []
                self.wave.clear()
                self.lbl_sess.setText("蓝=选区 · 绿=人工水花 · 橙=回测命中")
            self.refresh_lists()
            self._log(f"已删除会话 {root.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "删除失败", str(exc))
            self._log(f"删除会话失败：{exc}")

    def _on_template_combo(self, _idx: int) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path):
            return
        try:
            set_active_template(path)
            self._host.ensure_trigger().load_template(path)
            self._host.refresh_template_list()
            self._log(f"当前模板：{template_source_label(path)}")
            bundled = is_bundled_template(path)
            self.btn_tmpl_rename.setEnabled(not bundled)
            self.btn_tmpl_del.setEnabled(not bundled)
        except Exception as exc:  # noqa: BLE001
            self._log(f"切换模板失败：{exc}")

    def _tick(self) -> None:
        t = self._host.trigger
        if t is not None:
            for line in t.drain_logs(channel="backtest"):
                self._log(line)
        if t is None or not t.is_session_recording:
            return
        dur = t.session_record_duration_s
        self.lbl_sess.setText(f"长录音中 · {dur:.1f}s")
        self.btn_sess_rec.setText("停止并保存")
        if int(dur * 5) != getattr(self, "_wave_preview_tick", -1):
            self._wave_preview_tick = int(dur * 5)
            prev, sr, ranges = t.session_recording_preview()
            if prev is not None and prev.size > 0:
                self.wave.set_audio(prev, sr, keep_view=True)
                self.wave.set_marks(ranges)

    def _on_wave_selection(self, start_s: float, end_s: float) -> None:
        self.lbl_sel.setText(f"选区：[{start_s:.2f}, {end_s:.2f}]s")

    def _persist_ranges(self, ranges: list[tuple[float, float]]) -> None:
        if self._last_session_root is None or self._last_session_wave is None:
            raise RuntimeError("没有已加载的会话")
        from autofish.first_click_trigger.session_eval import SessionPaths, save_marks

        paths = SessionPaths(
            root=self._last_session_root,
            audio=self._last_session_root / "audio.npy",
            meta=self._last_session_root / "meta.json",
            marks=self._last_session_root / "marks.json",
        )
        save_marks(paths, ranges)
        self._last_session_ranges = list(ranges)
        self.wave.set_marks(ranges)

    def _add_selection_as_mark(self) -> None:
        if self._last_session_wave is None:
            self._log("请先长录音或选择会话")
            return
        a, b = self.wave.selection
        if b - a < 0.05:
            self._log("选区太短")
            return
        try:
            ranges = list(self._last_session_ranges) + [(a, b)]
            self._persist_ranges(ranges)
            self._log(f"已标注水花 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"标注失败：{exc}")

    def _clear_marks(self) -> None:
        if self._last_session_root is None:
            return
        try:
            self._persist_ranges([])
            self._log("已清空标注")
        except Exception as exc:  # noqa: BLE001
            self._log(f"清空失败：{exc}")

    def _add_template_from_selection(self) -> None:
        if self._last_session_wave is None:
            self._log("请先加载会话并拖选")
            return
        a, b = self.wave.selection
        if b - a < 0.05:
            self._log("选区太短")
            return
        try:
            import numpy as np

            trigger = self._host.ensure_trigger()
            wave = np.asarray(self._last_session_wave, dtype=np.float32)
            trigger.replace_template_from_range(
                wave, self._last_session_sr, a, b, save_user=True
            )
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"选区已入库 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"入库失败：{exc}")

    def _play_selection(self) -> None:
        if self._last_session_wave is None or self._last_session_root is None:
            return
        a, b = self.wave.selection
        if b - a < 0.02:
            return
        try:
            import sounddevice as sd
            from autofish.first_click_trigger.session_eval import load_session_raw

            # 原始采集、原音量、系统默认输出
            raw, sr = load_session_raw(self._last_session_root)
            i0 = int(a * sr)
            i1 = int(b * sr)
            sd.stop()
            sd.play(raw[i0:i1].copy(), sr, blocking=False)
            self._log(f"试听选区 [{a:.2f},{b:.2f}]s")
        except Exception as exc:  # noqa: BLE001
            self._log(f"试听失败：{exc}")

    def _play_template(self) -> None:
        try:
            t = self._host.ensure_trigger()
            path = self.cmb_template.currentData()
            if isinstance(path, Path):
                t.load_template(path)
            if not t.has_template:
                raise RuntimeError("没有模板")
            t.play_template()
            self._log("正在播放模板")
        except Exception as exc:  # noqa: BLE001
            self._log(f"播放失败：{exc}")

    def _rename_template(self) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path) or is_bundled_template(path):
            return
        name, ok = QInputDialog.getText(
            self, "改名模板", "新名称（不含扩展名）", text=path.stem
        )
        if not ok or not name.strip():
            return
        try:
            rename_library_template(path, name)
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"已改名 → {name.strip()}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "改名失败", str(exc))

    def _delete_template(self) -> None:
        path = self.cmb_template.currentData()
        if not isinstance(path, Path) or is_bundled_template(path):
            return
        if (
            QMessageBox.question(self, "删除模板", f"删除 {path.name}？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            delete_library_template(path)
            self._host.reload_active_template()
            self._host.refresh_template_list()
            self.refresh_lists()
            self._log(f"已删除 {path.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "删除失败", str(exc))

    def _apply_loaded_session(
        self,
        root: Path,
        wave,
        samplerate: int,
        ranges: list[tuple[float, float]],
    ) -> None:
        import numpy as np

        self._last_session_root = root
        self._last_session_wave = np.asarray(wave, dtype=np.float32)
        self._last_session_sr = int(samplerate)
        self._last_session_ranges = list(ranges)
        dur = float(len(wave) / max(samplerate, 1))
        self.wave.set_audio(self._last_session_wave, self._last_session_sr)
        self.wave.set_marks(ranges)
        self.wave.set_hits([])
        if ranges:
            self.wave.set_selection(ranges[-1][0], ranges[-1][1])
        self.lbl_sess.setText(
            f"{root.name} · {dur:.1f}s · 人工水花 {len(ranges)} 段"
        )

    def _log(self, msg: str) -> None:
        # 只写本页日志，不转发主控
        append_log(self._logs, self.log, msg)

    def shutdown(self) -> None:
        self._timer.stop()
