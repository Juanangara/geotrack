import asyncio


def selector_loop_factory(use_subprocess: bool = False):
    """Event loop for uvicorn. psycopg async does not work with Windows' default ProactorEventLoop."""
    return asyncio.SelectorEventLoop()
