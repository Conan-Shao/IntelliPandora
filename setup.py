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
Programming Language :: Python :: 3.8
Programming Language :: Python :: 3.9
Programming Language :: Python :: 3.10
Programming Language :: Python :: 3.11
Programming Language :: Python :: 3.12
Programming Language :: Python :: Implementation :: CPython
Topic :: Software Development :: Testing
Topic :: Software Development :: Testing :: Acceptance
Topic :: Software Development :: Testing :: BDD
Topic :: Software Development :: Libraries :: Python Modules
Topic :: Utilities
Framework :: Robot Framework
Framework :: Pytest
""".strip().splitlines()

DESCRIPTION = ("Generic automation framework for system testing and model evaluation")
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
    python_requires='>=3.7',
    url="https://www.python.org/doc/",
    include_package_data=True,
    install_requires=[
        'twine',
        'setuptools',
        'six',
        'pendulum',
        'tabulate',
        'retrying',
        'assertpy',
        'bs4',
        'pluggy',
        'pyyaml',
        'pycryptodome',
        'urllib3',
        'requests',
        'httpretty',
        'websockets',
        'pytest',
        'robotframework',
        'psutil'
    ],
    zip_safe=False,
    classifiers=CLASSIFIERS,
    scripts=['src/ipandora/run/runner.py'],
    entry_points={
        'console_scripts': [
            'ipandora = ipandora.run:command_line',
        ]
    },
)