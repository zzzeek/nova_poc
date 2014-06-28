import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

requires = [
    'nova',
    'SQLAlchemy >= 0.8.5, <= 0.9.9',
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
    entry_points={
        'console_scripts': ['nova-poc = nova_poc.main']
    }
)

