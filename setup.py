#!/usr/bin/env python
import os
from setuptools import setup, find_packages


with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as f:
    long_description = f.read()


setup(
    name='pymux',
    author='Jonathan Slenders',
    version='0.14',
    license='LICENSE',
    url='https://github.com/jonathanslenders/',
    description='Pure Python terminal multiplexer.',
    long_description=long_description,
    packages=find_packages('.'),
    install_requires = [
        'prompt_toolkit>=2.0.0,<2.1.0',
        'ptterm',
        'six>=1.9.0',
        'docopt>=0.6.2',
    ],
    entry_points={
        'console_scripts': [
            'pymux = pymux.entry_points.run_pymux:run',
        ]
    },
)
