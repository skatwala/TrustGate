check:
	uv run black .
	uv run ruff check . --fix
	uv run pyright
	uv run pytest -q
