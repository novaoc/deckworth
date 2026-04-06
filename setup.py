from setuptools import setup

setup(
    name="deckworth",
    version="1.0.0",
    description="Calculate the market value of a Pokemon TCG deck",
    author="Nova",
    author_email="novaoc@users.noreply.github.com",
    url="https://github.com/novaoc/deckworth",
    py_modules=["deckworth"],
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "deckworth=deckworth:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Topic :: Games/Entertainment :: Role-Playing",
        "Topic :: Utilities",
    ],
)
