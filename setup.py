# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

# distutils setup script.
# users should install with: `$ pip3 install writeup-tool`
# developers can make a local install with: `$ pip3 install -e .`
# upload to pypi test server with: `$ py3 setup.py sdist upload -r pypitest`
# upload to pypi prod server with: `$ py3 setup.py sdist upload`

from setuptools import setup


setup(
  name='writeup-tool',
  license='CC0',
  version='0.0.1',
  author='George King',
  author_email='george.w.king@gmail.com',
  url='https://github.com/gwk/writeup',
  description='Writeup is a text markup format and standalone tool that translates to HTML5.',
  packages=['writeup'],
  entry_points = {'console_scripts': ['writeup=writeup.v0:main']},
  keywords=[
    'documentation', 'markup'
  ],
  classifiers=[ # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    'Development Status :: 3 - Alpha',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'Intended Audience :: Education',
    'Intended Audience :: Information Technology',
    'Intended Audience :: Science/Research',
    'License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication',
    'Programming Language :: Python :: 3 :: Only',
    'Topic :: Documentation',
    'Topic :: Education',
    'Topic :: Multimedia',
    'Topic :: Software Development',
    'Topic :: Software Development :: Documentation',
    'Topic :: Text Processing :: Markup',
    'Topic :: Text Processing :: Markup :: HTML',
  ],
)
