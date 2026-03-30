"""
Altair Tasking Order Dock Widget

Generic tasking/order form for optical and SAR satellite acquisitions.
This panel does not submit orders to providers directly; it prepares a
structured email draft to the configured recipient.
"""

from urllib.parse import quote

from qgis.PyQt.QtCore import QDate, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)
try:
    from qgis.gui import QgsExtentWidget
except ImportError:
    QgsExtentWidget = None

from ..logger import get_logger

logger = get_logger('gui.tasking')


class TaskingDockWidget(QDockWidget):
    """Dock widget with a generic satellite tasking order form."""

    TARGET_EMAIL = 'mlanini@proton.me'

    PROVIDERS = [
        'Maxar',
        'Planet Labs',
        'Airbus',
        'ICEYE',
        'Capella Space',
        'European Space Imaging',
        'SkyWatch',
        'BlackSky',
        'HawkEye 360',
        'Spire',
        'UrtheCast / UrtheDaily',
        'Other (specify in notes)',
    ]

    def __init__(self, iface, parent=None):
        super().__init__('Tasking Order', parent)
        logger.info('Initializing Tasking Order dock widget')

        self.iface = iface
        self.setObjectName('AltairTaskingDock')
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        self._setup_ui()

    # Shared label color used by the subtitle and all form labels/group titles
    _LABEL_COLOR = '#b0b0b0'

    def _setup_ui(self):
        widget = QWidget()
        self.setWidget(widget)

        # Apply light text tone to all labels and group-box titles uniformly,
        # matching the subtitle style.
        widget.setStyleSheet(
            f"QLabel {{ color: {self._LABEL_COLOR}; }}"
            f"QGroupBox {{ color: {self._LABEL_COLOR}; font-weight: bold; }}"
        )

        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        header = QLabel('TEST Satellite Tasking Request')
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet('color: #ffffff;')
        layout.addWidget(header)

        subtitle = QLabel(
            'Compile a generic request for optical/SAR tasking and open it as '
            'an email draft. No direct provider API order is sent yet.'
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet('color: #b0b0b0; font-size: 10px;')
        layout.addWidget(subtitle)
        layout.addStretch(1)

        requester_group = QGroupBox('Requester')
        requester_form = QFormLayout(requester_group)

        self.requester_name = QLineEdit()
        self.requester_name.setPlaceholderText('Full name')
        requester_form.addRow('Name*:', self.requester_name)

        self.requester_email = QLineEdit()
        self.requester_email.setPlaceholderText('name@organization.tld')
        requester_form.addRow('Email*:', self.requester_email)

        self.requester_org = QLineEdit()
        self.requester_org.setPlaceholderText('Organization / Team')
        requester_form.addRow('Organization:', self.requester_org)

        layout.addWidget(requester_group)
        layout.addStretch(1)

        mission_group = QGroupBox('Mission & Provider')
        mission_form = QFormLayout(mission_group)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem('Any suitable provider')
        self.provider_combo.addItems(self.PROVIDERS)
        mission_form.addRow('Preferred Provider:', self.provider_combo)

        self.service_type_combo = QComboBox()
        self.service_type_combo.addItems(['Tasking'])
        self.service_type_combo.setEnabled(False)  # Only mode available
        # mission_form.addRow('Service Type:', self.service_type_combo)

        self.sensor_type_combo = QComboBox()
        self.sensor_type_combo.addItems(['Optical', 'SAR', 'Optical + SAR'])
        self.sensor_type_combo.currentTextChanged.connect(self._on_sensor_type_changed)
        mission_form.addRow('Sensor Type*:', self.sensor_type_combo)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(['5-Low', '4-Normal', '3-High', '2-Urgent', '1-CRITICAL'])
        self.priority_combo.setCurrentText('4-Normal')
        mission_form.addRow('Priority:', self.priority_combo)

        self.delivery_date = QDateEdit()
        self.delivery_date.setCalendarPopup(True)
        self.delivery_date.setDate(QDate.currentDate().addDays(7))
        mission_form.addRow('Desired Delivery Date:', self.delivery_date)

        layout.addWidget(mission_group)
        layout.addStretch(1)

        aoi_group = QGroupBox('Area Of Interest (AOI)')
        aoi_form = QFormLayout(aoi_group)

        self.aoi_name = QLineEdit()
        self.aoi_name.setPlaceholderText('AOI name / operation name')
        aoi_form.addRow('AOI Name:', self.aoi_name)

        self.extent_widget = None
        if QgsExtentWidget and self.iface:
            self.extent_widget = QgsExtentWidget(parent=aoi_group)
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())
            canvas = self.iface.mapCanvas()
            canvas_extent = canvas.extent()
            canvas_crs = canvas.mapSettings().destinationCrs()
            self.extent_widget.setCurrentExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOriginalExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOutputCrs(canvas_crs)
            aoi_form.addRow('AOI Extent:', self.extent_widget)
        else:
            fallback = QLabel('QgsExtentWidget not available in this environment.')
            fallback.setWordWrap(True)
            aoi_form.addRow('AOI Extent:', fallback)

        self.aoi_wkt = QTextEdit()
        self.aoi_wkt.setMaximumHeight(70)
        self.aoi_wkt.setPlaceholderText('Optional AOI polygon in WKT format')
        # aoi_form.addRow('AOI WKT (optional):', self.aoi_wkt)

        layout.addWidget(aoi_group)
        layout.addStretch(1)

        acquisition_group = QGroupBox('Acquisition Requirements')
        acquisition_form = QFormLayout(acquisition_group)

        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate())
        acquisition_form.addRow('Window Start*:', self.start_date)

        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate().addDays(14))
        acquisition_form.addRow('Window End*:', self.end_date)

        self.resolution_m = QDoubleSpinBox()
        self.resolution_m.setRange(0.1, 1000.0)
        self.resolution_m.setDecimals(1)
        self.resolution_m.setValue(1.0)
        self.resolution_m.setSuffix(' m')
        acquisition_form.addRow('Max GSD / Resolution:', self.resolution_m)

        self.revisit_hours = QDoubleSpinBox()
        self.revisit_hours.setRange(1.0, 720.0)
        self.revisit_hours.setDecimals(1)
        self.revisit_hours.setValue(24.0)
        self.revisit_hours.setSuffix(' h')
        acquisition_form.addRow('Desired Revisit:', self.revisit_hours)

        self.max_cloud_cover = QDoubleSpinBox()
        self.max_cloud_cover.setRange(0.0, 100.0)
        self.max_cloud_cover.setDecimals(1)
        self.max_cloud_cover.setValue(20.0)
        self.max_cloud_cover.setSuffix(' %')
        acquisition_form.addRow('Max Cloud Cover (Optical):', self.max_cloud_cover)

        self.optical_bands = QLineEdit()
        self.optical_bands.setPlaceholderText('e.g. RGB, NIR, SWIR')
        acquisition_form.addRow('Optical Bands:', self.optical_bands)

        self.sar_mode = QComboBox()
        self.sar_mode.addItems(['Any', 'Stripmap', 'Spotlight', 'ScanSAR'])
        acquisition_form.addRow('SAR Mode:', self.sar_mode)

        self.sar_polarization = QComboBox()
        self.sar_polarization.addItems(['Any', 'VV', 'VH', 'HH', 'HV', 'Dual-pol', 'Quad-pol'])
        acquisition_form.addRow('SAR Polarization:', self.sar_polarization)

        self.day_night_combo = QComboBox()
        self.day_night_combo.addItems(['Any', 'Day only', 'Night only'])
        acquisition_form.addRow('Day/Night:', self.day_night_combo)

        layout.addWidget(acquisition_group)
        layout.addStretch(1)

        product_group = QGroupBox('Delivery & Product')
        product_form = QFormLayout(product_group)

        self.product_level = QComboBox()
        self.product_level.addItems(['Any', 'Level-1', 'Level-2', 'Ortho-ready', 'Analysis-ready'])
        product_form.addRow('Product Level:', self.product_level)

        self.format_combo = QComboBox()
        self.format_combo.addItems(['GeoTIFF/COG', 'NITF', 'JPEG2000', 'NetCDF', 'Other'])
        product_form.addRow('Preferred Format:', self.format_combo)

        self.delivery_method = QComboBox()
        self.delivery_method.addItems(['Download link', 'STAC API endpoint', 'S3 bucket', 'Secure FTP'])
        product_form.addRow('Delivery Method:', self.delivery_method)

        self.notes = QTextEdit()
        self.notes.setMaximumHeight(90)
        self.notes.setPlaceholderText('Additional constraints, incidence angle, licensing, budget, legal notes...')
        product_form.addRow('Notes:', self.notes)

        layout.addWidget(product_group)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        self.send_btn = QPushButton('Compose Email Order (DEMO ONLY)')
        self.send_btn.clicked.connect(self._compose_email_order)
        buttons.addWidget(self.send_btn)

        self.clear_btn = QPushButton('Clear Form')
        self.clear_btn.clicked.connect(self._clear_form)
        buttons.addWidget(self.clear_btn)
        layout.addLayout(buttons)

        self.status_label = QLabel('Ready - Fill the form and click "Compose Email Order (DEMO ONLY)"')
        self.status_label.setStyleSheet('color: #f0f0f0; font-size: 10px;')
        layout.addWidget(self.status_label)

        self._on_sensor_type_changed(self.sensor_type_combo.currentText())

    # ------------------------------------------------------------------
    # AOI helpers
    # ------------------------------------------------------------------

    def _get_aoi_bbox_wgs84(self):
        if not self.extent_widget:
            return None
        try:
            extent = self.extent_widget.outputExtent()
            crs = self.extent_widget.outputCrs()
            if not extent or extent.isEmpty() or not crs or not crs.isValid():
                return None

            if crs.authid() != 'EPSG:4326':
                transform = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance())
                extent = transform.transformBoundingBox(extent)

            return (
                extent.xMinimum(),
                extent.yMinimum(),
                extent.xMaximum(),
                extent.yMaximum(),
            )
        except Exception as e:
            logger.warning(f'Failed to read AOI extent: {e}')
            return None

    def _on_sensor_type_changed(self, sensor_type: str):
        sensor = sensor_type.lower()
        optical_enabled = 'optical' in sensor
        sar_enabled = 'sar' in sensor

        self.max_cloud_cover.setEnabled(optical_enabled)
        self.optical_bands.setEnabled(optical_enabled)
        self.sar_mode.setEnabled(sar_enabled)
        self.sar_polarization.setEnabled(sar_enabled)

    def _validate_form(self) -> bool:
        if not self.requester_name.text().strip():
            QMessageBox.warning(self, 'Missing Field', 'Requester name is required.')
            return False
        if not self.requester_email.text().strip():
            QMessageBox.warning(self, 'Missing Field', 'Requester email is required.')
            return False
        if self.start_date.date() > self.end_date.date():
            QMessageBox.warning(self, 'Invalid Date Range', 'Window Start must be before Window End.')
            return False

        bbox = self._get_aoi_bbox_wgs84()
        if bbox is None:
            QMessageBox.warning(self, 'Missing AOI', 'Please define a valid AOI extent.')
            return False
        min_lon, min_lat, max_lon, max_lat = bbox
        if min_lon >= max_lon or min_lat >= max_lat:
            QMessageBox.warning(self, 'Invalid BBox', 'BBox must satisfy minLon < maxLon and minLat < maxLat.')
            return False

        return True

    def _build_email_subject_body(self):
        sensor_type = self.sensor_type_combo.currentText()
        requester = self.requester_name.text().strip()
        provider = self.provider_combo.currentText()

        subject = f"[Altair Tasking Request] {sensor_type} | {provider} | {requester}"

        bbox = self._get_aoi_bbox_wgs84()
        if bbox:
            bbox_text = f"[{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}]"
        else:
            bbox_text = 'N/A'

        body_lines = [
            'Satellite Tasking Request (Generic Form)',
            '',
            'REQUESTER',
            f"- Name: {requester}",
            f"- Email: {self.requester_email.text().strip()}",
            f"- Organization: {self.requester_org.text().strip() or 'N/A'}",
            '',
            'MISSION',
            f"- Preferred Provider: {provider}",
            f"- Service Type: {self.service_type_combo.currentText()}",
            f"- Sensor Type: {sensor_type}",
            f"- Priority: {self.priority_combo.currentText()}",
            f"- Desired Delivery Date: {self.delivery_date.date().toString('yyyy-MM-dd')}",
            '',
            'AOI',
            f"- AOI Name: {self.aoi_name.text().strip() or 'N/A'}",
            f"- BBox WGS84: {bbox_text}",
            f"- AOI WKT: {self.aoi_wkt.toPlainText().strip() or 'N/A'}",
            '',
            'ACQUISITION REQUIREMENTS',
            f"- Window Start: {self.start_date.date().toString('yyyy-MM-dd')}",
            f"- Window End: {self.end_date.date().toString('yyyy-MM-dd')}",
            f"- Max Resolution (GSD): {self.resolution_m.value():.1f} m",
            f"- Desired Revisit: {self.revisit_hours.value():.1f} h",
            f"- Max Cloud Cover (Optical): {self.max_cloud_cover.value():.1f}%",
            f"- Optical Bands: {self.optical_bands.text().strip() or 'N/A'}",
            f"- SAR Mode: {self.sar_mode.currentText()}",
            f"- SAR Polarization: {self.sar_polarization.currentText()}",
            f"- Day/Night: {self.day_night_combo.currentText()}",
            '',
            'DELIVERY',
            f"- Product Level: {self.product_level.currentText()}",
            f"- Preferred Format: {self.format_combo.currentText()}",
            f"- Delivery Method: {self.delivery_method.currentText()}",
            '',
            'NOTES',
            self.notes.toPlainText().strip() or 'N/A',
            '',
            '---',
            'Generated by KADAS Altair Tasking Dock',
        ]

        return subject, '\n'.join(body_lines)

    def _compose_email_order(self):
        if not self._validate_form():
            return

        try:
            subject, body = self._build_email_subject_body()
            mailto_url = (
                f"mailto:{self.TARGET_EMAIL}"
                f"?subject={quote(subject)}"
                f"&body={quote(body)}"
            )

            opened = QDesktopServices.openUrl(QUrl(mailto_url))
            if not opened:
                raise RuntimeError('Unable to open default email client with mailto URL')

            self.status_label.setText(f'Email draft opened for {self.TARGET_EMAIL}')
            self.status_label.setStyleSheet('color: #00ffbf; font-size: 10px;')
            logger.info('Tasking order email draft opened successfully')

        except Exception as e:
            logger.error(f'Failed to compose/send tasking email: {e}', exc_info=True)
            self.status_label.setText(f'Failed to open email client: {e}')
            self.status_label.setStyleSheet('color: #ff6b6b; font-size: 10px;')
            QMessageBox.critical(
                self,
                'Email Error',
                'Could not open your default email client.\n\n'
                f'Error: {str(e)}\n\n'
                f'Please send manually to: {self.TARGET_EMAIL}'
            )

    def _clear_form(self):
        self.requester_name.clear()
        self.requester_email.clear()
        self.requester_org.clear()

        self.provider_combo.setCurrentIndex(0)
        self.service_type_combo.setCurrentIndex(0)
        self.sensor_type_combo.setCurrentText('Optical')
        self.priority_combo.setCurrentText('Normal')
        self.delivery_date.setDate(QDate.currentDate().addDays(7))

        self.aoi_name.clear()
        self.aoi_wkt.clear()
        if self.extent_widget and self.iface:
            canvas = self.iface.mapCanvas()
            canvas_extent = canvas.extent()
            canvas_crs = canvas.mapSettings().destinationCrs()
            self.extent_widget.setCurrentExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOriginalExtent(canvas_extent, canvas_crs)
            self.extent_widget.setOutputCrs(canvas_crs)

        self.start_date.setDate(QDate.currentDate())
        self.end_date.setDate(QDate.currentDate().addDays(14))
        self.resolution_m.setValue(1.0)
        self.revisit_hours.setValue(24.0)
        self.max_cloud_cover.setValue(20.0)
        self.optical_bands.clear()
        self.sar_mode.setCurrentIndex(0)
        self.sar_polarization.setCurrentIndex(0)
        self.day_night_combo.setCurrentIndex(0)

        self.product_level.setCurrentIndex(0)
        self.format_combo.setCurrentIndex(0)
        self.delivery_method.setCurrentIndex(0)
        self.notes.clear()

        self.status_label.setText('Form cleared')
        self.status_label.setStyleSheet('color: #b0b0b0; font-size: 10px;')
