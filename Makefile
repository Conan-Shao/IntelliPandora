# Makefile for Python project packaging
.PHONY: install test package clean
# Define some variables
PYTHON := python3
PIP := pip3
TARGET_DIR := dist

# 安装所有依赖
install:
	pip install -r requirements_dev.txt

# 运行测试
test:
	pytest tests/

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