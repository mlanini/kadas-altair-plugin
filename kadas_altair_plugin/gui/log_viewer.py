"""
Log Viewer Dialog for KADAS Altair Plugin

Allows users to view, filter, and export plugin logs.
"""

import os
import subprocess
import platform
from pathlib import Path
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTextEdit, QComboBox, QLabel, QFileDialog, QMessageBox,
    QCheckBox, QLineEdit
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont, QTextCursor


class LogViewerDialog(QDialog):
    """Dialog to view and manage plugin logs"""
    
    def __init__(self, log_file_path: Path, parent=None):
        super().__init__(parent)
        self.log_file_path = log_file_path
        self.auto_refresh = False
        self.refresh_timer = None
        self.max_file_size_mb = 10  # Limite di 10 MB per evitare crash
        self.max_lines = 10000  # Massimo 10000 righe visualizzate
        
        self.setWindowTitle("KADAS Altair - Log Viewer")
        self.setMinimumSize(900, 600)
        
        self._setup_ui()
        self._load_logs()
    
    def _setup_ui(self):
        """Setup user interface"""
        layout = QVBoxLayout(self)
        
        # Header with log file path
        header_layout = QHBoxLayout()
        header_label = QLabel(f"📄 File di log: {self.log_file_path}")
        header_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        
        # Log level filter
        filter_layout.addWidget(QLabel("Livello:"))
        self.level_filter = QComboBox()
        self.level_filter.addItems(["TUTTI", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.level_filter.setCurrentText("TUTTI")
        self.level_filter.currentTextChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.level_filter)
        
        # Text search
        filter_layout.addWidget(QLabel("Cerca:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filtra per testo...")
        self.search_input.textChanged.connect(self._apply_filter)
        self.search_input.setMinimumWidth(200)
        filter_layout.addWidget(self.search_input)
        
        # Auto-refresh checkbox
        self.auto_refresh_checkbox = QCheckBox("Auto-aggiorna (5s)")
        self.auto_refresh_checkbox.stateChanged.connect(self._toggle_auto_refresh)
        filter_layout.addWidget(self.auto_refresh_checkbox)
        
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        
        # Monospace font for better readability
        font = QFont("Courier New", 9)
        self.log_text.setFont(font)
        
        layout.addWidget(self.log_text)
        
        # Status bar
        self.status_label = QLabel("Pronto")
        self.status_label.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 Aggiorna")
        self.refresh_btn.clicked.connect(self._load_logs)
        button_layout.addWidget(self.refresh_btn)
        
        self.clear_btn = QPushButton("🗑️ Cancella Log")
        self.clear_btn.clicked.connect(self._clear_logs)
        button_layout.addWidget(self.clear_btn)
        
        self.export_btn = QPushButton("💾 Esporta")
        self.export_btn.clicked.connect(self._export_logs)
        button_layout.addWidget(self.export_btn)
        
        self.open_folder_btn = QPushButton("📁 Apri Cartella")
        self.open_folder_btn.clicked.connect(self._open_log_folder)
        button_layout.addWidget(self.open_folder_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Chiudi")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def _load_logs(self):
        """Load logs from file with size protection to prevent crashes"""
        try:
            if not self.log_file_path.exists():
                self.log_text.setPlainText("File di log non trovato.")
                self.status_label.setText("⚠️ File di log non esistente")
                return
            
            # Check file size first to prevent crash
            file_size_bytes = self.log_file_path.stat().st_size
            file_size_mb = file_size_bytes / (1024 * 1024)
            
            if file_size_mb > self.max_file_size_mb:
                # File troppo grande - mostra solo le ultime righe
                self.log_text.setPlainText(
                    f"⚠️ FILE DI LOG TROPPO GRANDE ({file_size_mb:.1f} MB)\n\n"
                    f"Il file supera il limite di {self.max_file_size_mb} MB e potrebbe causare crash.\n"
                    f"Vengono mostrate solo le ultime {self.max_lines} righe.\n\n"
                    f"Per visualizzare tutto il file, aprilo con un editor di testo esterno.\n"
                    f"Usa il pulsante 'Apri Cartella' per accedere al file.\n\n"
                    f"{'=' * 80}\n\n"
                )
                
                # Leggi solo le ultime N righe
                self._load_tail_lines()
                return
            
            # File di dimensione accettabile - carica normalmente
            # Ma con timeout e protezione
            try:
                with open(self.log_file_path, 'r', encoding='utf-8', errors='replace') as f:
                    # Leggi il file
                    self.full_log_content = f.read()
                
                # Limita il numero di righe se necessario
                lines = self.full_log_content.split('\n')
                if len(lines) > self.max_lines:
                    # Prendi le ultime N righe
                    lines = lines[-self.max_lines:]
                    self.full_log_content = '\n'.join(lines)
                    truncated_msg = f"\n⚠️ Mostrate solo le ultime {self.max_lines} righe (file troppo lungo)\n\n"
                    self.full_log_content = truncated_msg + self.full_log_content
            
            except Exception as read_error:
                self.log_text.setPlainText(
                    f"❌ Errore nella lettura del file:\n{read_error}\n\n"
                    f"Il file potrebbe essere corrotto o troppo grande.\n"
                    f"Prova a cancellare il log o aprirlo con un editor esterno."
                )
                self.status_label.setText(f"❌ Errore di lettura: {str(read_error)[:50]}")
                return
            
            # Apply current filter
            self._apply_filter()
            
            # Update status
            file_size_kb = file_size_bytes / 1024
            line_count = len(self.full_log_content.split('\n'))
            self.status_label.setText(
                f"✅ Caricato: {line_count} righe, {file_size_kb:.1f} KB | "
                f"Ultima modifica: {self._get_file_mtime()}"
            )
            
            # Scroll to bottom
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_text.setTextCursor(cursor)
            
        except Exception as e:
            self.log_text.setPlainText(f"Errore nel caricamento del log: {e}")
            self.status_label.setText(f"❌ Errore: {str(e)[:50]}")
    
    def _load_tail_lines(self):
        """Load only the last N lines of a large file to prevent crash"""
        try:
            # Metodo efficiente per leggere le ultime righe di un file grande
            lines = []
            with open(self.log_file_path, 'rb') as f:
                # Vai alla fine del file
                f.seek(0, 2)
                file_size = f.tell()
                
                # Leggi a blocchi dal fondo
                block_size = 8192
                position = file_size
                
                while len(lines) < self.max_lines and position > 0:
                    # Calcola quanto leggere
                    read_size = min(block_size, position)
                    position -= read_size
                    
                    # Leggi il blocco
                    f.seek(position)
                    block = f.read(read_size)
                    
                    # Decodifica e aggiungi le righe
                    try:
                        text = block.decode('utf-8', errors='replace')
                        block_lines = text.split('\n')
                        lines = block_lines + lines
                    except:
                        # Errore di decodifica - salta questo blocco
                        continue
                
                # Prendi solo le ultime N righe
                lines = lines[-self.max_lines:]
                self.full_log_content = '\n'.join(lines)
                
                # Apply filter
                self._apply_filter()
                
                self.status_label.setText(
                    f"⚠️ File grande - mostrate ultime {len(lines)} righe | "
                    f"Dimensione totale: {file_size / (1024*1024):.1f} MB"
                )
                
        except Exception as e:
            self.log_text.setPlainText(
                f"❌ Impossibile leggere il file di log:\n{e}\n\n"
                f"Il file potrebbe essere bloccato o corrotto."
            )
            self.status_label.setText(f"❌ Errore: {str(e)[:50]}")
    
    def _apply_filter(self):
        """Apply level and text filters to log content with crash protection"""
        if not hasattr(self, 'full_log_content'):
            return
        
        try:
            filtered_lines = []
            level_filter = self.level_filter.currentText()
            search_text = self.search_input.text().lower()
            
            for line in self.full_log_content.split('\n'):
                # Level filter
                if level_filter != "TUTTI":
                    if f"| {level_filter} " not in line:
                        continue
                
                # Text search filter
                if search_text and search_text not in line.lower():
                    continue
                
                filtered_lines.append(line)
                
                # Protezione: limita righe filtrate per evitare crash
                if len(filtered_lines) > self.max_lines:
                    filtered_lines = filtered_lines[-self.max_lines:]
                    break
            
            # Update display - con protezione per testo molto lungo
            filtered_text = '\n'.join(filtered_lines)
            
            # Limita la lunghezza totale del testo (max ~5MB di testo)
            max_chars = 5 * 1024 * 1024
            if len(filtered_text) > max_chars:
                filtered_text = (
                    f"⚠️ RISULTATI TRONCATI (troppo testo)\n\n"
                    f"{filtered_text[-max_chars:]}"
                )
            
            self.log_text.setPlainText(filtered_text)
            
            # Update status with filter info
            if level_filter != "TUTTI" or search_text:
                self.status_label.setText(
                    f"🔍 Filtrato: {len(filtered_lines)} righe "
                    f"(Livello: {level_filter}, Cerca: '{search_text}')"
                )
        
        except Exception as e:
            self.log_text.setPlainText(
                f"❌ Errore durante il filtraggio:\n{e}\n\n"
                f"Il log potrebbe contenere dati corrotti."
            )
            self.status_label.setText(f"❌ Errore filtro: {str(e)[:50]}")
    
    def _get_file_mtime(self) -> str:
        """Get file modification time as string"""
        from datetime import datetime
        mtime = self.log_file_path.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
    
    def _toggle_auto_refresh(self, state):
        """Toggle auto-refresh timer"""
        self.auto_refresh = (state == Qt.Checked)
        
        if self.auto_refresh:
            # Create timer for 5-second refresh
            self.refresh_timer = QTimer(self)
            self.refresh_timer.timeout.connect(self._load_logs)
            self.refresh_timer.start(5000)  # 5 seconds
            self.status_label.setText("🔄 Auto-aggiornamento attivo (ogni 5s)")
        else:
            # Stop timer
            if self.refresh_timer:
                self.refresh_timer.stop()
                self.refresh_timer = None
            self.status_label.setText("Auto-aggiornamento disattivato")
    
    def _clear_logs(self):
        """Clear log file after confirmation"""
        reply = QMessageBox.question(
            self,
            "Conferma Cancellazione",
            "Sei sicuro di voler cancellare tutti i log?\n\n"
            "Questa operazione è irreversibile.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Clear file content
                with open(self.log_file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                
                # Reload display
                self._load_logs()
                
                QMessageBox.information(
                    self,
                    "Log Cancellati",
                    "File di log svuotato con successo."
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Errore",
                    f"Impossibile cancellare il log:\n{e}"
                )
    
    def _export_logs(self):
        """Export logs to a file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta Log",
            f"altair_plugin_log_{self._get_timestamp()}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                # Export current filtered view
                content = self.log_text.toPlainText()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                QMessageBox.information(
                    self,
                    "Esportazione Completata",
                    f"Log esportato in:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Errore",
                    f"Impossibile esportare il log:\n{e}"
                )
    
    def _get_timestamp(self) -> str:
        """Get current timestamp for filename"""
        from datetime import datetime
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def _open_log_folder(self):
        """Open log folder in file explorer"""
        log_dir = self.log_file_path.parent
        
        try:
            system = platform.system()
            
            if system == "Windows":
                os.startfile(log_dir)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(log_dir)])
            else:  # Linux
                subprocess.run(["xdg-open", str(log_dir)])
        
        except Exception as e:
            QMessageBox.warning(
                self,
                "Apertura Cartella",
                f"Impossibile aprire la cartella:\n{e}\n\n"
                f"Percorso: {log_dir}"
            )
    
    def closeEvent(self, event):
        """Handle dialog close"""
        # Stop auto-refresh timer if active
        if self.refresh_timer:
            self.refresh_timer.stop()
        event.accept()
