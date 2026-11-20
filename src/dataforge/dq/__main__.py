import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "monitor":
        from .observability import main as monitor_main

        return monitor_main(arguments[1:])
    from .gate import main as gate_main

    return gate_main(arguments)


raise SystemExit(main())
