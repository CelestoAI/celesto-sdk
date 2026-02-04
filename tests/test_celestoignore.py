"""Tests for .celestoignore file handling during deployment."""

import os
import tarfile
import tempfile
from pathlib import Path

import pytest

from celesto.sdk.client import Deployment, _BaseConnection


class MockConnection(_BaseConnection):
    """Mock connection for testing without requiring API key."""

    def __init__(self):
        super().__init__(api_key="test", base_url="http://test")
        self.session = None


@pytest.fixture
def deployment():
    """Create a Deployment instance for testing."""
    return Deployment(MockConnection())


def test_comment_lines_are_ignored_in_celestoignore(deployment, tmp_path: Path):
    """Test that lines starting with # in .celestoignore are treated as comments."""
    # Create test files including one that starts with #
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "#important.py").write_text("# This file starts with #")
    (tmp_path / "README.md").write_text("# Documentation")
    (tmp_path / "actual_ignore.pyc").write_text("compiled")

    # Create .celestoignore with comments and actual patterns
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """# This is a comment and should be ignored
# Another comment line
*.pyc

# Yet another comment
# Files starting with # should NOT be excluded by these comment lines
"""
    )

    # Load ignore patterns
    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None, "Should load ignore patterns"

    # Test that comment lines don't cause files to be ignored
    assert not ignore_spec.match_file("main.py"), "main.py should not be ignored"
    assert not ignore_spec.match_file(
        "#important.py"
    ), "Files starting with # should not be ignored by comment lines"
    assert not ignore_spec.match_file("README.md"), "README.md should not be ignored"

    # Test that actual patterns work
    assert ignore_spec.match_file(
        "actual_ignore.pyc"
    ), "*.pyc pattern should match .pyc files"


def test_empty_lines_are_ignored_in_celestoignore(deployment, tmp_path: Path):
    """Test that empty lines in .celestoignore are ignored."""
    # Create test files
    (tmp_path / "keep.py").write_text("code")
    (tmp_path / "ignore.log").write_text("logs")

    # Create .celestoignore with empty lines
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """
# Comment

*.log


# Another comment with blank lines above
"""
    )

    # Load ignore patterns
    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Test file matching
    assert not ignore_spec.match_file("keep.py"), "keep.py should not be ignored"
    assert ignore_spec.match_file("ignore.log"), "ignore.log should be ignored"


def test_files_starting_with_hash_are_included_in_deployment(
    deployment, tmp_path: Path
):
    """Test that files whose names start with # are included in deployment."""
    # Create files including ones starting with #
    (tmp_path / "normal.py").write_text("code")
    (tmp_path / "#config.yaml").write_text("config")
    (tmp_path / "#.hidden").write_text("hidden")

    # Create .celestoignore with only comments (no actual ignore patterns)
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """# This is just a comment
# Another comment
# No actual ignore patterns here
"""
    )

    # Create a tar archive using the same logic as deploy()
    ignore_spec = deployment._load_ignore_patterns(tmp_path)

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        with tarfile.open(temp_path, "w:gz") as tar:
            for root, dirs, files in os.walk(tmp_path):
                root_path = Path(root)
                rel_root = root_path.relative_to(tmp_path)

                for file in files:
                    file_path = root_path / file
                    rel_file = rel_root / file if rel_root != Path(".") else Path(file)

                    # Skip if file matches ignore patterns
                    if ignore_spec:
                        file_pattern = str(rel_file).replace("\\", "/")
                        if ignore_spec.match_file(file_pattern):
                            continue

                    # Add file to archive
                    arcname = str(rel_file).replace("\\", "/")
                    tar.add(file_path, arcname=arcname)

        # Verify the archive contents
        with tarfile.open(temp_path, "r:gz") as tar:
            members = tar.getnames()

            # All files should be present (including those starting with #)
            assert "normal.py" in members, "normal.py should be in archive"
            assert "#config.yaml" in members, "#config.yaml should be in archive"
            assert "#.hidden" in members, "#.hidden should be in archive"
            assert ".celestoignore" in members, ".celestoignore should be in archive"

    finally:
        temp_path.unlink()


def test_mixed_comments_and_patterns(deployment, tmp_path: Path):
    """Test .celestoignore with mixed comments and actual patterns."""
    # Create test files
    (tmp_path / "keep.py").write_text("code")
    (tmp_path / "test.pyc").write_text("compiled")
    (tmp_path / ".env").write_text("secrets")
    (tmp_path / "#note.txt").write_text("note")
    Path(tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cache.pyc").write_text("cache")

    # Create .celestoignore with mixed content
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """# Python compilation artifacts
*.pyc
__pycache__/

# Environment variables
.env

# This is a comment about files starting with #
# They should NOT be excluded by this comment
"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Files that should NOT be ignored
    assert not ignore_spec.match_file("keep.py"), "keep.py should not be ignored"
    assert not ignore_spec.match_file(
        "#note.txt"
    ), "#note.txt should not be ignored by comments"

    # Files that SHOULD be ignored
    assert ignore_spec.match_file("test.pyc"), "*.pyc should match .pyc files"
    assert ignore_spec.match_file(".env"), ".env should be ignored"
    assert ignore_spec.match_file(
        "__pycache__/cache.pyc"
    ), "Files in __pycache__/ should be ignored"


def test_celestoignore_does_not_ignore_itself(deployment, tmp_path: Path):
    """Test that .celestoignore file itself is not ignored."""
    # Create .celestoignore
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("*.pyc\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # .celestoignore should not be ignored
    assert not ignore_spec.match_file(
        ".celestoignore"
    ), ".celestoignore should not be ignored"


def test_inline_comments_are_supported(deployment, tmp_path: Path):
    """Test that inline comments (# after pattern) are properly stripped.

    Inline comments allow users to add explanatory text after patterns.
    Everything after # on a line is treated as a comment and ignored.
    """
    # Create test files
    (tmp_path / "test.pyc").write_text("compiled")
    (tmp_path / "keep.py").write_text("code")
    (tmp_path / ".env").write_text("secrets")

    # Create .celestoignore with inline comments
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """*.pyc  # Python compiled files
.env # Environment variables
# This is a full-line comment
*.log   # Log files (but no .log files exist)
"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Patterns with inline comments should work (comments are stripped)
    assert ignore_spec.match_file("test.pyc"), "*.pyc with inline comment should match"
    assert ignore_spec.match_file(".env"), ".env with inline comment should match"

    # Files not matching patterns should not be ignored
    assert not ignore_spec.match_file("keep.py"), "keep.py should not be ignored"


def test_all_files_ignored_creates_valid_archive(deployment, tmp_path: Path):
    """Test that ignoring all files creates a valid (but empty) tar archive.

    This verifies graceful handling when .celestoignore patterns match all
    files in the deployment folder, resulting in an empty archive.
    """
    # Create test files
    (tmp_path / "test.pyc").write_text("compiled")
    (tmp_path / "test.log").write_text("logs")
    (tmp_path / ".env").write_text("secrets")

    # Create .celestoignore that ignores everything
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """# Ignore all files
*
"""
    )

    # Load ignore patterns
    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Create tar archive (should be valid but contain no files except .celestoignore)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        with tarfile.open(temp_path, "w:gz") as tar:
            for root, dirs, files in os.walk(tmp_path):
                root_path = Path(root)
                rel_root = root_path.relative_to(tmp_path)

                for file in files:
                    file_path = root_path / file
                    rel_file = rel_root / file if rel_root != Path(".") else Path(file)

                    # Skip if file matches ignore patterns
                    if ignore_spec:
                        file_pattern = str(rel_file).replace("\\", "/")
                        if ignore_spec.match_file(file_pattern):
                            continue

                    # Add file to archive
                    arcname = str(rel_file).replace("\\", "/")
                    tar.add(file_path, arcname=arcname)

        # Verify the archive is valid and check contents
        with tarfile.open(temp_path, "r:gz") as tar:
            members = tar.getnames()

            # The archive should be valid (can be opened)
            # Note: .celestoignore itself won't be in archive because it's matched by *
            # In real deployment, this would result in empty or near-empty bundle
            assert isinstance(
                members, list
            ), "Archive should be valid with list of members"

            # Verify that the test files are NOT in the archive
            assert "test.pyc" not in members, "test.pyc should be ignored"
            assert "test.log" not in members, "test.log should be ignored"
            assert ".env" not in members, ".env should be ignored"

    finally:
        temp_path.unlink()
