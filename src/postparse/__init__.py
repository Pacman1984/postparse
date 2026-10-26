"""PostParse: collect, search and analyze saved social media posts."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("postparse")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
