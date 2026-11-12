"""Legacy fallback alias for the main Altair dock.

Historically this module contained a separate fallback implementation.
It now re-exports the primary dock widget to keep imports stable across
Qt5/Qt6 runtimes without maintaining duplicate UI code.
"""

from .dock import AltairDockWidget

__all__ = ['AltairDockWidget']
