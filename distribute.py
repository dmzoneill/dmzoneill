"""Distribute Dependabot config and default-branch workflow triggers."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent / "dependabot.yml"
SKIP_DIRS = {
    ".bundle",
    ".git",
    ".terraform",
    ".venv",
    "__pycache__",
    "bower_components",
    "node_modules",
    "site-packages",
    "vendor",
    "venv",
}
ROOT_ECOSYSTEMS = {"devcontainers", "github-actions"}
ECOSYSTEM_ORDER = (
    "github-actions",
    "npm",
    "bun",
    "pip",
    "uv",
    "composer",
    "gomod",
    "bundler",
    "cargo",
    "nuget",
    "dotnet-sdk",
    "maven",
    "gradle",
    "sbt",
    "docker",
    "docker-compose",
    "helm",
    "terraform",
    "opentofu",
    "gitsubmodule",
    "pub",
    "mix",
    "elm",
    "swift",
    "nix",
    "conda",
    "devcontainers",
    "pre-commit",
    "rust-toolchain",
    "bazel",
    "vcpkg",
    "julia",
    "deno",
)
EXACT_SIGNALS = {
    ".gitmodules": ("gitsubmodule", "manifest"),
    ".pre-commit-config.yaml": ("pre-commit", "manifest"),
    "Cargo.lock": ("cargo", "lock"),
    "Cargo.toml": ("cargo", "manifest"),
    "Chart.yaml": ("helm", "manifest"),
    "Chart.yml": ("helm", "manifest"),
    "Dockerfile": ("docker", "manifest"),
    "Gemfile": ("bundler", "manifest"),
    "Gemfile.lock": ("bundler", "lock"),
    "MODULE.bazel": ("bazel", "manifest"),
    "Package.swift": ("swift", "manifest"),
    "Pipfile": ("pip", "manifest"),
    "Pipfile.lock": ("pip", "lock"),
    "Project.toml": ("julia", "manifest"),
    "WORKSPACE": ("bazel", "manifest"),
    "WORKSPACE.bazel": ("bazel", "manifest"),
    "build.gradle": ("gradle", "manifest"),
    "build.gradle.kts": ("gradle", "manifest"),
    "build.sbt": ("sbt", "manifest"),
    "bun.lock": ("bun", "lock"),
    "bun.lockb": ("bun", "lock"),
    "composer.json": ("composer", "manifest"),
    "composer.lock": ("composer", "lock"),
    "compose.yaml": ("docker-compose", "manifest"),
    "compose.yml": ("docker-compose", "manifest"),
    "deno.json": ("deno", "manifest"),
    "deno.jsonc": ("deno", "manifest"),
    "deno.lock": ("deno", "lock"),
    "docker-compose.yaml": ("docker-compose", "manifest"),
    "docker-compose.yml": ("docker-compose", "manifest"),
    "elm.json": ("elm", "manifest"),
    "environment.yaml": ("conda", "manifest"),
    "environment.yml": ("conda", "manifest"),
    "flake.nix": ("nix", "manifest"),
    "global.json": ("dotnet-sdk", "manifest"),
    "go.mod": ("gomod", "manifest"),
    "mix.exs": ("mix", "manifest"),
    "npm-shrinkwrap.json": ("npm", "lock"),
    "nuget.config": ("nuget", "manifest"),
    "package-lock.json": ("npm", "lock"),
    "package.json": ("npm", "manifest"),
    "packages.config": ("nuget", "manifest"),
    "pnpm-lock.yaml": ("npm", "lock"),
    "poetry.lock": ("pip", "lock"),
    "pom.xml": ("maven", "manifest"),
    "pubspec.yaml": ("pub", "manifest"),
    "pyproject.toml": ("pip", "pyproject"),
    "rust-toolchain": ("rust-toolchain", "manifest"),
    "rust-toolchain.toml": ("rust-toolchain", "manifest"),
    "settings.gradle": ("gradle", "manifest"),
    "settings.gradle.kts": ("gradle", "manifest"),
    "setup.cfg": ("pip", "manifest"),
    "setup.py": ("pip", "setup.py"),
    "uv.lock": ("uv", "lock"),
    "vcpkg.json": ("vcpkg", "manifest"),
    "yarn.lock": ("npm", "lock"),
}
NUGET_SUFFIXES = (".csproj", ".fsproj", ".nuspec", ".sln", ".vbproj")
MANAGED_HEADER = (
    "---\n"
    "# Managed by https://github.com/dmzoneill/dmzoneill setup.sh.\n"
    "# Entries follow manifests detected in this repository.\n"
)


def _ignored(path):
    return any(part in SKIP_DIRS for part in path.split("/"))


def _directory(path):
    parent = str(Path(path).parent)
    if parent == ".":
        return ""
    return parent


def _dependabot_directory(directory):
    if directory == "":
        return "/"
    return "/" + directory


def _signals_for(path):
    name = Path(path).name
    signals = []
    if name in EXACT_SIGNALS:
        signals.append(EXACT_SIGNALS[name])
    if name.startswith("requirements") and name.endswith(".txt"):
        signals.append(("pip", "manifest"))
    if name.startswith("Dockerfile."):
        signals.append(("docker", "manifest"))
    if name.endswith(".dockerfile"):
        signals.append(("docker", "manifest"))
    if name.endswith(NUGET_SUFFIXES):
        signals.append(("nuget", "manifest"))
    if name.endswith(".tf"):
        signals.append(("terraform", "manifest"))
    if name.endswith(".tofu"):
        signals.append(("opentofu", "manifest"))
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == ".github" and parts[1] == "workflows":
        if name.endswith((".yml", ".yaml")):
            signals.append(("github-actions", "root"))
    if name in {"action.yml", "action.yaml"} and path.count("/") == 0:
        signals.append(("github-actions", "root"))
    if ".devcontainer" in parts and name == "devcontainer.json":
        signals.append(("devcontainers", "root"))
    if _directory(path).endswith("requirements") and name.endswith(".txt"):
        signals.append(("pip", "manifest"))
    return signals


def setup_py_is_manifest(text):
    """True when setup.py looks like a packaging manifest."""
    if not text or not text.strip():
        return True
    if "setuptools" in text or "distutils" in text:
        return True
    return re.search(r"(?m)^[ \t]*setup[ \t]*\(", text) is not None


def _resolve_directory(signals, setup_py_text):
    ecosystems = {item[0] for item in signals}
    pip_kinds = {kind for eco, kind in signals if eco == "pip"}
    if ("uv", "lock") in signals and pip_kinds <= {"pyproject"}:
        ecosystems.discard("pip")
    if ("bun", "lock") in signals:
        ecosystems.discard("npm")
    if pip_kinds <= {"setup.py"} and not setup_py_is_manifest(setup_py_text):
        ecosystems.discard("pip")
    return ecosystems


def detect(paths, read_setup_py):
    """Return {ecosystem: [dependabot directories]} for repository paths."""
    grouped = {}
    root_scoped = set()
    for path in paths:
        if _ignored(path):
            continue
        signals = _signals_for(path)
        if not signals:
            continue
        directory = _directory(path)
        bucket = grouped.setdefault(directory, [])
        bucket.extend(signals)
        for ecosystem, kind in signals:
            if kind == "root" or ecosystem in ROOT_ECOSYSTEMS:
                root_scoped.add(ecosystem)

    found = {ecosystem: set() for ecosystem in root_scoped}
    for directory, signals in grouped.items():
        setup_path = f"{directory}/setup.py" if directory else "setup.py"
        setup_text = ""
        if any(item == ("pip", "setup.py") for item in signals):
            setup_text = read_setup_py(setup_path)
        for ecosystem in _resolve_directory(signals, setup_text):
            if ecosystem in ROOT_ECOSYSTEMS:
                found.setdefault(ecosystem, set()).add("/")
                continue
            found.setdefault(ecosystem, set()).add(_dependabot_directory(directory))

    for ecosystem in root_scoped:
        found.setdefault(ecosystem, set()).add("/")

    rendered = {}
    for ecosystem, directories in found.items():
        if not directories:
            continue
        rendered[ecosystem] = sorted(directories, key=lambda item: (item != "/", item))
    return rendered


def _prototype_block(template_text):
    marker = "  - package-ecosystem:"
    start = template_text.find(marker)
    if start < 0:
        raise ValueError("dependabot template has no updates entry")
    return template_text[start:].strip() + "\n"


def _block_for(prototype, ecosystem, directories):
    lines = []
    for line in prototype.splitlines():
        if "package-ecosystem:" in line:
            lines.append(f'  - package-ecosystem: "{ecosystem}"')
            continue
        if re.match(r"    directory:", line):
            lines.extend(_directory_lines(directories))
            continue
        if re.match(r"      [A-Za-z0-9_|-]+:$", line):
            lines.append(f"      {ecosystem}:")
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def _directory_lines(directories):
    if len(directories) == 1:
        return [f'    directory: "{directories[0]}"']
    lines = ["    directories:"]
    lines.extend(f'      - "{directory}"' for directory in directories)
    return lines


def render(paths, read_setup_py, template_text):
    """Render dependabot.yml text, or '' when nothing should be written."""
    found = detect(paths, read_setup_py)
    if not found:
        return ""
    prototype = _prototype_block(template_text)
    ordered = [name for name in ECOSYSTEM_ORDER if name in found]
    ordered.extend(sorted(set(found) - set(ordered)))
    blocks = [_block_for(prototype, name, found[name]) for name in ordered]
    return MANAGED_HEADER + "version: 2\nupdates:\n" + "".join(blocks)


def iter_files(root):
    """Yield relative file paths, skipping dependency and VCS directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            yield full.relative_to(root).as_posix()


def render_tree(root, template_text=None):
    root = Path(root)
    template_text = template_text if template_text is not None else TEMPLATE_PATH.read_text(encoding="utf-8")
    paths = list(iter_files(root))

    def read_setup_py(rel):
        file_path = root / rel
        if not file_path.is_file():
            return ""
        return file_path.read_text(encoding="utf-8", errors="replace")

    return render(paths, read_setup_py, template_text)


def _github_token():
    return os.getenv("GITHUB_TOKEN") or os.getenv("PROFILE_HOOK") or ""


def _github_get(url, token):
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "dmzoneill-distribute")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_remote_paths(owner, repo, branch, token):
    quoted = urllib.parse.quote(branch, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{quoted}?recursive=1"
    try:
        payload = _github_get(url, token)
    except urllib.error.URLError as exc:
        detail = getattr(exc, "code", None) or getattr(exc, "reason", exc)
        print(f"Tree lookup failed for {owner}/{repo}@{branch}: {detail}", file=sys.stderr)
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Tree lookup returned invalid JSON for {owner}/{repo}@{branch}: {exc}", file=sys.stderr)
        return None
    if data.get("truncated"):
        print(f"Tree truncated for {owner}/{repo}@{branch}", file=sys.stderr)
        return None
    return [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]


def _fetch_setup_py(owner, repo, branch, path, token):
    quoted_branch = urllib.parse.quote(branch, safe="")
    quoted_path = urllib.parse.quote(path, safe="/")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{quoted_branch}/{quoted_path}"
    try:
        return _github_get(url, token).decode("utf-8", errors="replace")
    except urllib.error.URLError:
        return ""


def render_remote(owner, repo, branch, extra_paths):
    token = _github_token()
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    paths = fetch_remote_paths(owner, repo, branch, token)
    if paths is None:
        return None
    merged = list(dict.fromkeys(list(paths) + list(extra_paths)))
    cache = {}

    def read_setup_py(rel):
        if rel not in cache:
            cache[rel] = _fetch_setup_py(owner, repo, branch, rel, token)
        return cache[rel]

    return render(merged, read_setup_py, template_text)


_FLOW_BRANCHES = re.compile(r"^([ \t]*)branches:[ \t]*\[(.*)\][ \t]*$")
_BLOCK_BRANCHES = re.compile(r"^([ \t]*)branches:[ \t]*$")
_BLOCK_ITEM = re.compile(r"^([ \t]+)-[ \t]+(.*)$")


def _branch_names(body):
    names = []
    for quoted, bare in re.findall(r"""["']([^"']+)["']|([^\s,\"'\]]+)""", body):
        names.append(quoted or bare)
    return names


def ensure_default_branch(text, branch):
    """Add branch to workflow branches filters that omit it."""
    lines = text.splitlines()
    output = []
    index = 0
    while index < len(lines):
        flow = _FLOW_BRANCHES.match(lines[index])
        if flow:
            names = _branch_names(flow.group(2))
            if branch not in names:
                names.append(branch)
                quoted = ", ".join(f'"{name}"' for name in names)
                output.append(f"{flow.group(1)}branches: [{quoted}]")
            else:
                output.append(lines[index])
            index += 1
            continue
        block = _BLOCK_BRANCHES.match(lines[index])
        if block:
            item_indent = None
            items = []
            cursor = index + 1
            while cursor < len(lines):
                item = _BLOCK_ITEM.match(lines[cursor])
                if item is None or len(item.group(1)) <= len(block.group(1)):
                    break
                if item_indent is None:
                    item_indent = item.group(1)
                if item.group(1) != item_indent:
                    break
                items.append(item.group(2).strip().strip("'\""))
                cursor += 1
            output.extend(lines[index:cursor])
            if items and item_indent and branch not in items:
                output.append(f'{item_indent}- "{branch}"')
            index = cursor
            continue
        output.append(lines[index])
        index += 1
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(output) + suffix


def _print(text):
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")


def _cmd_dependabot(argv):
    if len(argv) != 1:
        print("usage: dependabot DIR", file=sys.stderr)
        return 2
    _print(render_tree(argv[0]))
    return 0


def _cmd_dependabot_remote(argv):
    if len(argv) < 3:
        print("usage: dependabot-remote OWNER REPO BRANCH [--ensure PATH]", file=sys.stderr)
        return 2
    owner, repo, branch = argv[0], argv[1], argv[2]
    extra = []
    index = 3
    while index < len(argv):
        if argv[index] != "--ensure" or index + 1 >= len(argv):
            print("usage: dependabot-remote OWNER REPO BRANCH [--ensure PATH]", file=sys.stderr)
            return 2
        extra.append(argv[index + 1])
        index += 2
    rendered = render_remote(owner, repo, branch, extra)
    if rendered is None:
        return 1
    _print(rendered)
    return 0


def _cmd_needs_default_branch(argv):
    if len(argv) != 2:
        print("usage: needs-default-branch FILE BRANCH", file=sys.stderr)
        return 2
    text = Path(argv[0]).read_text(encoding="utf-8")
    if ensure_default_branch(text, argv[1]) == text:
        return 0
    return 1


def _cmd_ensure_default_branch(argv):
    if len(argv) != 2:
        print("usage: ensure-default-branch FILE BRANCH", file=sys.stderr)
        return 2
    file_path = Path(argv[0])
    text = file_path.read_text(encoding="utf-8")
    file_path.write_text(ensure_default_branch(text, argv[1]), encoding="utf-8")
    return 0


def _usage():
    print(
        "usage: distribute.py dependabot DIR | dependabot-remote OWNER REPO BRANCH | "
        "needs-default-branch FILE BRANCH | ensure-default-branch FILE BRANCH",
        file=sys.stderr,
    )


def main(argv):
    if len(argv) < 2:
        _usage()
        return 2
    handlers = {
        "--self-test": _self_test,
        "dependabot": _cmd_dependabot,
        "dependabot-remote": _cmd_dependabot_remote,
        "ensure-default-branch": _cmd_ensure_default_branch,
        "needs-default-branch": _cmd_needs_default_branch,
    }
    handler = handlers.get(argv[1])
    if handler is None:
        print("unknown command: " + argv[1], file=sys.stderr)
        return 2
    if argv[1] == "--self-test":
        return handler()
    return handler(argv[2:])


def _self_test():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    paths = [
        "package.json",
        "requirements.txt",
        "composer.json",
        "go.mod",
        "Dockerfile",
        "chrome-plugin/package.json",
        ".github/workflows/main.yml",
        "setup.py",
    ]

    def read_setup_py(_path):
        return "print('not a package')\n"

    found = detect(paths, read_setup_py)
    assert found["npm"] == ["/", "/chrome-plugin"]
    assert found["pip"] == ["/"]
    assert found["composer"] == ["/"]
    assert found["gomod"] == ["/"]
    assert found["docker"] == ["/"]
    assert found["github-actions"] == ["/"]
    assert "pip" not in detect(["setup.py"], read_setup_py)

    uv_paths = ["pyproject.toml", "uv.lock", "package.json", "bun.lock"]
    uv_found = detect(uv_paths, read_setup_py)
    assert uv_found["uv"] == ["/"]
    assert "pip" not in uv_found
    assert uv_found["bun"] == ["/"]
    assert "npm" not in uv_found

    package = detect(["setup.py"], lambda _path: "from setuptools import setup\nsetup(name='x')\n")
    assert package["pip"] == ["/"]

    rendered = render(paths, read_setup_py, template)
    assert 'package-ecosystem: "github-actions"' in rendered
    assert 'package-ecosystem: "npm"' in rendered
    assert 'package-ecosystem: "pip"' in rendered
    assert 'package-ecosystem: "composer"' in rendered
    assert 'package-ecosystem: "gomod"' in rendered
    assert 'directory: "/chrome-plugin"' not in rendered
    assert '"/chrome-plugin"' in rendered
    assert rendered.startswith("---\n")

    stock = 'on:\n  push:\n    branches: [ "main" ]\n  pull_request:\n    branches:\n      - main\n'
    patched = ensure_default_branch(stock, "master")
    assert 'branches: ["main", "master"]' in patched
    assert '- "master"' in patched
    assert ensure_default_branch(patched, "master") == patched
    assert ensure_default_branch("on:\n  push:\n", "master") == "on:\n  push:\n"
    print("self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
