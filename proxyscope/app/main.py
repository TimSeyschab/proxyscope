import sys
from argparse import ArgumentParser

from proxyscope.app.application import ApplicationOptions, ProxyApplication


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Interactive HTTP/HTTPS debugging proxy")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", default=8080, type=int, help="Port to bind")
    parser.add_argument("--config", default=None, help="Path to JSON runtime configuration file")
    parser.add_argument("--mitm", choices=("on", "off"), default=None, help="Override MITM interception mode")
    parser.add_argument("--certs-dir", default=None, help="Directory for MITM CA and host certificates")
    parser.add_argument("--no-ui", action="store_true", help="Disable interactive runtime CLI UI")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    options = ApplicationOptions(
        host=args.host,
        port=args.port,
        config_path=args.config,
        mitm_enabled=None if args.mitm is None else args.mitm == "on",
        certs_dir=args.certs_dir,
        use_ui=not args.no_ui and sys.stdin.isatty() and sys.stdout.isatty(),
    )
    with ProxyApplication(options) as application:
        application.run()


if __name__ == "__main__":
    main()
