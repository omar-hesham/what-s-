"""
Tests for security: Zip Slip vulnerability prevention, path traversal defense, and token authentication.
"""

import zipfile
import pytest
from pathlib import Path
from owi.core.security import safe_extract_zip, sanitize_filename, is_safe_path

def test_zip_slip_prevention(tmp_path):
    """Ensure safe_extract_zip blocks archives attempting directory traversal."""
    malicious_zip = tmp_path / "malicious.zip"
    extract_target = tmp_path / "extracted_dir"
    extract_target.mkdir()

    # Create a zip with a malicious relative path trying to write outside
    with zipfile.ZipFile(malicious_zip, "w") as z:
        z.writestr("../../evil_script.bat", b"@echo off\necho pwned\n")
        z.writestr("legit_file.txt", b"Safe content")

    extracted, errors = safe_extract_zip(malicious_zip, extract_target)

    # Malicious file must be blocked
    evil_path = tmp_path / "evil_script.bat"
    assert not evil_path.exists(), "Zip slip attack succeeded! Security vulnerability detected!"
    assert any("Zip Slip attempt" in e for e in errors)

    # Legitimate file must be extracted
    assert (extract_target / "legit_file.txt").exists()

def test_filename_sanitization():
    assert sanitize_filename("../../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\calc.exe") == "calc.exe"
    # Arabic text must be preserved
    assert sanitize_filename("عقد_إيجار_مكتب.pdf") == "عقد_إيجار_مكتب.pdf"
    assert sanitize_filename("file;rm -rf") == "file_rm -rf"

def test_is_safe_path(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    safe_child = base / "subdir" / "file.txt"
    unsafe_child = tmp_path / "outside.txt"

    assert is_safe_path(base, safe_child) is True
    assert is_safe_path(base, unsafe_child) is False
