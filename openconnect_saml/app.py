import asyncio
import getpass
import json
import logging
import os
import shlex
import shutil
import signal
import subprocess  # nosec
from pathlib import Path

import structlog
from prompt_toolkit import HTML
from prompt_toolkit.shortcuts import radiolist_dialog
from requests.exceptions import HTTPError

from openconnect_saml import config
from openconnect_saml.authenticator import (
    CHROME_MODE,
    HEADLESS_MODE,
    Authenticator,
    AuthResponseError,
)
from openconnect_saml.browser import Terminated
from openconnect_saml.config import BitwardenConfig, Credentials, TwoFAuthConfig
from openconnect_saml.profile import get_profiles
from openconnect_saml.totp_providers import BitwardenProvider, TwoFAuthProvider

logger = structlog.get_logger()


def run(args):
    configure_logger(logging.getLogger(), args.log_level)

    cfg = config.load()

    try:
        auth_response, selected_profile = asyncio.run(_run(args, cfg))
    except KeyboardInterrupt:
        logger.warn("CTRL-C pressed, exiting")
        return 130
    except ValueError as e:
        msg, retval = e.args
        logger.error(msg)
        return retval
    except Terminated:
        logger.warn("Browser window terminated, exiting")
        return 2
    except AuthResponseError as exc:
        logger.error(
            f'Required attributes not found in response ("{exc}", does this endpoint do SSO?), exiting'
        )
        return 3
    except HTTPError as exc:
        logger.error(f"Request error: {exc}")
        return 4

    config.save(cfg)

    if args.authenticate:
        logger.warn("Exiting after login, as requested")
        details = {
            "host": selected_profile.vpn_url,
            "cookie": auth_response.session_token,
            "fingerprint": auth_response.server_cert_hash,
        }
        if args.authenticate == "json":
            print(json.dumps(details, indent=4))
        elif args.authenticate == "shell":
            print("\n".join(f"{k.upper()}={shlex.quote(v)}" for k, v in details.items()))
        return 0

    reconnect = getattr(args, "reconnect", False)
    max_retries = getattr(args, "max_retries", None)
    notify = getattr(args, "notify", False) or cfg.notifications

    # Resolve routes: CLI > profile config
    routes = getattr(args, "routes", None) or []
    no_routes = getattr(args, "no_routes", None) or []

    # Check profile routes if available
    profile_name = getattr(args, "profile_name", None)
    if profile_name:
        prof = cfg.get_profile(profile_name)
        if prof:
            if not routes and prof.routes:
                routes = prof.routes
            if not no_routes and prof.no_routes:
                no_routes = prof.no_routes

    if reconnect:
        return _run_with_reconnect(
            args,
            cfg,
            auth_response,
            selected_profile,
            max_retries=max_retries,
            notify=notify,
            routes=routes,
            no_routes=no_routes,
        )

    if notify:
        from openconnect_saml.notify import notify_connected

        notify_connected(selected_profile.vpn_url)

    try:
        rc = run_openconnect(
            auth_response,
            selected_profile,
            args.proxy,
            args.ac_version,
            args.openconnect_args,
            no_sudo=getattr(args, "no_sudo", False),
            csd_wrapper=getattr(args, "csd_wrapper", None),
            on_connect=cfg.on_connect,
            routes=routes,
            no_routes=no_routes,
        )
        return rc
    except KeyboardInterrupt:
        logger.warn("CTRL-C pressed, exiting")
        return 0
    finally:
        if notify:
            from openconnect_saml.notify import notify_disconnected

            notify_disconnected(selected_profile.vpn_url)
        handle_disconnect(cfg.on_disconnect)


# Backoff schedule for reconnection (seconds)
RECONNECT_BACKOFF = [30, 60, 120, 300]


def _run_with_reconnect(
    args,
    cfg,
    auth_response,
    selected_profile,
    max_retries=None,
    notify=False,
    routes=None,
    no_routes=None,
):
    """Run openconnect with automatic reconnection on failure.

    Re-authenticates and reconnects when the VPN process exits unexpectedly.
    Uses exponential backoff: 30s, 60s, 120s, then 300s.

    Parameters
    ----------
    max_retries : int or None
        Maximum reconnection attempts. None means unlimited.
    notify : bool
        Whether to send desktop notifications.
    routes : list or None
        Split-tunnel include routes.
    no_routes : list or None
        Split-tunnel exclude routes.
    """
    import time

    if notify:
        from openconnect_saml.notify import (
            notify_connected,
            notify_disconnected,
            notify_error,
            notify_reconnecting,
        )

        notify_connected(selected_profile.vpn_url)

    attempt = 0
    while True:
        try:
            rc = run_openconnect(
                auth_response,
                selected_profile,
                args.proxy,
                args.ac_version,
                args.openconnect_args,
                no_sudo=getattr(args, "no_sudo", False),
                csd_wrapper=getattr(args, "csd_wrapper", None),
                on_connect=cfg.on_connect,
                routes=routes,
                no_routes=no_routes,
            )
        except KeyboardInterrupt:
            logger.warn("CTRL-C pressed, stopping reconnect loop")
            if notify:
                notify_disconnected(selected_profile.vpn_url)
            handle_disconnect(cfg.on_disconnect)
            return 0

        if rc == 0:
            # Clean exit
            if notify:
                notify_disconnected(selected_profile.vpn_url)
            handle_disconnect(cfg.on_disconnect)
            return 0

        attempt += 1
        if max_retries is not None and attempt >= max_retries:
            logger.error(
                "Max reconnection retries reached",
                attempts=attempt,
                max_retries=max_retries,
            )
            if notify:
                notify_error(selected_profile.vpn_url, f"Max retries ({max_retries}) reached")
            handle_disconnect(cfg.on_disconnect)
            return rc

        backoff_idx = min(attempt - 1, len(RECONNECT_BACKOFF) - 1)
        delay = RECONNECT_BACKOFF[backoff_idx]
        logger.warn(
            "VPN connection dropped, reconnecting",
            attempt=attempt,
            delay=delay,
            exit_code=rc,
        )

        if notify:
            notify_reconnecting(selected_profile.vpn_url, attempt, delay)

        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            logger.warn("CTRL-C pressed during backoff, exiting")
            handle_disconnect(cfg.on_disconnect)
            return 0

        # Re-authenticate
        try:
            auth_response, selected_profile = asyncio.run(_run(args, cfg))
        except KeyboardInterrupt:
            logger.warn("CTRL-C pressed during re-authentication, exiting")
            handle_disconnect(cfg.on_disconnect)
            return 0
        except Exception as exc:
            logger.error("Re-authentication failed", error=str(exc))
            # Continue with backoff
            continue


def configure_logger(logger, level):
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    formatter = structlog.stdlib.ProcessorFormatter(processor=structlog.dev.ConsoleRenderer())

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


async def _run(args, cfg):
    # Handle --reset-credentials
    if getattr(args, "reset_credentials", False):
        if args.user:
            logger.info("Resetting stored credentials", user=args.user)
            cred = Credentials(args.user)
            del cred.password
            del cred.totp
        else:
            logger.error("--reset-credentials requires --user")
        raise ValueError("Credentials reset complete", 0)

    credentials = None
    if cfg.credentials:
        credentials = cfg.credentials
    elif args.user:
        credentials = Credentials(args.user)

    if credentials and not credentials.password:
        credentials.password = getpass.getpass(prompt=f"Password ({args.user}): ")
        cfg.credentials = credentials

    # Determine TOTP source: CLI > config > default ("local")
    totp_source = (
        getattr(args, "totp_source", None) or credentials.totp_source if credentials else "local"
    )

    if credentials and totp_source == "bitwarden":
        # Build Bitwarden config from CLI flags or config file
        bw_item_id = getattr(args, "bw_item_id", None)

        if cfg.bitwarden:
            bw_item_id = bw_item_id or cfg.bitwarden.item_id

        if not bw_item_id:
            logger.error(
                "Bitwarden TOTP source requires --bw-item-id (or [bitwarden] config section)"
            )
            raise ValueError("Missing Bitwarden configuration", 22)

        credentials.totp_source = "bitwarden"
        credentials.set_totp_provider(BitwardenProvider(item_id=bw_item_id))
        # Persist Bitwarden config
        cfg.bitwarden = BitwardenConfig(item_id=bw_item_id)
        logger.info("Using Bitwarden TOTP provider")
    elif credentials and totp_source == "2fauth":
        # Build 2FAuth config from CLI flags or config file
        twofauth_url = getattr(args, "twofauth_url", None)
        twofauth_token = getattr(args, "twofauth_token", None)
        twofauth_account_id = getattr(args, "twofauth_account_id", None)

        if cfg.twofauth:
            twofauth_url = twofauth_url or cfg.twofauth.url
            twofauth_token = twofauth_token or cfg.twofauth.token
            twofauth_account_id = (
                twofauth_account_id if twofauth_account_id is not None else cfg.twofauth.account_id
            )

        if not all([twofauth_url, twofauth_token, twofauth_account_id]):
            logger.error(
                "2FAuth TOTP source requires --2fauth-url, --2fauth-token, "
                "and --2fauth-account-id (or [2fauth] config section)"
            )
            raise ValueError("Missing 2FAuth configuration", 21)

        credentials.totp_source = "2fauth"
        credentials.set_totp_provider(
            TwoFAuthProvider(
                url=twofauth_url,
                token=twofauth_token,
                account_id=twofauth_account_id,
            )
        )
        # Persist 2FAuth config
        cfg.twofauth = TwoFAuthConfig(
            url=twofauth_url,
            token=twofauth_token,
            account_id=twofauth_account_id,
        )
        logger.info("Using 2FAuth TOTP provider")
    elif credentials and not credentials.totp:
        credentials.totp = getpass.getpass(
            prompt=f"TOTP secret (leave blank if not required) ({args.user}): "
        )
        cfg.credentials = credentials

    if cfg.default_profile and not (args.use_profile_selector or args.server):
        selected_profile = cfg.default_profile
    elif args.use_profile_selector or args.profile_path:
        profiles = get_profiles(Path(args.profile_path))
        if not profiles:
            raise ValueError("No profile found", 17)

        selected_profile = await select_profile(profiles)
        if not selected_profile:
            raise ValueError("No profile selected", 18)
    elif args.server:
        selected_profile = config.HostProfile(args.server, args.usergroup, args.authgroup)
    else:
        raise ValueError("Cannot determine server address. Invalid arguments specified.", 19)

    cfg.default_profile = config.HostProfile(
        selected_profile.address, selected_profile.user_group, selected_profile.name
    )

    browser_backend = getattr(args, "browser", None)
    if browser_backend == "chrome":
        display_mode = CHROME_MODE
    elif getattr(args, "headless", False) or browser_backend == "headless":
        display_mode = HEADLESS_MODE
    else:
        display_mode = config.DisplayMode[args.browser_display_mode.upper()]

    # Resolve timeout: CLI > config > default
    timeout = getattr(args, "timeout", None) or cfg.timeout or 30

    # Resolve window size: CLI > config > default
    window_size = getattr(args, "window_size", None)
    if window_size:
        try:
            w, h = window_size.split("x")
            cfg.window_width = int(w)
            cfg.window_height = int(h)
        except (ValueError, AttributeError):
            logger.warning("Invalid --window-size format, using defaults", value=window_size)

    ssl_legacy = getattr(args, "ssl_legacy", False)

    auth_response = await authenticate_to(
        selected_profile,
        args.proxy,
        credentials,
        display_mode,
        args.ac_version,
        ssl_legacy=ssl_legacy,
        timeout=timeout,
        window_width=cfg.window_width,
        window_height=cfg.window_height,
    )

    if credentials:
        credentials.save()

    if args.on_disconnect and not cfg.on_disconnect:
        cfg.on_disconnect = args.on_disconnect

    on_connect = getattr(args, "on_connect", "")
    if on_connect and not cfg.on_connect:
        cfg.on_connect = on_connect

    return auth_response, selected_profile


async def select_profile(profile_list):
    selection = await radiolist_dialog(
        title="Select AnyConnect profile",
        text=HTML(
            "The following AnyConnect profiles are detected.\n"
            "The selection will be <b>saved</b> and not asked again unless the <pre>--profile-selector</pre> command line option is used"
        ),
        values=[(p, p.name) for i, p in enumerate(profile_list)],
    ).run_async()
    # Somehow prompt_toolkit sets up a bogus signal handler upon exit
    # TODO: Report this issue upstream
    if hasattr(signal, "SIGWINCH"):
        asyncio.get_running_loop().remove_signal_handler(signal.SIGWINCH)
    if not selection:
        return selection
    logger.info("Selected profile", profile=selection.name)
    return selection


def authenticate_to(
    host,
    proxy,
    credentials,
    display_mode,
    version,
    ssl_legacy=False,
    timeout=30,
    window_width=800,
    window_height=600,
):
    logger.info("Authenticating to VPN endpoint", name=host.name, address=host.address)
    return Authenticator(
        host,
        proxy,
        credentials,
        version,
        ssl_legacy=ssl_legacy,
        timeout=timeout,
        window_width=window_width,
        window_height=window_height,
    ).authenticate(display_mode)


def run_openconnect(
    auth_info,
    host,
    proxy,
    version,
    args,
    no_sudo=False,
    csd_wrapper=None,
    on_connect="",
    routes=None,
    no_routes=None,
):
    superuser_cmd = None

    if os.name == "nt":
        import ctypes

        if not ctypes.windll.shell32.IsUserAnAdmin():
            logger.error("OpenConnect must be run as Administrator on Windows, exiting")
            return 20
    elif not no_sudo:
        superuser_cmd = next((prog for prog in ("doas", "sudo") if shutil.which(prog)), None)
        if not superuser_cmd:
            logger.error(
                "Cannot find suitable program to execute as superuser (doas/sudo), exiting"
            )
            return 20

    user_agent = (
        f"AnyConnect Win {version}" if os.name == "nt" else f"AnyConnect Linux_64 {version}"
    )
    openconnect_args = [
        "openconnect",
        "--useragent",
        user_agent,
        "--version-string",
        version,
        "--cookie-on-stdin",
        "--servercert",
        auth_info.server_cert_hash,
        *args,
        host.vpn_url,
    ]
    if proxy:
        openconnect_args.extend(["--proxy", proxy])
    if csd_wrapper:
        openconnect_args.extend(["--csd-wrapper", csd_wrapper])

    # Split-tunnel routes
    if routes:
        for route in routes:
            openconnect_args.extend(["--route", route])
    if no_routes:
        for no_route in no_routes:
            openconnect_args.extend(["--no-route", no_route])

    if os.name == "nt":
        command_line = ["powershell.exe", "-Command", shlex.join(openconnect_args)]
    elif superuser_cmd:
        command_line = [superuser_cmd, *openconnect_args]
    else:
        command_line = openconnect_args

    session_token = auth_info.session_token.encode("utf-8")
    logger.debug("Starting OpenConnect", command_line=command_line)

    if on_connect:
        # Run on-connect script via openconnect's --script mechanism would
        # conflict with user-provided scripts, so we run it separately after
        # openconnect is started. Use Popen for non-blocking openconnect.
        proc = subprocess.Popen(command_line, stdin=subprocess.PIPE)  # nosec
        proc.stdin.write(session_token)
        proc.stdin.close()
        handle_connect(on_connect)
        return proc.wait()
    else:
        return subprocess.run(command_line, input=session_token).returncode  # nosec


def _validate_hook_command(command):
    """Basic validation for on-connect/on-disconnect hook commands.

    Rejects commands containing shell metacharacters that could indicate
    injection attempts. Users who need complex commands should use a script file.
    """
    if not command:
        return True
    # Allow paths to scripts and simple commands; warn on suspicious patterns
    suspicious = ["`", "$(", "${", "||", "&&", ";", "\n", "|"]
    for pattern in suspicious:
        if pattern in command:
            logger.warning(
                "Hook command contains suspicious shell metacharacter",
                command=command,
                pattern=pattern,
            )
            return False
    return True


def handle_connect(command):
    if command:
        if not _validate_hook_command(command):
            logger.error(
                "Refusing to run on-connect command with suspicious content",
                command_line=command,
            )
            return 1
        logger.info("Running on-connect command", command_line=command)
        try:
            return subprocess.run(shlex.split(command), timeout=30, shell=False).returncode  # nosec
        except subprocess.TimeoutExpired:
            logger.warning("On-connect command timed out after 30s", command_line=command)
            return 1
        except (FileNotFoundError, OSError) as exc:
            logger.error("On-connect command failed", command_line=command, error=str(exc))
            return 1


def handle_disconnect(command):
    if command:
        if not _validate_hook_command(command):
            logger.error(
                "Refusing to run on-disconnect command with suspicious content",
                command_line=command,
            )
            return 1
        logger.info("Running command on disconnect", command_line=command)
        try:
            return subprocess.run(shlex.split(command), timeout=5, shell=False).returncode  # nosec
        except subprocess.TimeoutExpired:
            logger.warning("On-disconnect command timed out after 5s", command_line=command)
            return 1
        except (FileNotFoundError, OSError) as exc:
            logger.error("On-disconnect command failed", command_line=command, error=str(exc))
            return 1
