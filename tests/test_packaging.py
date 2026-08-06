"""
Invariants of the PyInstaller spec.

Every failure guarded here is invisible until someone runs the packaged
executable, which is the worst place to discover it. Two have already
happened:

* Bundling the decoder assets to ``src/assets`` created a real directory
  named ``src`` in the bundle, which shadowed the frozen ``src`` package. The
  application died at startup with ``No module named 'src.popups'``. Nothing
  in the source tree or the test suite could have caught it.

* ``pikepdf`` was never listed in ``requirements.txt``, so ``build.bat``
  installed everything except it and the analysis silently dropped it.
  TouchUp extraction and the Tier 2 glyph renderer both need it, so the whole
  feature failed at runtime in the shipped build while working perfectly from
  source.
"""

import ast
import re
import unittest
from pathlib import Path

from src.cid_fonts import BUNDLED_ASSET_DIRNAME

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "PDFRecon.spec"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"


def _spec_source() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _literal_list(name: str) -> list:
    """Extract a top-level list literal from the spec without executing it."""
    tree = ast.parse(_spec_source())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return []
    return []


class TestSpecExists(unittest.TestCase):
    def test_spec_is_present_and_tracked(self):
        """
        The spec must be in the repository.

        It used to be listed in .gitignore, so a fix to it could not be
        committed and a fresh clone would build a broken executable.
        """
        self.assertTrue(SPEC_PATH.is_file(), "PDFRecon.spec is missing")
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        entries = {line.strip() for line in gitignore.splitlines()}
        self.assertNotIn("PDFRecon.spec", entries,
                         "PDFRecon.spec must not be ignored; the build depends on it")


class TestBundledAssets(unittest.TestCase):
    def test_assets_are_bundled(self):
        datas = _literal_list("datas")
        targets = {str(target) for _source, target in datas}
        self.assertIn(
            BUNDLED_ASSET_DIRNAME, targets,
            "the decoder assets are not bundled; Tier 1 loses the Adobe Glyph "
            "List and Tier 2 loses the reference font, both silently")

    def test_asset_target_does_not_shadow_a_package(self):
        """
        A data target must not be named after an importable package.

        PyInstaller creates a real directory for each data entry. A directory
        called "src" shadows the frozen "src" package and the application
        cannot start.
        """
        package_names = {
            path.name for path in REPO_ROOT.iterdir()
            if path.is_dir() and (path / "__init__.py").is_file()
        }
        self.assertIn("src", package_names, "expected src to be a package")

        for _source, target in _literal_list("datas"):
            first = Path(str(target)).parts[0] if str(target) not in (".", "") else ""
            self.assertNotIn(
                first, package_names,
                f"data target {target!r} shadows the {first!r} package")

    def test_code_and_spec_agree_on_the_directory_name(self):
        self.assertIn(f"'{BUNDLED_ASSET_DIRNAME}'", _spec_source())


#: Matches an f-string literal, capturing its body.
_FSTRING_RE = re.compile(
    r"""(?:\b(?:rf|fr|f)) (?P<quote>'''|\"\"\"|'|") (?P<body>.*?) (?<!\\)(?P=quote)""",
    re.VERBOSE | re.DOTALL,
)
#: Matches a replacement field within an f-string body.
_FIELD_RE = re.compile(r"\{([^{}]*)\}")


def backslash_in_fstring_expression(source: str):
    """
    Yield 1-based line numbers of f-strings whose expression holds a backslash.

    Legal from Python 3.12 (PEP 701), a SyntaxError before it. The failure is
    nastier than it sounds: the module does not compile at all, so PyInstaller
    cannot bundle it and the packaged application dies with an unrelated
    "No module named ..." at startup.
    """
    hits = []
    for match in _FSTRING_RE.finditer(source):
        body = match.group("body")
        for field in _FIELD_RE.finditer(body):
            if "\\" in field.group(1):
                hits.append(source.count("\n", 0, match.start()) + 1)
                break
    return hits


class TestSourceRuntimeCompatibility(unittest.TestCase):
    """
    PDFRecon targets Python 3.10+, and build.bat builds with whatever
    "python" resolves to. Syntax accepted only by a newer interpreter than
    the build machine's silently removes a module from the executable.
    """

    def test_no_backslash_inside_fstring_expressions(self):
        offenders = []
        for path in sorted((REPO_ROOT / "src").glob("*.py")):
            for line_no in backslash_in_fstring_expression(
                    path.read_text(encoding="utf-8")):
                offenders.append(f"{path.name}:{line_no}")
        self.assertEqual(
            offenders, [],
            "backslash inside an f-string expression is a SyntaxError before "
            "Python 3.12; assign the value to a name first")

    def test_the_check_detects_the_known_case(self):
        """The regression this guards against, so the check cannot go vacuous."""
        bad = 'tag = f"link_{found_path.replace(\'\\\\\', \'_\')}"'
        self.assertEqual(backslash_in_fstring_expression(bad), [1])

        good = 'safe = p.replace("\\\\", "_")\ntag = f"link_{safe}"'
        self.assertEqual(backslash_in_fstring_expression(good), [])

    def test_backslash_in_the_literal_part_is_fine(self):
        """Only the expression part is restricted, not the text around it."""
        self.assertEqual(backslash_in_fstring_expression(r'x = f"a\nb{value}"'), [])


class TestRuntimeDependencies(unittest.TestCase):
    #: Imported inside functions, so static analysis does not reliably see
    #: them and they must be declared as hidden imports.
    DEFERRED_IMPORTS = ["pikepdf"]

    def test_deferred_imports_are_hidden_imports(self):
        hidden = _literal_list("hiddenimports")
        for name in self.DEFERRED_IMPORTS:
            self.assertIn(
                name, hidden,
                f"{name} is imported inside a function; without a hidden "
                f"import the packaged build may omit it")

    def test_deferred_imports_are_declared_requirements(self):
        """
        build.bat installs only what requirements.txt lists.

        A dependency missing here is installed on a developer machine by
        chance and absent from the build environment, which is exactly how
        pikepdf came to be left out of the executable.
        """
        text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
        declared = {
            re.split(r"[<>=!\[ ]", line.strip())[0].lower()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        for name in self.DEFERRED_IMPORTS:
            self.assertIn(name.lower(), declared,
                          f"{name} is required at runtime but not in requirements.txt")

    def test_pikepdf_is_actually_used_at_runtime(self):
        """Guards against the list above going stale if an import is dropped."""
        sources = " ".join(
            path.read_text(encoding="utf-8")
            for path in (REPO_ROOT / "src").glob("*.py")
        )
        self.assertIn("import pikepdf", sources)


if __name__ == "__main__":
    unittest.main()
