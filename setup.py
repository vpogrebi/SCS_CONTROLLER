from setuptools import setup, find_packages
import sys, os

version = '0.1'

setup(name = 'scs',
      version = version,
      description = "SCS Controller System'",
      author = 'Valeriy Pogrebitskiy',
      author_email = 'vpogrebi@iname.com',
      url = '',
      zip_safe = False,
      package_dir = {'': 'python'},
      packages = ['', 'test'],
      install_requires = [
          # -*- Extra requirements: -*-
          'twisted >= 8.2.0',
          'zope.interface',
          'mysql-python',
      ],
      test_suite = 'python/test/controller_test.py'
      )
