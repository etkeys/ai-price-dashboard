"""Tests for the ai-price-dashboard CLI entry point."""

import pytest

from app.cli import main


class TestCli:
    """CLI smoke tests."""

    def test_routes_command_lists_endpoints(self, capsys):
        exit_code = main(["routes"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "health" in captured.out

    def test_invalid_command_exits_with_error(self):
        with pytest.raises(SystemExit):
            main(["not-a-command"])
