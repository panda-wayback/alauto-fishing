"""模板库下拉：填充 / 选中同步（开钓页与回测页共用）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox

from autofish.first_click_trigger.paths import (
    list_library_templates,
    resolve_template_path,
    template_source_label,
)


def fill_template_combo(combo: QComboBox) -> Path | None:
    """清空并填入库内模板；选中当前 active；返回当前 Path 或 None。"""
    active = resolve_template_path()
    combo.blockSignals(True)
    combo.clear()
    sel = 0
    for i, p in enumerate(list_library_templates()):
        combo.addItem(template_source_label(p), p)
        try:
            if active is not None and p.resolve() == active.resolve():
                sel = i
        except OSError:
            if active is not None and p == active:
                sel = i
    if combo.count() > 0:
        combo.setCurrentIndex(sel)
    combo.blockSignals(False)
    path = combo.currentData()
    return path if isinstance(path, Path) else None


def sync_combo_to_path(combo: QComboBox, path: Path) -> None:
    combo.blockSignals(True)
    for i in range(combo.count()):
        p = combo.itemData(i)
        if not isinstance(p, Path):
            continue
        try:
            if p.resolve() == path.resolve():
                combo.setCurrentIndex(i)
                break
        except OSError:
            if p == path:
                combo.setCurrentIndex(i)
                break
    combo.blockSignals(False)
