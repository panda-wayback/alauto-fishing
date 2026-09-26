# albn-fishing — 常用命令
# 用法: make help
# 发版: make release                 # 自动递增 patch（v0.1.0 → v0.1.1）
#       make release VERSION=1.0.0   # 指定版本

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

# 可选覆盖：VERSION=0.2.0 或 VERSION=v0.2.0
VERSION ?=
# 密钥 CLI：DAYS=7 COUNT=1
DAYS ?= 30
COUNT ?= 1

.PHONY: help install sim preview algo \
	license-ui gen-license \
	build-macos build-macos-dev build-license-macos build-windows \
	open-app open-app-dev open-license-app \
	reset-perms clean release next-version

help:
	@echo "PY = $(PY)"
	@echo ""
	@echo "运行"
	@echo "  make install         安装 requirements.txt"
	@echo "  make sim             启动模拟器 (main.py)"
	@echo "  make preview         启动真机预览壳 (--ui)"
	@echo "  make algo            无头跑策略 (tier=4 episodes=50)"
	@echo ""
	@echo "密钥（本机发密钥，勿给用户）"
	@echo "  make license-ui      打开密钥生成窗"
	@echo "  make gen-license     CLI 生成（DAYS=30 COUNT=1）"
	@echo "  make build-license-macos  打密钥生成器 .app（仅 macOS）"
	@echo "  make open-license-app     打开刚打的密钥生成器 .app"
	@echo ""
	@echo "打包"
	@echo "  make build-macos     打正式 .app（带唯一后缀）"
	@echo "  make build-macos-dev 打开发 .app（独立 Bundle + 唯一后缀）"
	@echo "  make build-windows   打 Windows 包（须在 Windows 上）"
	@echo "  make open-app / open-app-dev"
	@echo "  make reset-perms     清除 macOS 屏幕录制/辅助功能 TCC 记录"
	@echo "  make clean           清理 build/ dist/ 与 __pycache__"
	@echo ""
	@echo "发版"
	@echo "  make next-version    显示下一个自动 tag（不推送）"
	@echo "  make release         自动打下一版 tag 并 push → GitHub Release"
	@echo "  make release VERSION=1.0.0   指定版本发版"
	@echo ""
	@echo "CI（GitHub Actions）："
	@echo "  push main  → 构建 macOS + Windows artifact"
	@echo "  tag vX.Y.Z → 构建并上传 GitHub Release"

install:
	$(PY) -m pip install -r $(ROOT)/requirements.txt

sim:
	$(PY) $(ROOT)/main.py

preview:
	$(PY) -m autofish.preview --ui

algo:
	$(PY) -m algo --tier 4 --episodes 50

license-ui:
	$(PY) $(ROOT)/packaging/gen_license_ui.py

gen-license:
	$(PY) $(ROOT)/packaging/gen_license_key.py $(DAYS) --count $(COUNT)

build-macos:
	bash $(ROOT)/packaging/build_macos.sh

# 本地反复测包：独立名字 + Bundle ID，避免和正式包/旧包抢 TCC
build-macos-dev:
	ALBN_BUNDLE_ID=com.albn.autofish.dev \
	ALBN_APP_NAME=albn-autofish-dev.app \
	ALBN_DISPLAY_NAME='Albn Autofish Dev' \
	bash $(ROOT)/packaging/build_macos.sh

build-license-macos:
	bash $(ROOT)/packaging/build_license_macos.sh

build-windows:
	bash $(ROOT)/packaging/build_windows.sh

open-app:
	@if [ ! -f $(ROOT)/dist/.build_macos_name ]; then echo "请先 make build-macos"; exit 1; fi; \
	open "$(ROOT)/dist/$$(cat $(ROOT)/dist/.build_macos_name)"

open-app-dev:
	@APP=$$(ls -td $(ROOT)/dist/albn-autofish-dev-*.app 2>/dev/null | head -n1); \
	if [ -z "$$APP" ]; then echo "请先 make build-macos-dev"; exit 1; fi; \
	open "$$APP"

open-license-app:
	@if [ ! -f $(ROOT)/dist/.build_keygen_macos_name ]; then echo "请先 make build-license-macos"; exit 1; fi; \
	open "$(ROOT)/dist/$$(cat $(ROOT)/dist/.build_keygen_macos_name)"

reset-perms:
	bash $(ROOT)/packaging/reset_macos_perms.sh

clean:
	rm -rf $(ROOT)/build $(ROOT)/dist
	find $(ROOT) -type d -name __pycache__ -not -path '*/.conda/*' -not -path '*/.venv/*' -exec rm -rf {} + 2>/dev/null || true

# 计算下一个 tag：无 v* → v0.1.0；否则 patch+1（v1.2.3 → v1.2.4）
define NEXT_TAG_CMD
LATEST=$$(git tag -l 'v*' --sort=-v:refname | head -n1); \
if [ -n "$(VERSION)" ]; then \
  case "$(VERSION)" in v*) TAG="$(VERSION)" ;; *) TAG="v$(VERSION)" ;; esac; \
elif [ -z "$$LATEST" ]; then \
  TAG=v0.1.0; \
else \
  TAG=$$(echo "$$LATEST" | sed 's/^v//' | awk -F. '{printf "v%d.%d.%d\n", $$1, $$2, $$3+1}'); \
fi
endef

next-version:
	@$(NEXT_TAG_CMD); \
	LATEST=$$(git tag -l 'v*' --sort=-v:refname | head -n1); \
	echo "最新 tag: $${LATEST:-（无）}"; \
	echo "下一版:   $$TAG"

release:
	@$(NEXT_TAG_CMD); \
	echo "将创建并推送 tag: $$TAG"; \
	if git rev-parse --verify "$$TAG" >/dev/null 2>&1; then \
	  echo "错误: tag $$TAG 已存在"; exit 1; \
	fi; \
	if git status --porcelain | grep -q .; then \
	  echo "警告: 工作区有未提交改动，仍继续打 tag（指向当前 HEAD）"; \
	fi; \
	git tag "$$TAG"; \
	git push origin "$$TAG"; \
	echo "已推送 $$TAG。到 GitHub Actions / Releases 查看构建。"
