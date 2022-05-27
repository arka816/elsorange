from setuptools import setup

setup(
        name="Demo",
        packages=["elsevier"],
        package_data={"elsevier": ["icons/*.svg"]},
        classifiers=["Example :: Invalid"],
        # Declare orangedemo package to contain widgets for the "Demo" category
        entry_points={"orange.widgets": "Demo = elsevier"},
    )
    