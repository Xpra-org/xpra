# Repository preferences

- Allow Python lines up to 150 characters. Do not flag or reflow lines merely
  because they exceed 79 or 120 characters.
- Use the repository's lint configuration. When running standalone Flake8
  without support for `pyproject.toml`, pass `--max-line-length=150` explicitly.

# Backport verification

- Run changed Python test modules and check all changed Python files, including
  tests, for undefined names. Compiling or importing a module does not catch a
  missing import used only inside a test method (such as `unittest.mock.patch`).
