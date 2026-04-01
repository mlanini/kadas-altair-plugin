"""
KADAS Altair Plugin - GUI Modules
"""

from .dock import AltairDockWidget
from .settings_dock import SettingsDockWidget
from .log_viewer import LogViewerDialog
from .tasking_dock import TaskingDockWidget
from .archive_dock import ArchiveDockWidget
from .smart_tasking_dock import SmartTaskingDockWidget

__all__ = [
    'AltairDockWidget',
    'SettingsDockWidget',
    'LogViewerDialog',
    'TaskingDockWidget',
    'ArchiveDockWidget',
    'SmartTaskingDockWidget',
]
