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
from openconnect_saml.config import (
    BitwardenConfig,
    Credentials,
    OnePasswordConfig,
    PassConfig,
    TwoFAuthConfig,
)
from openconnect_saml.history import ConnectionTracker
from openconnect_saml.profile import get_profiles
from openconnect_saml.totp_providers import (
    BitwardenProvider,
    OnePasswordProvider,
    PassProvider,
    TwoFAuthProvider,
)

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
            f'Required attributes not found in response ("{exc}", '
            "does this endpoint do SSO?), exiting"
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

    profile_name = getattr(args, "profile_name", None)
    if profile_name:
        prof = cfg.get_profile(profile_name)
        if prof:
            if not routes and prof.routes:
                routes = prof.routes
            if not no_routes and prof.no_routes:
                no_routes = prof.no_routes

    # Kill-switch — resolve CLI > config
    ks_cli_enabled = getattr(args, "kill_switch", False)
    ks_cfg = cfg.kill_switch
    ks_persisted = ks_cfg.enabled if ks_cfg else False
    killswitch_enabled = ks_cli_enabled or ks_persisted
    killswitch = None
    if killswitch_enabled:
        killswitch = _setup_killswitch(args, cfg, selected_profile)

    # History tracker
    history_enabled = cfg.connection_history and not getattr(args, "no_history", False)
    tracker = None
    if history_enabled:
        username = args.user or (cfg.credentials.username if cfg.credentials else "")
        tracker = ConnectionTracker(
            server=selected_profile.vpn_url,
            profile=profile_name or "default",
            user=username,
        )

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
            killswitch=killswitch,
            tracker=tracker,
        )

    if notify:
        from openconnect_saml.notify import notify_connected

        notify_connected(selected_profile.vpn_url)

    if tracker:
        tracker.start()

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
            useragent=getattr(args, "useragent", None),
        )
        return rc
    except KeyboardInterrupt:
        logger.warn("CTRL-C pressed, exiting")
        return 0
    finally:
        if notify:
            from openconnect_saml.notify import notify_disconnected

            notify_disconnected(selected_profile.vpn_url)
        if tracker:
            tracker.stop()
        # Only auto-disable kill-switch if it was a CLI-session enablement.
        # If the user persisted it in config, keep it active.
        if killswitch and ks_cli_enabled and not ks_persisted:
            try:
                killswitch.disable()
            except Exception as exc:
                logger.warning("Could not disable kill-switch on exit", error=str(exc))
        handle_disconnect(cfg.on_disconnect)


def _setup_killswitch(args, cfg, selected_profile):
    """Build a KillSwitch instance and enable it. Returns the instance or None."""
    try:
        from openconnect_saml.killswitch import (
            KillSwitch,
            KillSwitchConfig,
            KillSwitchError,
            KillSwitchNotSupported,
        )
    except ImportError as exc:
        logger.error("Cannot import kill-switch module", error=str(exc))
        return None

    dns_servers: list[str] = list(getattr(args, "ks_allow_dns", None) or [])
    if cfg.kill_switch and not dns_servers:
        dns_servers = list(cfg.kill_switch.dns_servers)
    allow_lan = getattr(args, "ks_allow_lan", False) or (
        cfg.kill_switch.allow_lan if cfg.kill_switch else False
    )
    ipv6 = not getattr(args, "ks_no_ipv6", False)
    if cfg.kill_switch:
        ipv6 = ipv6 and cfg.kill_switch.ipv6

    ks_config = KillSwitchConfig(
        server_host=selected_profile.vpn_url,
        server_port=getattr(args, "ks_port", 443) or 443,
        dns_servers=dns_servers,
        allow_lan=allow_lan,
        ipv6=ipv6,
        sudo=getattr(args, "ks_sudo", None),
    )

    try:
        ks = KillSwitch(ks_config)
        ks.enable()
        logger.info("Kill-switch active — traffic locked to VPN")
        return ks
    except KillSwitchNotSupported as exc:
        logger.warning("Kill-switch not supported on this platform", error=str(exc))
        return None
    except KillSwitchError as exc:
        logger.error("Kill-switch setup failed", error=str(exc))
        return None


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
    killswitch=None,
    tracker=None,
):
    """Run openconnect with automatic reconnection on failure."""
    import time

    if notify:
        from openconnect_saml.notify import (
            notify_connected,
            notify_disconnected,
            notify_error,
            notify_reconnecting,
        )

        notify_connected(selected_profile.vpn_url)

    if tracker:
        tracker.start()

    attempt = 0
    try:
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
                    useragent=getattr(args, "useragent", None),
                )
            except KeyboardInterrupt:
                logger.warn("CTRL-C pressed, stopping reconnect loop")
                if notify:
                    notify_disconnected(selected_profile.vpn_url)
                if tracker:
                    tracker.stop("user interrupted")
                handle_disconnect(cfg.on_disconnect)
                return 0

            if rc == 0:
                if notify:
                    notify_disconnected(selected_profile.vpn_url)
                if tracker:
                    tracker.stop("clean exit")
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
                if tracker:
                    tracker.error(f"max retries ({max_retries}) reached")
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
            if tracker:
                tracker.reconnecting(attempt, delay)

            try:
                time.sleep(delay)
            except KeyboardInterrupt:
                logger.warn("CTRL-C pressed during backoff, exiting")
                if tracker:
                    tracker.stop("user interrupted during backoff")
                handle_disconnect(cfg.on_disconnect)
                return 0

            try:
                auth_response, selected_profile = asyncio.run(_run(args, cfg))
            except KeyboardInterrupt:
                logger.warn("CTRL-C pressed during re-authentication, exiting")
                if tracker:
                    tracker.stop("user interrupted during re-auth")
                handle_disconnect(cfg.on_disconnect)
                return 0
            except Exception as exc:
                logger.error("Re-authentication failed", error=str(exc))
                if tracker:
                    tracker.error(f"re-auth failed: {exc}")
                continue
    finally:
        # Only clear transient kill-switch — persistent ones stay.
        if (
            killswitch
            and getattr(args, "kill_switch", False)
            and not (cfg.kill_switch and cfg.kill_switch.enabled)
        ):
            try:
                killswitch.disable()
            except Exception as exc:
                logger.warning("Could not disable kill-switch on exit", error=str(exc))


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
    totp_source = getattr(args, "totp_source", None) or (
        credentials.totp_source if credentials else "local"
    )

    if credentials and totp_source == "bitwarden":
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
        cfg.bitwarden = BitwardenConfig(item_id=bw_item_id)
        logger.info("Using Bitwarden TOTP provider")

    elif credentials and totp_source == "1password":
        op_item = getattr(args, "op_item", None)
        op_vault = getattr(args, "op_vault", None)
        op_account = getattr(args, "op_account", None)
        if cfg.onepassword:
            op_item = op_item or cfg.onepassword.item
            op_vault = op_vault or cfg.onepassword.vault or None
            op_account = op_account or cfg.onepassword.account or None
        if not op_item:
            logger.error(
                "1Password TOTP source requires --1password-item (or [1password] config section)"
            )
            raise ValueError("Missing 1Password configuration", 23)
        credentials.totp_source = "1password"
        credentials.set_totp_provider(
            OnePasswordProvider(item=op_item, vault=op_vault, account=op_account)
        )
        cfg.onepassword = OnePasswordConfig(
            item=op_item, vault=op_vault or "", account=op_account or ""
        )
        logger.info("Using 1Password TOTP provider")

    elif credentials and totp_source == "pass":
        pass_entry = getattr(args, "pass_entry", None)
        if cfg.pass_:
            pass_entry = pass_entry or cfg.pass_.entry
        if not pass_entry:
            logger.error("pass TOTP source requires --pass-entry (or [pass] config section)")
            raise ValueError("Missing pass configuration", 24)
        credentials.totp_source = "pass"
        credentials.set_totp_provider(PassProvider(entry=pass_entry))
        cfg.pass_ = PassConfig(entry=pass_entry)
        logger.info("Using pass TOTP provider")

    elif credentials and totp_source == "2fauth":
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
        cfg.twofauth = TwoFAuthConfig(
            url=twofauth_url, token=twofauth_token, account_id=twofauth_account_id
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

    timeout = getattr(args, "timeout", None) or cfg.timeout or 30

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
            "The selection will be <b>saved</b> and not asked again unless the "
            "<pre>--profile-selector</pre> command line option is used"
        ),
        values=[(p, p.name) for i, p in enumerate(profile_list)],
    ).run_async()
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
    useragent=None,
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

    user_agent = useragent
    if not user_agent:
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
        proc = subprocess.Popen(command_line, stdin=subprocess.PIPE)  # nosec
        proc.stdin.write(session_token)
        proc.stdin.close()
        handle_connect(on_connect)
        return proc.wait()
    return subprocess.run(command_line, input=session_token).returncode  # nosec


def _validate_hook_command(command):
    """Basic validation for on-connect/on-disconnect hook commands."""
    if not command:
        return True
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
