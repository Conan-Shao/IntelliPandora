# Makefile for Python project packaging
.PHONY: install install-tools locks security docs docs-write test smoke test-without-ai package clean
# Define some variables
PYTHON := python3
PIP := pip3
TARGET_DIR := dist

# 安装开发环境：与 CI 完全相同的锁定版本，逐个文件校验哈希
# 依赖变了先 make locks，见 docs/design/decisions/15-第三方组件安全准入与漏洞扫描.md
install:
	$(PIP) install --require-hashes -r requirements/ci.txt
	$(PIP) install --no-deps --no-build-isolation -e .

# 构建与扫描工具（pip-audit、bandit、build、uv……），同样锁定并校验哈希
install-tools:
	$(PIP) install --require-hashes -r requirements/tools.txt

# 重新生成锁文件：只接受发布满 14 天的版本
locks:
	$(PYTHON) scripts/update_locks.py

# 本地跑一遍与 CI 相同的安全扫描，并更新 docs/security/report.md
# 需要 make install install-tools（同一环境即可）
security:
	$(PYTHON) scripts/check_components.py
	$(PYTHON) scripts/security_report.py

# 运行测试
test:
	pytest test/

# 冒烟：确认每个模块都能被 import
# v1.1.0 曾发布过 import 即崩溃的模块，这一步就是防它重演
smoke:
	$(PYTHON) scripts/smoke_import.py

# LLM 必须是可拆卸的：删掉 ai/ 之后测试仍须全绿
# 见 docs/design/decisions/03-LLM接入边界.md
test-without-ai:
	rm -rf /tmp/ipandora-noai && cp -r . /tmp/ipandora-noai
	rm -rf /tmp/ipandora-noai/src/ipandora/ai
	cd /tmp/ipandora-noai && pytest test/

# 文档门禁：链接有效，docs/reference/ 与代码一致；改了 CLI 参数或 config.yaml 后用 make docs-write
docs:
	$(PYTHON) scripts/check_docs.py

docs-write:
	$(PYTHON) scripts/check_docs.py --write

# 打包项目（需要 make install-tools）。发布到 PyPI 只走 .github/workflows/release.yml：
# 本地没有、也不应该有 PyPI 凭据
package:
	rm -rf build/ dist/ src/*.egg-info
	$(PYTHON) -m build --no-isolation
	$(PYTHON) scripts/check_packaging.py dist/*.whl

# 清理临时文件
clean:
	rm -rf build/ dist/ src/*.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
