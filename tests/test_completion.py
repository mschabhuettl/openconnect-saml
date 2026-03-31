"""Tests for shell completion generation."""

from unittest.mock import MagicMock, patch

from openconnect_saml.completion import (
    _bash_completion,
    _fish_completion,
    _get_profile_names,
    _zsh_completion,
    handle_completion_command,
)


class TestBashCompletion:
    def test_generates_script(self):
        script = _bash_completion()
        assert "complete -F _openconnect_saml openconnect-saml" in script
        assert "connect" in script
        assert "profiles" in script
        assert "status" in script
        assert "completion" in script
        assert "service" in script

    def test_includes_flags(self):
        script = _bash_completion()
        assert "--server" in script
        assert "--headless" in script
        assert "--reconnect" in script

    def test_profile_completion(self):
        script = _bash_completion()
        assert "_profiles" in script


class TestZshCompletion:
    def test_generates_script(self):
        script = _zsh_completion()
        assert "#compdef openconnect-saml" in script
        assert "_openconnect_saml" in script
        assert "connect" in script
        assert "profiles" in script

    def test_includes_actions(self):
        script = _zsh_completion()
        assert "list" in script
        assert "add" in script
        assert "remove" in script


class TestFishCompletion:
    def test_generates_script(self):
        script = _fish_completion()
        assert "complete -c openconnect-saml" in script
        assert "connect" in script
        assert "profiles" in script

    def test_includes_subcommands(self):
        script = _fish_completion()
        assert "status" in script
        assert "completion" in script
        assert "service" in script


class TestGetProfileNames:
    @patch("openconnect_saml.completion.config")
    def test_with_profiles(self, mock_config):
        from openconnect_saml.config import Config

        cfg = Config()
        cfg.add_profile("work", {"server": "vpn.com"})
        cfg.add_profile("lab", {"server": "lab.com"})
        mock_config.load.return_value = cfg
        names = _get_profile_names()
        assert "work" in names
        assert "lab" in names

    @patch("openconnect_saml.completion.config")
    def test_empty_profiles(self, mock_config):
        from openconnect_saml.config import Config

        mock_config.load.return_value = Config()
        names = _get_profile_names()
        assert names == []

    @patch("openconnect_saml.completion.config")
    def test_config_error(self, mock_config):
        mock_config.load.side_effect = Exception("broken")
        names = _get_profile_names()
        assert names == []


class TestHandleCompletion:
    def test_bash(self, capsys):
        args = MagicMock()
        args.shell_type = "bash"
        result = handle_completion_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "complete" in captured.out

    def test_zsh(self, capsys):
        args = MagicMock()
        args.shell_type = "zsh"
        result = handle_completion_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "#compdef" in captured.out

    def test_fish(self, capsys):
        args = MagicMock()
        args.shell_type = "fish"
        result = handle_completion_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "complete -c" in captured.out

    @patch("openconnect_saml.completion.config")
    def test_hidden_profiles(self, mock_config, capsys):
        from openconnect_saml.config import Config

        cfg = Config()
        cfg.add_profile("work", {"server": "vpn.com"})
        mock_config.load.return_value = cfg

        args = MagicMock()
        args.shell_type = "_profiles"
        result = handle_completion_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "work" in captured.out

    def test_install(self, capsys, tmp_path):
        args = MagicMock()
        args.shell_type = "install"
        with patch("openconnect_saml.completion.Path") as mock_path:
            mock_home = tmp_path
            mock_path.home.return_value = mock_home
            # Create needed dirs
            bash_dir = mock_home / ".local" / "share" / "bash-completion" / "completions"
            bash_dir.mkdir(parents=True, exist_ok=True)
            zsh_dir = mock_home / ".zsh" / "completions"
            zsh_dir.mkdir(parents=True, exist_ok=True)
            fish_dir = mock_home / ".config" / "fish" / "completions"
            fish_dir.mkdir(parents=True, exist_ok=True)

            _install_completions_to(tmp_path)

    def test_unknown_shell(self, capsys):
        """Should not happen due to argparse choices, but defensive."""
        args = MagicMock()
        args.shell_type = "powershell"
        result = handle_completion_command(args)
        assert result == 1


def _install_completions_to(base_path):
    """Helper to test install without modifying real home."""

    from openconnect_saml.completion import _bash_completion, _fish_completion, _zsh_completion

    bash_dir = base_path / ".local" / "share" / "bash-completion" / "completions"
    bash_dir.mkdir(parents=True, exist_ok=True)
    (bash_dir / "openconnect-saml").write_text(_bash_completion())

    zsh_dir = base_path / ".zsh" / "completions"
    zsh_dir.mkdir(parents=True, exist_ok=True)
    (zsh_dir / "_openconnect-saml").write_text(_zsh_completion())

    fish_dir = base_path / ".config" / "fish" / "completions"
    fish_dir.mkdir(parents=True, exist_ok=True)
    (fish_dir / "openconnect-saml.fish").write_text(_fish_completion())

    # Verify files exist
    assert (bash_dir / "openconnect-saml").exists()
    assert (zsh_dir / "_openconnect-saml").exists()
    assert (fish_dir / "openconnect-saml.fish").exists()
    return 0
