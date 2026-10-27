# Repository preferences

- Allow Python lines up to 150 characters. Do not flag or reflow lines merely
  because they exceed 79 or 120 characters.
- Use the repository's lint configuration. When running standalone Flake8
  without support for `pyproject.toml`, pass `--max-line-length=150` explicitly.

# Backport verification

- Do not modify `docs/CHANGELOG.md` until v7.0 is released, including for
  backports and packaging changes. This overrides the backport-review skill's
  changelog guidance; the existing release heading/date does not confirm release.
- Run changed Python test modules and check all changed Python files, including
  tests, for undefined names. Compiling or importing a module does not catch a
  missing import used only inside a test method (such as `unittest.mock.patch`).
