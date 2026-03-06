"""Setup script for LTX-2 Dataset Builder."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    long_description = readme_path.read_text()

setup(
    name="ltx2-dataset-builder",
    version="0.1.0",
    description="Automated training data extraction for LTX-2 character LoRA training",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="LTX-2 Dataset Builder Team",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=[
        "scenedetect[opencv]>=0.6.2",
        "opencv-python>=4.8.0",
        "insightface>=0.7.3",
        "onnxruntime-gpu>=1.16.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.3.0",
        "PyYAML>=6.0",
        "tqdm>=4.66.0",
        "Pillow>=10.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
        ],
        "cpu": [
            "onnxruntime>=1.16.0",  # CPU-only version
        ],
    },
    entry_points={
        "console_scripts": [
            "ltx2-build=ltx2_dataset_builder.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Multimedia :: Video",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
