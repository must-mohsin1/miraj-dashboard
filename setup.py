from setuptools import find_packages, setup

setup(
    name="mirai_core",
    version="0.1.0",
    description="Crypto trading analysis engine — indicators, SMC, patterns, confluence scoring, trade plans",
    packages=find_packages(include=["mirai_core", "mirai_core.*"]),
    python_requires=">=3.10",
    install_requires=[
        "pandas>=1.3",
        "numpy>=1.21",
        "scipy>=1.7",
        "yfinance>=0.2",
        "requests>=2.28",
        "pytz>=2022",
        "mplfinance>=0.12.0a0",
        "plotly>=5.9",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
