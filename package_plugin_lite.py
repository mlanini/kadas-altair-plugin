#!/usr/bin/env python3
"""
KADAS Altair Plugin Packager (Lightweight)
Creates a minimal plugin ZIP package without bundled dependencies.
Use this for environments that already have dependencies installed.

Usage:
    python package_plugin_lite.py

Output:
    kadas_altair_plugin.zip - Lightweight package (plugin code only)
"""

import os
import sys
import zipfile
from pathlib import Path
from datetime import datetime

# Configuration
PLUGIN_NAME = "kadas_altair_plugin"
OUTPUT_ZIP = "kadas_altair_plugin.zip"

# Files/folders to exclude
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".gitignore",
    ".vscode",
    "*.backup",
    ".pytest_cache",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "lib",  # Exclude bundled dependencies
]


def print_header(text):
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_step(step, text):
    """Print step information."""
    print(f"\n[{step}] {text}")


def print_success(text):
    """Print success message."""
    print(f"✅ {text}")


def print_error(text):
    """Print error message."""
    print(f"❌ ERROR: {text}")


def print_info(text):
    """Print info message."""
    print(f"ℹ️  {text}")


def should_exclude(path, base_path):
    """Check if path should be excluded."""
    rel_path = os.path.relpath(path, base_path)
    
    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*."):
            # Extension pattern
            if path.endswith(pattern[1:]):
                return True
        else:
            # Directory/file name pattern
            if pattern in rel_path.split(os.sep):
                return True
    
    return False


def check_requirements():
    """Check if plugin directory exists."""
    print_step(1, "Checking requirements")
    
    if not os.path.isdir(PLUGIN_NAME):
        print_error(f"Plugin directory '{PLUGIN_NAME}' not found!")
        return False
    print_success(f"Found plugin directory: {PLUGIN_NAME}")
    
    metadata_path = os.path.join(PLUGIN_NAME, "metadata.txt")
    if not os.path.isfile(metadata_path):
        print_error(f"metadata.txt not found in {PLUGIN_NAME}")
        return False
    print_success("Found metadata.txt")
    
    # Read version
    version = None
    with open(metadata_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('version='):
                version = line.split('=')[1].strip()
                break
    
    if version:
        print_info(f"Plugin version: {version}")
    
    return True


def create_zip_package():
    """Create ZIP package."""
    print_step(2, "Creating ZIP package")
    
    # Remove old ZIP if exists
    if os.path.isfile(OUTPUT_ZIP):
        os.remove(OUTPUT_ZIP)
        print_info(f"Removed old {OUTPUT_ZIP}")
    
    # Create ZIP
    file_count = 0
    skipped_count = 0
    
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PLUGIN_NAME):
            # Filter directories
            dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), PLUGIN_NAME)]
            
            for file_name in files:
                file_path = os.path.join(root, file_name)
                
                if should_exclude(file_path, PLUGIN_NAME):
                    skipped_count += 1
                    continue
                
                arcname = os.path.relpath(file_path, ".")
                zipf.write(file_path, arcname)
                file_count += 1
    
    print_success(f"Added {file_count} files to ZIP")
    if skipped_count > 0:
        print_info(f"Skipped {skipped_count} excluded files")
    
    # Get ZIP info
    zip_size = os.path.getsize(OUTPUT_ZIP)
    size_mb = zip_size / (1024 * 1024)
    
    print_success(f"Created {OUTPUT_ZIP}")
    print_info(f"Package size: {size_mb:.2f} MB ({zip_size:,} bytes)")
    
    return True


def print_package_info():
    """Print package information."""
    print_header("Package Information")
    
    zip_path = Path(OUTPUT_ZIP)
    
    print(f"\n📦 Package: {zip_path.name}")
    print(f"📊 Size: {zip_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"📅 Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📍 Location: {zip_path.absolute()}")
    
    print("\n📋 Package Contents:")
    
    with zipfile.ZipFile(OUTPUT_ZIP, 'r') as zipf:
        file_list = zipf.namelist()
        
        # Count by type
        py_files = [f for f in file_list if f.endswith('.py')]
        ui_files = [f for f in file_list if f.endswith('.ui')]
        icon_files = [f for f in file_list if f.endswith(('.png', '.svg', '.ico'))]
        md_files = [f for f in file_list if f.endswith('.md')]
        
        print(f"   • Python files: {len(py_files)}")
        print(f"   • UI files: {len(ui_files)}")
        print(f"   • Icon files: {len(icon_files)}")
        print(f"   • Documentation: {len(md_files)}")
        print(f"   • Total files: {len(file_list)}")
    
    print("\n⚠️  Note: This is a lightweight package")
    print("   Dependencies must be installed separately:")
    print("   • pystac-client>=0.7.0")
    print("   • beautifulsoup4>=4.9.0")
    
    print("\n📚 Installation:")
    print("   1. Install dependencies (if not already available):")
    print("      pip install pystac-client beautifulsoup4")
    print("   2. Open QGIS/KADAS")
    print("   3. Plugins → Manage and Install Plugins")
    print("   4. Install from ZIP")
    print(f"   5. Select {OUTPUT_ZIP}")
    print("   6. Activate plugin")
    
    print("\n✅ Lightweight package ready!")
    print("\n💡 For a complete package with bundled dependencies,")
    print("   use: python package_plugin_full.py")


def main():
    """Main packaging process."""
    print_header("KADAS Altair Plugin Packager (Lightweight)")
    print("Building lightweight package (dependencies not included)...")
    
    try:
        # Check requirements
        if not check_requirements():
            return 1
        
        # Create ZIP
        if not create_zip_package():
            return 1
        
        # Print info
        print_package_info()
        
        return 0
        
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
