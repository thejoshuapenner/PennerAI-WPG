from setuptools import setup, find_packages

setup(
    name="membrane",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.25.0"
    ],
    description="Thin adapter client to membrane-api.com",
    author="PennerAI Team"
)
