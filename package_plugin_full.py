#!/usr/bin/env python3
"""
KADAS Altair Plugin Packager with Dependencies
Creates a complete plugin ZIP package including all external dependencies.

Usage:
    python package_plugin_full.py

Output:
    kadas_altair_plugin_full.zip - Complete package with bundled dependencies
"""

import os
import re
import sys
import zipfile
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from datetime import datetime

# Configuration
PLUGIN_NAME = "kadas_altair_plugin"
OUTPUT_ZIP = None  # Will be set after reading version from metadata.txt
REQUIREMENTS_FILE = "kadas_altair_plugin/requirements.txt"

# QGIS/KADAS built-in packages (don't bundle these)
QGIS_BUILTIN = {
    "pyqt5",
    "requests",
    "urllib3",
    "keyring",
    "cryptography",
}

# Files/folders to exclude from plugin
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
]

# Set KADAS_SKIP_PIP=1 to package without attempting pip installs
SKIP_DEP_INSTALL = os.environ.get("KADAS_SKIP_PIP", "0").strip().lower() in {
    "1", "true", "yes", "on"
}


def parse_requirement_name(requirement):
    """Extract normalized package name from a requirements entry."""
    cleaned = requirement.split(";", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", cleaned)
    if not match:
        return ""
    return match.group(1).strip().lower()


def requirement_to_import_root(requirement):
    """Convert a requirement specifier into its import root name."""
    package_name = parse_requirement_name(requirement)
    return package_name.replace("-", "_")


def load_external_dependencies(requirements_path):
    """Load non-QGIS runtime dependencies from requirements.txt."""
    deps = []

    with open(requirements_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue

            package_name = parse_requirement_name(line)
            if not package_name:
                continue
            if package_name in QGIS_BUILTIN:
                continue

            deps.append(line)

    return deps


# External dependencies to bundle (derived from runtime requirements)
EXTERNAL_DEPS = load_external_dependencies(REQUIREMENTS_FILE)

# Import roots that must be present in bundled lib for a valid FULL package.
REQUIRED_BUNDLED_MODULES = [
    requirement_to_import_root(dep) for dep in EXTERNAL_DEPS
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


def print_warning(text):
    """Print warning message."""
    print(f"⚠️  {text}")


def is_group_policy_block(error_text: str) -> bool:
    """Return True when pip execution appears blocked by corporate policy.

    Typical signatures include AppLocker / Group Policy / execution denied
    messages from managed Windows environments.
    """
    text = (error_text or "").lower()
    markers = [
        "group policy",
        "applocker",
        "execution is blocked",
        "has been blocked",
        "administrator has blocked",
        "not digitally signed",
    ]
    return any(marker in text for marker in markers)


def is_network_error(error_text: str) -> bool:
    """Return True when pip output indicates transient network/proxy issues."""
    text = (error_text or "").lower()
    markers = [
        "timed out",
        "timeout",
        "connection",
        "connection reset",
        "proxyerror",
        "newconnectionerror",
        "temporary failure in name resolution",
        "name or service not known",
        "getaddrinfo failed",
        "connection aborted",
        "read timed out",
        "max retries exceeded",
        "ssl: wrong version number",
        "certificate verify failed",
        "tlsv1",
    ]
    return any(marker in text for marker in markers)


def check_requirements():
    """Check if all requirements are met."""
    global OUTPUT_ZIP
    
    print_step(1, "Checking requirements")
    
    # Check if plugin directory exists
    if not os.path.isdir(PLUGIN_NAME):
        print_error(f"Plugin directory '{PLUGIN_NAME}' not found!")
        return False
    print_success(f"Found plugin directory: {PLUGIN_NAME}")
    
    # Check if metadata.txt exists
    metadata_path = os.path.join(PLUGIN_NAME, "metadata.txt")
    if not os.path.isfile(metadata_path):
        print_error(f"metadata.txt not found in {PLUGIN_NAME}")
        return False
    print_success("Found metadata.txt")

    if not os.path.isfile(REQUIREMENTS_FILE):
        print_error(f"Requirements file not found: {REQUIREMENTS_FILE}")
        return False
    print_success(f"Found requirements file: {REQUIREMENTS_FILE}")
    
    # Read version from metadata
    version = None
    with open(metadata_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('version='):
                version = line.split('=')[1].strip()
                break
    
    if version:
        print_info(f"Plugin version: {version}")
        # Set output ZIP filename with version
        OUTPUT_ZIP = f"kadas_altair_plugin_full_v{version}.zip"
        print_info(f"Output package: {OUTPUT_ZIP}")
    else:
        print_error("Could not read version from metadata.txt")
        return False
    
    return True


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


def get_pip_install_cmd(lib_dir, dep):
    """Build pip install command with proxy and network settings."""
    pip_retries = os.environ.get("KADAS_PIP_RETRIES", "4").strip()
    pip_timeout = os.environ.get("KADAS_PIP_TIMEOUT", "45").strip()

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        lib_dir,
        "--upgrade",
        "--disable-pip-version-check",
        "--retries",
        pip_retries,
        "--timeout",
        pip_timeout,
    ]
    
    # Add proxy if configured
    proxy = os.environ.get("PIP_PROXY") or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        cmd.extend(["--proxy", proxy])
        print_info(f"Using proxy: {proxy}")
    
    # Add trusted hosts if configured
    trusted_hosts = os.environ.get("PIP_TRUSTED_HOST")
    if trusted_hosts:
        for host in trusted_hosts.split():
            cmd.extend(["--trusted-host", host])
        print_info(f"Trusted hosts: {trusted_hosts}")
    
    # Add custom index URL if configured
    index_url = os.environ.get("PIP_INDEX_URL")
    if index_url:
        cmd.extend(["--index-url", index_url])
        print_info(f"Index URL: {index_url}")
    
    # Add the dependency
    cmd.append(dep)
    return cmd


def install_dependencies(temp_dir):
    """Install external dependencies to temporary directory."""
    print_step(2, "Installing external dependencies")

    if SKIP_DEP_INSTALL:
        print_warning("KADAS_SKIP_PIP=1 detected: skipping dependency installation")
        return True
    
    if not EXTERNAL_DEPS:
        print_info("No external dependencies to install")
        return True
    
    # Create lib directory in temp
    lib_dir = os.path.join(temp_dir, PLUGIN_NAME, "lib")
    os.makedirs(lib_dir, exist_ok=True)
    
    print_info(f"Installing to: {lib_dir}")
    
    for dep in EXTERNAL_DEPS:
        print(f"   • Installing {dep}...")

        max_attempts = max(1, int(os.environ.get("KADAS_DEP_INSTALL_ATTEMPTS", "3")))
        for attempt in range(1, max_attempts + 1):
            try:
                # Build and execute pip install command
                cmd = get_pip_install_cmd(lib_dir, dep)
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=os.environ.copy()
                )

                print_success(f"Installed {dep}")
                break

            except subprocess.CalledProcessError as e:
                stderr = e.stderr or ""
                stdout = e.stdout or ""
                combined = f"{stderr}\n{stdout}".strip()

                if is_group_policy_block(combined):
                    print_error(
                        "pip blocked by Group Policy/AppLocker. "
                        "Cannot build FULL package without bundled dependencies."
                    )
                    print_info(
                        "Run packaging in an environment where pip install is allowed, "
                        "or use package_plugin_lite.py if dependencies are managed externally."
                    )
                    return False

                if is_network_error(combined):
                    if attempt < max_attempts:
                        backoff_seconds = min(20, 2 ** (attempt - 1))
                        print_warning(
                            f"Network error while installing {dep} (attempt {attempt}/{max_attempts}). "
                            f"Retrying in {backoff_seconds}s..."
                        )
                        time.sleep(backoff_seconds)
                        continue

                    print_error(f"Failed to install {dep}: Network/Connection error")
                    print_info(
                        "If behind a corporate proxy, set environment variables:"
                    )
                    print_info(
                        '  PowerShell: $env:PIP_PROXY=\'http://proxy:8080\'; '
                        '$env:PIP_TRUSTED_HOST=\'pypi.org files.pythonhosted.org\''
                    )
                    print_info(
                        "  Bash: export PIP_PROXY=http://proxy:8080 "
                        "PIP_TRUSTED_HOST='pypi.org files.pythonhosted.org'"
                    )
                    print_info(
                        "Optional tuning: KADAS_DEP_INSTALL_ATTEMPTS=5, "
                        "KADAS_PIP_TIMEOUT=60, KADAS_PIP_RETRIES=6"
                    )
                    return False

                print_error(f"Failed to install {dep}")
                print(f"Error: {stderr}")
                return False
    
    # Clean up unnecessary files in lib
    cleanup_lib_directory(lib_dir)
    
    return True


def verify_bundled_dependencies(temp_dir):
    """Ensure required dependencies are actually present in plugin lib/."""
    print_step(2.5, "Verifying bundled dependencies")

    lib_dir = os.path.join(temp_dir, PLUGIN_NAME, "lib")
    if not os.path.isdir(lib_dir):
        print_error("Missing lib directory in FULL package staging area")
        return False

    missing = []
    for module_name in REQUIRED_BUNDLED_MODULES:
        pkg_dir = os.path.join(lib_dir, module_name)
        pkg_file = os.path.join(lib_dir, f"{module_name}.py")
        if not os.path.isdir(pkg_dir) and not os.path.isfile(pkg_file):
            missing.append(module_name)

    if missing:
        print_error(
            "Missing required bundled dependencies in lib/: "
            + ", ".join(missing)
        )
        print_info(
            "FULL package must include all non-QGIS runtime dependencies "
            "listed in requirements.txt."
        )
        return False

    print_success("Bundled dependencies verified")
    return True


def cleanup_lib_directory(lib_dir):
    """Remove unnecessary files from lib directory."""
    print_info("Cleaning up lib directory...")

    # Keep botocore/docs because earthaccess imports runtime helpers from there
    # (e.g. botocore.docs.docstring).
    protected_dirs = {
        os.path.join("botocore", "docs"),
    }
    
    cleanup_patterns = [
        "*.dist-info",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "tests",
        "test",
        "examples",
        "docs",
        "*.egg-info",
    ]
    
    removed_count = 0
    
    for root, dirs, files in os.walk(lib_dir, topdown=False):
        # Remove matching directories
        for dir_name in dirs[:]:
            for pattern in cleanup_patterns:
                if pattern.startswith("*."):
                    if dir_name.endswith(pattern[1:]):
                        dir_path = os.path.join(root, dir_name)
                        shutil.rmtree(dir_path, ignore_errors=True)
                        removed_count += 1
                        dirs.remove(dir_name)
                        break
                else:
                    if dir_name == pattern:
                        dir_path = os.path.join(root, dir_name)

                        rel_dir_path = os.path.relpath(dir_path, lib_dir)
                        rel_dir_norm = rel_dir_path.replace("/", os.sep).replace("\\", os.sep)
                        if any(
                            rel_dir_norm == protected
                            or rel_dir_norm.startswith(protected + os.sep)
                            for protected in protected_dirs
                        ):
                            continue

                        shutil.rmtree(dir_path, ignore_errors=True)
                        removed_count += 1
                        dirs.remove(dir_name)
                        break
        
        # Remove matching files
        for file_name in files:
            for pattern in cleanup_patterns:
                if pattern.startswith("*."):
                    if file_name.endswith(pattern[1:]):
                        file_path = os.path.join(root, file_name)
                        os.remove(file_path)
                        removed_count += 1
                        break
    
    if removed_count > 0:
        print_info(f"Removed {removed_count} unnecessary items")


def copy_plugin_files(temp_dir):
    """Copy plugin files to temporary directory."""
    print_step(3, "Copying plugin files")
    
    dest_dir = os.path.join(temp_dir, PLUGIN_NAME)
    os.makedirs(dest_dir, exist_ok=True)
    
    copied_count = 0
    skipped_count = 0
    
    for root, dirs, files in os.walk(PLUGIN_NAME):
        # Filter directories
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), PLUGIN_NAME)]
        
        # Create directory structure
        rel_root = os.path.relpath(root, PLUGIN_NAME)
        if rel_root != ".":
            dest_root = os.path.join(dest_dir, rel_root)
            os.makedirs(dest_root, exist_ok=True)
        else:
            dest_root = dest_dir
        
        # Copy files
        for file_name in files:
            src_path = os.path.join(root, file_name)
            
            if should_exclude(src_path, PLUGIN_NAME):
                skipped_count += 1
                continue
            
            dest_path = os.path.join(dest_root, file_name)
            shutil.copy2(src_path, dest_path)
            copied_count += 1
    
    print_success(f"Copied {copied_count} files")
    if skipped_count > 0:
        print_info(f"Skipped {skipped_count} excluded files")
    
    return True


def create_lib_init(temp_dir):
    """Create __init__.py in lib directory to make it a package."""
    print_step(4, "Configuring dependency loading")
    
    lib_dir = os.path.join(temp_dir, PLUGIN_NAME, "lib")
    
    if not os.path.isdir(lib_dir):
        print_info("No lib directory, skipping")
        return True
    
    # Create __init__.py in lib
    init_path = os.path.join(lib_dir, "__init__.py")
    
    init_content = '''"""
External dependencies for KADAS Altair plugin.
This directory contains bundled third-party packages.
"""

import sys
import os

# Add lib directory to Python path
lib_path = os.path.dirname(__file__)
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
'''
    
    with open(init_path, 'w', encoding='utf-8') as f:
        f.write(init_content)
    
    print_success("Created lib/__init__.py")
    
    # Update plugin __init__.py to load lib
    plugin_init = os.path.join(temp_dir, PLUGIN_NAME, "__init__.py")
    
    if os.path.isfile(plugin_init):
        with open(plugin_init, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if lib loading is already present
        if "sys.path.insert" not in content or "lib" not in content:
            # Add lib loading at the beginning
            lib_loader = '''# Load bundled dependencies
import sys
import os

# Add lib directory to path for bundled dependencies
lib_path = os.path.join(os.path.dirname(__file__), 'lib')
if os.path.isdir(lib_path) and lib_path not in sys.path:
    sys.path.insert(0, lib_path)

'''
            # Insert after first line (usually # -*- coding: utf-8 -*-)
            lines = content.split('\n')
            if lines[0].startswith('#'):
                lines.insert(1, lib_loader)
            else:
                lines.insert(0, lib_loader)
            
            content = '\n'.join(lines)
            
            with open(plugin_init, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print_success("Updated plugin __init__.py with lib loader")
    
    return True


def create_zip_package(temp_dir):
    """Create ZIP package from temporary directory."""
    print_step(5, "Creating ZIP package")
    
    # Remove old ZIP if exists
    if os.path.isfile(OUTPUT_ZIP):
        os.remove(OUTPUT_ZIP)
        print_info(f"Removed old {OUTPUT_ZIP}")
    
    # Create ZIP
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        plugin_dir = os.path.join(temp_dir, PLUGIN_NAME)
        
        file_count = 0
        for root, dirs, files in os.walk(plugin_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
                file_count += 1
        
        print_success(f"Added {file_count} files to ZIP")
    
    # Get ZIP info
    zip_size = os.path.getsize(OUTPUT_ZIP)
    size_mb = zip_size / (1024 * 1024)
    
    print_success(f"Created {OUTPUT_ZIP}")
    print_info(f"Package size: {size_mb:.2f} MB ({zip_size:,} bytes)")
    
    return True


def print_package_info():
    """Print information about the created package."""
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
        lib_files = [f for f in file_list if '/lib/' in f]
        
        print(f"   • Python files: {len(py_files)}")
        print(f"   • UI files: {len(ui_files)}")
        print(f"   • Icon files: {len(icon_files)}")
        print(f"   • Bundled libraries: {len(lib_files)} files")
        print(f"   • Total files: {len(file_list)}")
    
    print("\n🔌 Bundled Dependencies:")
    if lib_files:
        for dep in EXTERNAL_DEPS:
            print(f"   • {dep}")
    else:
        print("   • none (dependency install skipped or unavailable)")
    
    print("\n📚 Installation:")
    print("   1. Open QGIS/KADAS")
    print("   2. Plugins → Manage and Install Plugins")
    print("   3. Install from ZIP")
    print(f"   4. Select {OUTPUT_ZIP}")
    print("   5. Activate plugin")
    
    print("\n✅ Package ready for deployment!")


def main():
    """Main packaging process."""
    print_header("KADAS Altair Plugin Packager with Dependencies")
    print(f"Building complete package with bundled dependencies...")
    
    try:
        # Step 1: Check requirements
        if not check_requirements():
            return 1
        
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            print_info(f"Using temporary directory: {temp_dir}")
            
            # Step 2: Install dependencies
            if not install_dependencies(temp_dir):
                return 1

            # Step 2.5: Verify required bundled modules are present
            if not verify_bundled_dependencies(temp_dir):
                return 1
            
            # Step 3: Copy plugin files
            if not copy_plugin_files(temp_dir):
                return 1
            
            # Step 4: Configure lib loading
            if not create_lib_init(temp_dir):
                return 1
            
            # Step 5: Create ZIP
            if not create_zip_package(temp_dir):
                return 1
        
        # Print package info
        print_package_info()
        
        return 0
        
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
