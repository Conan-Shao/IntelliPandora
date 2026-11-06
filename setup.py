#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
@Author  :  shaofeng
@Time    :  2020/1/7
@File    ： setup.py 
"""
import os
from setuptools import setup, find_packages
try:
    from ipandora.version import get_latest_version
except ImportError:
    get_latest_version = None

# Reload version.py and get the latest version from CHANGELOG
here = os.path.abspath(os.path.dirname(__file__))
_fpt_path = os.path.abspath(os.path.join(here, 'src/ipandora'))
_version_path = os.path.join(_fpt_path, "version.py")
with open(_version_path, 'rb') as f:
    # version = str(ast.literal_eval(_version_re.search(
    #     f.read().decode('utf-8')).group(1)))
    exec(f.read())
    version = get_latest_version(_fpt_path)
CLASSIFIERS = """
Development Status :: 4 - Beta
License :: OSI Approved :: Apache Software License
Operating System :: OS Independent
Programming Language :: Python :: 3
Programming Language :: Python :: 3 :: Only
Programming Language :: Python :: 3.10
Programming Language :: Python :: 3.11
Programming Language :: Python :: 3.12
Programming Language :: Python :: Implementation :: CPython
Topic :: Software Development :: Testing
Topic :: Software Development :: Testing :: Acceptance
Topic :: Software Development :: Testing :: BDD
Topic :: Software Development :: Libraries :: Python Modules
Topic :: Utilities
Framework :: Pytest
""".strip().splitlines()

DESCRIPTION = ("General-purpose test framework on pytest: deterministic verdicts, "
               "failure triage, reports, and an MCP entry point for AI agents")
with open(os.path.join(here, 'README.md')) as f:
    LONG_DESCRIPTION = f.read()

setup(
    name="intellipandora",
    version=version,
    author="Shao Feng",
    author_email="just.shao.007@gmail.com",
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    keywords="intellipandora",
    packages=find_packages('src'),
    package_data={"": ["LICENSE"]},
    package_dir={"": "src"},
    license='Apache License 2.0',
    python_requires='>=3.10',
    url="https://github.com/Conan-Shao/IntelliPandora",
    include_package_data=True,
    zip_safe=False,
    classifiers=CLASSIFIERS,
    # Bounded like install_requires, and for the same reason. `ai` stays an
    # extra because `rm -rf ai/ && pytest` staying green is a structural
    # guarantee, not a convention -- see docs/design/decisions/03-LLM接入边界.md.
    extras_require={
        # >=2.1: the 2.x line is what is tested; 1.x never was. Admitted 2026-11-05,
        # see docs/security/components.md.
        'ai': ['anthropic>=2.1,<3'],
        # `ipandora run --workers`, @pytest.mark.resource and --timeout. Kept
        # out of the core: a serial run needs none of it. See
        # docs/design/decisions/14 §1 and docs/security/components.md.
        'parallel': ['pytest-xdist>=3.8,<4', 'pytest-timeout>=2.4,<3'],
        # Web: Playwright and its official pytest plugin, used as they are
        # (docs/design/decisions/14 §3). pytest-playwright is 0.x, so bounded to one
        # minor. Browsers are a separate download pinned by the Playwright
        # version: python -m playwright install chromium.
        'web': ['playwright>=1.64,<2', 'pytest-playwright>=0.10,<0.11'],
        # Image verdicts, matches_golden() (docs/design/decisions/14 §4). Pillow 13 needs
        # Python 3.11, so 12 stays allowed for 3.10.
        'visual': ['pillow>=12,<14', 'pixelmatch>=0.4,<0.5'],
        # >=2: core/mcp/server.py imports mcp.server.mcpserver.MCPServer, which
        # only 2.x has. This said <2 from 1.11.0 on, so `pip install
        # intellipandora[mcp]` resolved to mcp 1.x and `ipandora mcp` failed
        # at import. The development environment happened to carry 2.3.0, which
        # hid it; installing from the hash-pinned lock is what exposed it.
        'mcp': ['mcp>=2.0,<3'],
        # SystemInfo's memory/network/process helpers. Nothing in the
        # framework calls them, so psutil is not installed by default.
        'system': ['psutil>=5.9,<8'],
        'test': ['httpretty>=1.1,<2'],
        # The Inspect path of agent evaluation (docs/design/decisions/13 §3, E1):
        # read Inspect logs, wrap graders as Inspect scorers. inspect_ai needs
        # Python 3.11, so the extra installs nothing on 3.10. 0.x and released
        # often, so bounded to the 0.3 line. See docs/security/components.md.
        'inspect': ['inspect_ai>=0.3.283,<0.4; python_version >= "3.11"'],
    },
    entry_points={
        'console_scripts': [
            'ipandora = ipandora.run:command_line',
        ]
    },
)