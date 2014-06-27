import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

requires = [
    'nova',
    'sqlalchemy >= 0.8.5',
    'MySQL-python'
    ]

setup(name='nova_poc',
      version='1.0',
      description='proof of concept for SQLAlchemy ORM optimizations',
      classifiers=[
        "Programming Language :: Python",
        ],
      author='mike bayer',
      author_email='mike_mp@zzzcomputing.com',
      url='',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=["nose", "mock"],
      test_suite="atmcraft",
      entry_points = {
        'console_scripts': ['console = nova_poc.main'],
      }

      )classics-MacBook-Pro-2:atmcraft classic$
