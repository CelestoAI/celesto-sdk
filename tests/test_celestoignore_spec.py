"""Tests for .celestoignore gitignore spec compliance.

These tests verify that .celestoignore follows the gitignore specification:
1. Lines starting with # (after optional whitespace) are comments
2. A # elsewhere in the line is literal unless preceded by whitespace (inline comment)
3. Trailing spaces are ignored unless escaped
4. Patterns with # in the middle should match literally
"""

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


def test_hash_in_middle_of_pattern_is_literal(deployment, tmp_path: Path):
    """Test that # in the middle of a pattern is treated as literal character."""
    # Create test files
    (tmp_path / "file#with#hash.txt").write_text("content")
    (tmp_path / "normal.txt").write_text("content")

    # Create .celestoignore with pattern containing # in the middle
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("file#with#hash.txt\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Should match the file with # in name
    assert ignore_spec.match_file(
        "file#with#hash.txt"
    ), "Pattern with # should match literal filename with #"
    assert not ignore_spec.match_file(
        "normal.txt"
    ), "Pattern with # should not match unrelated file"


def test_hash_at_start_after_pattern_is_literal(deployment, tmp_path: Path):
    """Test that #foo (no space before #) in a pattern is treated literally."""
    # Create test files
    (tmp_path / "test#file.txt").write_text("content")
    (tmp_path / "testfile.txt").write_text("content")

    # Pattern without space before # should be literal
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("test#file.txt\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file("test#file.txt"), "Should match file with # in name"
    assert not ignore_spec.match_file(
        "testfile.txt"
    ), "Should not match file without #"


def test_inline_comment_with_space_before_hash(deployment, tmp_path: Path):
    """Test that # preceded by space starts an inline comment."""
    # Create test files
    (tmp_path / "test.pyc").write_text("compiled")
    (tmp_path / "test.py").write_text("source")

    # Pattern with space before # should treat # as comment start
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("*.pyc # This is an inline comment\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Should match .pyc files (comment is stripped)
    assert ignore_spec.match_file("test.pyc"), "Pattern should work with inline comment"
    assert not ignore_spec.match_file("test.py"), "Should not match .py files"


def test_multiple_inline_comments_on_different_lines(deployment, tmp_path: Path):
    """Test multiple patterns with inline comments."""
    # Create test files
    (tmp_path / "test.pyc").write_text("compiled")
    (tmp_path / ".env").write_text("secrets")
    (tmp_path / "test.py").write_text("source")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """*.pyc # Python compiled files
.env # Environment variables
*.log # Log files
"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file("test.pyc"), "Should match .pyc"
    assert ignore_spec.match_file(".env"), "Should match .env"
    assert not ignore_spec.match_file("test.py"), "Should not match .py"


def test_pattern_ending_with_hash_no_space(deployment, tmp_path: Path):
    """Test pattern ending with # (no space before it) is treated literally."""
    # Create test file with # at the end of name
    (tmp_path / "file#").write_text("content")
    (tmp_path / "file").write_text("content")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("file#\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file("file#"), "Should match file ending with #"
    assert not ignore_spec.match_file("file"), "Should not match file without #"


def test_full_line_comment_variations(deployment, tmp_path: Path):
    """Test that lines starting with # (after whitespace) are comments."""
    # Create test files
    (tmp_path / "keep.txt").write_text("content")
    (tmp_path / "#file.txt").write_text("content")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """# This is a comment
  # This is also a comment (leading spaces)
	# This is a comment with tab
*.log
"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Comments should not affect pattern matching
    assert not ignore_spec.match_file("keep.txt"), "Comments shouldn't exclude files"
    assert not ignore_spec.match_file(
        "#file.txt"
    ), "Comments shouldn't exclude files starting with #"
    assert ignore_spec.match_file("test.log"), "Actual patterns should work"


def test_wildcard_with_hash_in_pattern(deployment, tmp_path: Path):
    """Test wildcard patterns containing # character."""
    # Create test files
    (tmp_path / "test#1.txt").write_text("content")
    (tmp_path / "test#2.txt").write_text("content")
    (tmp_path / "test-1.txt").write_text("content")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("test#*.txt\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Should match files with # in the name matching the pattern
    assert ignore_spec.match_file("test#1.txt"), "Should match test#1.txt"
    assert ignore_spec.match_file("test#2.txt"), "Should match test#2.txt"
    assert not ignore_spec.match_file(
        "test-1.txt"
    ), "Should not match file without # in name"


def test_pattern_with_hash_and_inline_comment(deployment, tmp_path: Path):
    """Test pattern containing # that also has an inline comment."""
    # Create test file
    (tmp_path / "file#name.txt").write_text("content")
    (tmp_path / "filename.txt").write_text("content")

    # Pattern: file#name.txt # inline comment
    # The first # is part of pattern, second # (after space) starts comment
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("file#name.txt # This is an inline comment\n")

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file(
        "file#name.txt"
    ), "Should match file with # in name despite inline comment"
    assert not ignore_spec.match_file(
        "filename.txt"
    ), "Should not match file without #"


def test_trailing_spaces_are_ignored(deployment, tmp_path: Path):
    """Test that trailing spaces in patterns are ignored per gitignore spec."""
    # Create test files
    (tmp_path / "test.txt").write_text("content")
    (tmp_path / "test.txt ").write_text("content")  # filename with trailing space

    # Pattern with trailing spaces (should be stripped)
    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text("test.txt   \n")  # Multiple trailing spaces

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    # Should match the file without trailing spaces
    assert ignore_spec.match_file("test.txt"), "Should match file without trailing space"


def test_empty_and_whitespace_only_lines(deployment, tmp_path: Path):
    """Test that empty lines and whitespace-only lines are ignored."""
    # Create test files
    (tmp_path / "test.pyc").write_text("compiled")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """

*.pyc



"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file(
        "test.pyc"
    ), "Pattern should work despite empty lines"


def test_negation_pattern_with_inline_comment(deployment, tmp_path: Path):
    """Test negation patterns (!) with inline comments."""
    # Create test files
    (tmp_path / "test.log").write_text("log")
    (tmp_path / "important.log").write_text("important")

    celestoignore = tmp_path / ".celestoignore"
    celestoignore.write_text(
        """*.log # Ignore all logs
!important.log # But not this one
"""
    )

    ignore_spec = deployment._load_ignore_patterns(tmp_path)
    assert ignore_spec is not None

    assert ignore_spec.match_file("test.log"), "Should match .log files"
    assert not ignore_spec.match_file(
        "important.log"
    ), "Should not match negated pattern"
