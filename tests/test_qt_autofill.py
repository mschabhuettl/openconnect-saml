"""Exercise the generated Qt script without requiring Qt or a display."""

import ast
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openconnect_saml.config import AutoFillRule


@pytest.fixture(scope="module")
def qt_selectors():
    # Load the actual script builder without importing Qt or starting a GUI.
    path = Path(__file__).parents[1] / "openconnect_saml/browser/webengine_process.py"
    tree = ast.parse(path.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_selectors"
    )
    namespace = {"json": json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["get_selectors"]


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node needed to execute generated JavaScript"
)
@pytest.mark.parametrize("username", ["username", 'user"; throw new Error("injected"); //'])
def test_username_only_preserves_manual_fields_and_does_not_submit(username, qt_selectors):
    rules = [
        AutoFillRule("user", fill="username"),
        AutoFillRule("password", fill="password"),
        AutoFillRule("otp", fill="totp"),
        AutoFillRule("submit", action="click"),
    ]
    credentials = SimpleNamespace(username=username, password=None, totp=None, username_only=True)
    generated = qt_selectors(rules, credentials)
    program = """
        let clicks = 0;
        const elements = {
            user: {value: ""}, password: {value: "manual-password"}, otp: {value: "123456"},
            submit: {value: ""}
        };
        for (const el of Object.values(elements)) {
            el.dispatchEvent = () => {};
            el.click = () => clicks++;
        }
        const document = {querySelector: s => elements[s]};
        function autofill() { GENERATED }
        autofill();
        const filledUsername = elements.user.value;
        elements.user.value = "manually-edited";
        autofill();
        console.log(JSON.stringify({filledUsername, elements, clicks}));
    """.replace("GENERATED", generated)
    result = subprocess.run(
        [shutil.which("node"), "-e", program], capture_output=True, text=True, check=True, timeout=5
    )
    data = json.loads(result.stdout)
    assert data["filledUsername"] == username
    assert data["elements"]["user"]["value"] == "manually-edited"
    assert data["elements"]["password"]["value"] == "manual-password"
    assert data["elements"]["otp"]["value"] == "123456"
    assert data["clicks"] == 0
