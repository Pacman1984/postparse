"""
Unit tests for API module import-time side effects.

These tests ensure importing the FastAPI entry point does not write the
environment file path directly to stdout.
"""

import importlib
import sys
from types import ModuleType
from unittest.mock import patch

import pytest


class TestApiMainImportBehavior:
    """Tests for import-time logging behavior in the API entry module."""

    def test_import_does_not_print_env_path_to_stdout(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        Avoid direct stdout output when loading environment variables.

        Example:
            Importing ``backend.postparse.api.main`` should not emit the
            ``Loaded environment variables from ...`` message via ``print()``.
        """
        module_name = "backend.postparse.api.main"
        previous_module: ModuleType | None = sys.modules.get(module_name)

        try:
            sys.modules.pop(module_name, None)
            with patch("builtins.print") as mock_print:
                importlib.import_module(module_name)

            captured = capsys.readouterr()
            assert captured.out == ""
            mock_print.assert_not_called()
        finally:
            if previous_module is not None:
                sys.modules[module_name] = previous_module
            else:
                sys.modules.pop(module_name, None)
