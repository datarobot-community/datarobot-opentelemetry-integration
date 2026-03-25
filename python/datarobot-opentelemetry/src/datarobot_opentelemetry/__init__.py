from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("datarobot-opentelemetry")
except PackageNotFoundError:
    __version__ = "0.0.0"  # package not installed

from datarobot_opentelemetry.semconv import SpanAttributes

__all__ = ["SpanAttributes", "__version__"]
