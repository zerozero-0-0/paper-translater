import uvicorn

HOST = "127.0.0.1"
PORT = 8787


def main() -> None:
    uvicorn.run(
        "paper_translator.app:default_app",
        factory=True,
        host=HOST,
        port=PORT,
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
