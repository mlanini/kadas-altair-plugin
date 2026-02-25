"""
Footprint Selection Tool for interactive map selection
"""
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.gui import QgsMapTool

try:
    from qgis.core import (
        QgsCoordinateTransform,
        QgsFeatureRequest,
        QgsGeometry,
        QgsProject
    )
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False

from ..logger import get_logger

logger = get_logger('gui.footprint_tool')


class FootprintSelectionTool(QgsMapTool):
    """Custom map tool for selecting footprints interactively."""
    
    selectionModeChanged = pyqtSignal(bool)  # True when active, False when inactive
    
    def __init__(self, canvas, layer):
        """Initialize the selection tool.
        
        Args:
            canvas: The KADAS/QGIS map canvas
            layer: The footprints vector layer
        """
        super().__init__(canvas)
        self.layer = layer
        self.canvas = canvas
        self.setCursor(Qt.CrossCursor)
        self.is_active = False
        logger.info("FootprintSelectionTool initialized")
    
    def canvasPressEvent(self, e):
        """Handle mouse press on canvas."""
        if not self.layer:
            logger.warning("Layer is not set")
            return
        
        if not QGIS_AVAILABLE:
            logger.error("QGIS core modules not available")
            return
        
        try:
            # Get point from mouse event in canvas CRS
            point_canvas = self.toMapCoordinates(e.pos())
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            layer_crs = self.layer.crs()
            logger.info(
                f"Canvas click at: ({point_canvas.x():.6f}, {point_canvas.y():.6f}) in {canvas_crs.authid()}"
            )

            # Transform point to layer CRS if needed
            point_layer = point_canvas
            if canvas_crs != layer_crs:
                try:
                    to_layer = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                    point_layer = to_layer.transform(point_canvas)
                    logger.debug(
                        f"Transformed click to layer CRS {layer_crs.authid()}: "
                        f"({point_layer.x():.6f}, {point_layer.y():.6f})"
                    )
                except Exception as transform_error:
                    logger.error(f"CRS transform failed: {transform_error}", exc_info=True)
                    return
            
            # Adaptive buffer size: ~10m in meters or ~0.0001 deg in geographic
            if layer_crs.isGeographic():
                buffer_size = 0.0001
            else:
                buffer_size = 10.0

            point_geom = QgsGeometry.fromPointXY(point_layer)
            buffered_point = point_geom.buffer(buffer_size, 8)
            
            # Search only nearby features using bounding box filter
            request = QgsFeatureRequest().setFilterRect(buffered_point.boundingBox())
            features_at_point = []
            min_distance = float("inf")
            closest_feature = None
            
            try:
                for feature in self.layer.getFeatures(request):
                    geom = feature.geometry()
                    if geom is None:
                        continue
                    
                    if geom.intersects(buffered_point):
                        fid = feature.id()
                        distance = geom.distance(point_geom)
                        logger.debug(f"Feature {fid} intersects buffer, distance: {distance:.6f}")
                        
                        if distance < min_distance:
                            min_distance = distance
                            closest_feature = fid
                
                if closest_feature is not None:
                    features_at_point = [closest_feature]
                    logger.info(
                        f"Found closest intersecting feature {closest_feature} at distance {min_distance}"
                    )
            except Exception as layer_error:
                logger.error(f"Error detecting features: {layer_error}", exc_info=True)
            
            logger.info(f"Features found at click point: {features_at_point}")
            
            if features_at_point:
                if e.modifiers() & Qt.ControlModifier:
                    # Ctrl+Click: toggle selection
                    current_selected = list(self.layer.selectedFeatureIds())
                    if features_at_point[0] in current_selected:
                        current_selected.remove(features_at_point[0])
                        logger.info(f"Removed from selection: {features_at_point[0]}")
                    else:
                        current_selected.append(features_at_point[0])
                        logger.info(f"Added to selection: {features_at_point[0]}")
                    self.layer.selectByIds(current_selected)
                else:
                    # Normal click: select only this feature
                    self.layer.selectByIds(features_at_point)
                    logger.info(f"Selected feature(s): {features_at_point}")
            else:
                # No feature at click point, clear selection
                self.layer.selectByIds([])
                logger.info("No feature at click point, cleared selection")
        
        except Exception as e:
            logger.error(f"Error in canvas press event: {e}", exc_info=True)
    
    def activate(self):
        """Activate the selection tool."""
        super().activate()
        self.is_active = True
        self.canvas.setCursor(Qt.CrossCursor)
        self.selectionModeChanged.emit(True)
        logger.info("Footprint selection tool activated")
    
    def deactivate(self):
        """Deactivate the selection tool."""
        super().deactivate()
        self.is_active = False
        self.selectionModeChanged.emit(False)
        logger.info("Footprint selection tool deactivated")
