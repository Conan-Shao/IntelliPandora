# Makefile for Python project packaging
.PHONY: install test package clean
# Define some variables
PYTHON := python3
PIP := pip3
TARGET_DIR := dist

# 安装所有依赖
install:
	pip install -r requirements.txt

# 运行测试
test:
	pytest test/

# 冒烟：确认每个模块都能被 import
# v1.1.0 曾发布过 import 即崩溃的模块，这一步就是防它重演
smoke:
	$(PYTHON) scripts/smoke_import.py

# LLM 必须是可拆卸的：删掉 ai/ 之后测试仍须全绿
# 见 docs/design/03-LLM接入边界.md
test-without-ai:
	rm -rf /tmp/ipandora-noai && cp -r . /tmp/ipandora-noai
	rm -rf /tmp/ipandora-noai/src/ipandora/ai
	cd /tmp/ipandora-noai && pytest test/

# 打包项目
package:
	$(PYTHON) setup.py sdist bdist_wheel

# 清理临时文件
clean:
	rm -rf build/ dist/ src/*.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete

# Upload the wheel file to PyPI (requires credentials)
upload: package
	twine upload -r pypi dist/*.whl

check:
	twine check dist/*