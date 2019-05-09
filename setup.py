#! /usr/bin/env python3

import os.path
from setuptools import setup, find_packages
import magictag

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='magictag',
    version=magictag.__version__,

    description=magictag.__doc__.strip().split('\n\n', 1)[0],
    long_description=long_description,

    url='https://github.com/MrDOS/magictag',

    author=magictag.__author__,
    author_email=magictag.__contact__,

    license=magictag.__license__,

    packages=['magictag'],
    entry_points = {'console_scripts': ['magictag=magictag:main']},

    install_requires=['chardet', 'mutagen', 'titlecase'],
    extras_require={'album art': ['python-itunes']}
)
