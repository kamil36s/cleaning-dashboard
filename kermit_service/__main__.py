"""Start with: python -B -m kermit_service"""

from .app import create_server


def main():
    server = create_server()
    print(f"Kermit listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
