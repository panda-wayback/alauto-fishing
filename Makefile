# albn-fishing — 常用命令
# 用法: make help

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PYTHONPATH := $(ROOT)/src

ifeq ($(wildcard $(ROOT)/.conda/bin/python),)
  ifeq ($(wildcard $(ROOT)/.venv/bin/python),)
    PY := python3
  else
    PY := $(ROOT)/.venv/bin/python
  endif
else
  PY := $(ROOT)/.conda/bin/python
endif

.PHONY: help install sim preview algo build-macos build-windows open-app clean

help:
	@echo "PY = $(PY)"
	@echo ""
	@echo "  make install        安装 requirements.txt"
	@echo "  make sim            启动模拟器 (main.py)"
	@echo "  make preview        启动真机预览壳 (--ui)"
	@echo "  make algo           无头跑策略 (tier=4 episodes=50)"
	@echo "  make build-macos    打 macOS .app → dist/albn-autofish.app"
	@echo "  make build-windows  打 Windows 包（须在 Windows 上）"
	@echo "  make open-app       打开已打包的 .app"
	@echo "  make clean          清理 build/ dist/ 与 __pycache__"
	@echo ""
	@echo "Release（GitHub Actions）："
	@echo "  git tag v0.1.0 && git push origin v0.1.0"
	@echo "  → 构建 macOS arm64 + Windows x64 zip 并上传到 GitHub Release"

install:
	$(PY) -m pip install -r $(ROOT)/requirements.txt

sim:
	$(PY) $(ROOT)/main.py

preview:
	$(PY) -m autofish.preview --ui

algo:
	$(PY) -m algo --tier 4 --episodes 50

build-macos:
	bash $(ROOT)/packaging/build_macos.sh

build-windows:
	bash $(ROOT)/packaging/build_windows.sh

open-app:
	open $(ROOT)/dist/albn-autofish.app

clean:
	rm -rf $(ROOT)/build $(ROOT)/dist
	find $(ROOT) -type d -name __pycache__ -not -path '*/.conda/*' -not -path '*/.venv/*' -exec rm -rf {} + 2>/dev/null || true
