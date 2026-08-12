"""
AoiDrawTool and AoiWidget — drop-in replacement for QgsExtentWidget
that lets users draw an AOI rectangle interactively on the map canvas.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..logger import get_logger

logger = get_logger('gui.aoi_draw_tool')

try:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsGeometry,
        QgsPointXY,
        QgsRectangle,
        QgsWkbTypes,
    )
    from qgis.gui import QgsMapTool, QgsRubberBand
    from qgis.PyQt.QtGui import QColor
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
    QgsMapTool = object  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Map tool
# ---------------------------------------------------------------------------

class RectangleDrawTool(QgsMapTool):  # type: ignore[misc]
    """
    Interactive rubber-band rectangle drawing tool.

    On mouse-press → records the start corner.
    On mouse-move  → updates the rubber-band preview.
    On mouse-release → emits *rectangleDrawn* with the final QgsRectangle
                       (in canvas CRS) and restores the previous map tool.
    """

    rectangleDrawn = pyqtSignal(object)  # emits QgsRectangle

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._start_point: 'QgsPointXY | None' = None
        self._rubber_band: 'QgsRubberBand | None' = None
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    # QgsMapTool events
    # ------------------------------------------------------------------

    def canvasPressEvent(self, event):
        self._start_point = self.toMapCoordinates(event.pos())
        self._rubber_band = QgsRubberBand(self._canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber_band.setColor(QColor(255, 50, 50, 100))
        self._rubber_band.setFillColor(QColor(255, 50, 50, 30))
        self._rubber_band.setWidth(2)

    def canvasMoveEvent(self, event):
        if self._start_point is None or self._rubber_band is None:
            return
        self._update_rubber_band(self.toMapCoordinates(event.pos()))

    def canvasReleaseEvent(self, event):
        if self._start_point is None:
            return
        end = self.toMapCoordinates(event.pos())
        self._update_rubber_band(end)

        rect = QgsRectangle(self._start_point, end)
        self._reset()

        if not rect.isEmpty():
            self.rectangleDrawn.emit(rect)

        # Deactivate ourselves so the previous tool is restored by AoiWidget
        self._canvas.unsetMapTool(self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_rubber_band(self, end: 'QgsPointXY'):
        if self._rubber_band is None or self._start_point is None:
            return
        s, e = self._start_point, end
        self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        ring = [
            QgsPointXY(s.x(), s.y()),
            QgsPointXY(e.x(), s.y()),
            QgsPointXY(e.x(), e.y()),
            QgsPointXY(s.x(), e.y()),
        ]
        self._rubber_band.setToGeometry(QgsGeometry.fromPolygonXY([ring]), None)

    def _reset(self):
        if self._rubber_band:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self._rubber_band = None
        self._start_point = None

    def deactivate(self):
        self._reset()
        super().deactivate()


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class AoiWidget(QWidget):
    """
    AOI definition widget with interactive map-canvas drawing.

    Drop-in replacement for QgsExtentWidget.  Supports:

    * **Draw on Map** — click and drag a rectangle on the canvas.
    * **Current View** — snap the AOI to the current map extent.
    * **Clear** — remove the AOI.

    Compatible subset of QgsExtentWidget's API
    -------------------------------------------
    setMapCanvas(canvas)
    setCurrentExtent(extent, crs)
    setOriginalExtent(extent, crs)
    setOutputCrs(crs)
    outputExtent()  -> QgsRectangle | None
    outputCrs()     -> QgsCoordinateReferenceSystem
    extentChanged   (signal)
    """

    extentChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None
        self._crs: 'QgsCoordinateReferenceSystem | None' = None
        self._extent: 'QgsRectangle | None' = None
        self._draw_tool: 'RectangleDrawTool | None' = None

        # ---- Layout ------------------------------------------------
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._draw_btn = QPushButton('✏ Draw on Map')
        self._draw_btn.setToolTip('Click and drag on the map canvas to define the AOI rectangle')
        self._draw_btn.setCheckable(True)
        self._draw_btn.clicked.connect(self._on_draw_clicked)
        btn_row.addWidget(self._draw_btn)

        self._view_btn = QPushButton('⌖ Current View')
        self._view_btn.setToolTip('Set AOI to the current map view extent')
        self._view_btn.clicked.connect(self._on_use_view)
        btn_row.addWidget(self._view_btn)

        self._clear_btn = QPushButton('✕ Clear')
        self._clear_btn.setToolTip('Remove the current AOI definition')
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)

        outer.addLayout(btn_row)

        self._coords_label = QLabel('No AOI defined')
        self._coords_label.setWordWrap(True)
        self._coords_label.setStyleSheet('font-size: 9px; color: #555555;')
        outer.addWidget(self._coords_label)

    # ------------------------------------------------------------------
    # QgsExtentWidget-compatible API
    # ------------------------------------------------------------------

    def setMapCanvas(self, canvas):
        """Attach the widget to a map canvas (required for drawing)."""
        self._canvas = canvas

    def setOutputCrs(self, crs):
        """
        Set the preferred output CRS.
        Only applied when no extent is stored yet; once an extent is
        drawn or initialised the stored draw-CRS is authoritative and
        must not be silently overwritten (otherwise reprojection in
        _get_aoi_bbox_wgs84 would use the wrong source CRS).
        """
        if self._extent is None:
            self._crs = crs

    def setExtent(self, extent, crs):
        """
        Unconditionally set the AOI extent and its source CRS.
        Use this for external pre-fill (e.g. from Search and Predict) where
        the caller already knows the exact extent and CRS.
        """
        if extent and not extent.isEmpty() and crs and crs.isValid():
            self._extent = extent
            self._crs = crs
            self._refresh_display()
            self.extentChanged.emit()

    def outputCrs(self) -> 'QgsCoordinateReferenceSystem':
        """Return the output CRS (falls back to canvas CRS or EPSG:4326)."""
        if self._crs and self._crs.isValid():
            return self._crs
        if self._canvas:
            return self._canvas.mapSettings().destinationCrs()
        return QgsCoordinateReferenceSystem('EPSG:4326')

    def setCurrentExtent(self, extent, crs):
        """
        Set (and display) an initial extent.
        Only replaces the stored extent when none is defined yet, so
        repeated calls to setCurrentExtent after a user draw do not
        discard the drawn AOI.
        """
        if self._extent is None and extent and not extent.isEmpty():
            self._extent = extent
            self._crs = crs
            self._refresh_display()

    def setOriginalExtent(self, extent, crs):
        """
        Store the 'original' / reset extent.
        Initialises the stored extent if nothing is defined yet.
        """
        if self._extent is None and extent and not extent.isEmpty():
            self._extent = extent
            self._crs = crs
            self._refresh_display()

    def outputExtent(self) -> 'QgsRectangle | None':
        """Return the currently defined AOI extent, or None if not set."""
        return self._extent

    # ------------------------------------------------------------------
    # Button slots
    # ------------------------------------------------------------------

    def _on_draw_clicked(self, checked: bool):
        if not QGIS_AVAILABLE or self._canvas is None:
            self._draw_btn.setChecked(False)
            logger.warning('AoiWidget: map canvas not available for drawing')
            return

        if checked:
            self._draw_tool = RectangleDrawTool(self._canvas)
            self._draw_tool.rectangleDrawn.connect(self._on_rectangle_drawn)
            self._draw_tool.deactivated.connect(self._on_tool_deactivated)
            self._canvas.setMapTool(self._draw_tool)
            self._draw_btn.setText('… Drawing (drag on map)')
            logger.debug('AoiWidget: rectangle draw tool activated')
        else:
            self._cancel_drawing()

    def _cancel_drawing(self):
        if self._canvas and self._draw_tool:
            self._canvas.unsetMapTool(self._draw_tool)
        self._draw_tool = None
        self._draw_btn.setChecked(False)
        self._draw_btn.setText('✏ Draw on Map')

    def _on_tool_deactivated(self):
        """Handles Escape / external tool change while drawing."""
        self._draw_btn.setChecked(False)
        self._draw_btn.setText('✏ Draw on Map')
        self._draw_tool = None

    def _on_rectangle_drawn(self, rect: 'QgsRectangle'):
        self._extent = rect
        if self._canvas:
            self._crs = self._canvas.mapSettings().destinationCrs()
        self._draw_btn.setChecked(False)
        self._draw_btn.setText('✏ Draw on Map')
        self._draw_tool = None
        self._refresh_display()
        self.extentChanged.emit()
        logger.debug(f'AoiWidget: AOI drawn — {rect}')

    def _on_use_view(self):
        if self._canvas is None:
            return
        self._extent = self._canvas.extent()
        self._crs = self._canvas.mapSettings().destinationCrs()
        self._refresh_display()
        self.extentChanged.emit()
        logger.debug('AoiWidget: AOI set to current view')

    def _on_clear(self):
        self._extent = None
        self._coords_label.setText('No AOI defined')
        self.extentChanged.emit()
        logger.debug('AoiWidget: AOI cleared')

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _refresh_display(self):
        if self._extent is None or self._extent.isEmpty():
            self._coords_label.setText('No AOI defined')
            return
        e = self._extent
        crs_id = self._crs.authid() if self._crs and self._crs.isValid() else '?'
        self._coords_label.setText(
            f'W: {e.xMinimum():.5f}   E: {e.xMaximum():.5f}\n'
            f'S: {e.yMinimum():.5f}   N: {e.yMaximum():.5f}\n'
            f'CRS: {crs_id}'
        )
