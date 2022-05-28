from setuptools import setup
import os

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
        name="Dev",
        version="0.0.1",
        author="Arka",
        author_email="arkaprava.mail@gmail.com",
        license="MIT",
        long_description=read('README.md'),
        packages=["elsevier"],
        package_data={"elsevier": ["icons/*.svg"]},
        entry_points={"orange.widgets": "Dev = elsevier"},
        zip_safe=False,
    )
    