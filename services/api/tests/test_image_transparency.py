import base64
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry
from app.image_output import inspect_image_output, prepare_image_output
from app.main import new_project
from app.providers.http import OpenAICompatibleImageProvider, ProviderError
from app.storage import ProjectStore


def image_bytes(mode="RGBA", alpha=0, format="PNG"):
    image = Image.new(mode, (16, 16), (120, 90, 200, alpha) if mode == "RGBA" else (120, 90, 200))
    image.putpixel((8, 8), (120, 90, 200, 255) if mode == "RGBA" else (120, 90, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize("prompt,expected", [
    ("我想要一张透明背景的吹风机图片", "transparent"),
    ("A blow dryer on a transparent background", "transparent"),
    ("生成透明图层", "transparent"),
    ("不要透明背景，改成白色背景", "opaque"),
    ("not a transparent background", "opaque"),
    ("透明玻璃杯放在木桌上", None),
    ("Draw a dryer", None),
])
def test_background_intent_fallback(prompt, expected):
    _, params = prepare_image_output(prompt, {})
    assert params.get("background") == expected


def test_explicit_setting_and_transparent_edit_preservation():
    _, options = prepare_image_output("透明背景", {"background": "opaque"}, background="transparent")
    assert options["background"] == "opaque"
    _, options = prepare_image_output("改为橙色", {}, source_transparent=True)
    assert options["background"] == "transparent" and options["output_format"] == "png"
    _, options = prepare_image_output("A dryer", {"background": "transparent", "output_format": "jpeg", "output_compression": 70})
    assert options["output_format"] == "png" and "output_compression" not in options
    _, options = prepare_image_output("A dryer", {"background": "transparent", "output_format": "webp", "output_compression": 70})
    assert options["output_format"] == "webp" and options["output_compression"] == 70


def test_raster_format_defaults_and_rejection_before_network():
    from app.providers.openrouter_image import OpenRouterImageProvider
    assert prepare_image_output('封面', {})[1]['output_format'] == 'png'
    assert prepare_image_output('封面', {'output_format':'JPG'})[1]['output_format'] == 'jpeg'
    provider = OpenRouterImageProvider(base_url='https://fixture.invalid/v1', provider_key='fixture', model='fixture', credentials=SimpleNamespace(get=lambda _: 'fixture'))
    with patch('app.providers.openrouter_image.urllib.request.urlopen') as network:
        with pytest.raises(ProviderError, match='只允许 PNG') as failed:
            provider.generate(prompt='封面', output_format='svg')
        assert failed.value.status_code == 400
        network.assert_not_called()


def test_openrouter_requests_png_even_without_explicit_format():
    from app.providers.openrouter_image import OpenRouterImageProvider
    content = image_bytes()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({'data':[{'b64_json':base64.b64encode(content).decode()}]}).encode()
    provider = OpenRouterImageProvider(base_url='https://fixture.invalid/v1', provider_key='fixture', model='fixture', credentials=SimpleNamespace(get=lambda _: 'fixture'))
    with patch('app.providers.openrouter_image.urllib.request.urlopen', return_value=Response()) as network:
        assert provider.generate(prompt='封面') == content
    assert network.call_count == 1
    assert json.loads(network.call_args.args[0].data)['output_format'] == 'png'


@pytest.mark.parametrize("mode,alpha,transparent", [("RGBA", 0, True), ("RGBA", 128, True), ("RGBA", 255, False), ("RGB", 255, False)])
def test_alpha_is_verified_from_actual_pixels(mode, alpha, transparent):
    result = inspect_image_output(image_bytes(mode, alpha), transparent_requested=True)
    assert result["verified"] is True and result["hasTransparency"] is transparent
    assert bool(result.get("warning")) is not transparent


def test_palette_and_invalid_image_output():
    image = Image.new("P", (2, 2), 0)
    image.info["transparency"] = 0
    out = io.BytesIO(); image.save(out, format="PNG")
    assert inspect_image_output(out.getvalue())["hasTransparency"] is True
    result = inspect_image_output(b"invalid", transparent_requested=True)
    assert result["verified"] is False and result["hasTransparency"] is None and result["warning"]


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"])
@pytest.mark.parametrize("editing", [False, True])
def test_images_api_sends_transparent_for_generation_and_edit(tmp_path, model, editing):
    content = image_bytes()
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"data": [{"b64_json": base64.b64encode(content).decode()}]}).encode()
    def respond(request, **kwargs):
        captured.append(request)
        return Response()
    source = tmp_path / "source.png"; source.write_bytes(content)
    provider = OpenAICompatibleImageProvider(base_url="https://fixture.invalid/v1", provider_key="fixture", model=model, credentials=SimpleNamespace(get=lambda _: "fixture-secret"))
    params = {"background": "transparent", "output_format": "jpeg", "output_compression": 80, "input_fidelity": "high", "quality": "high"}
    if editing: params["source_asset_path"] = str(source)
    with patch("app.providers.http.urllib.request.urlopen", respond):
        assert provider.generate(prompt="A blow dryer", **params) == content
    assert len(captured) == 1
    request = captured[0]
    assert request.get_header("Authorization") == "Bearer fixture-secret"
    assert "input_fidelity" not in request.data.decode(errors="ignore")
    assert "output_compression" not in request.data.decode(errors="ignore")
    if editing:
        assert request.full_url.endswith("/images/edits")
        assert b'name="background"\r\n\r\ntransparent' in request.data
        assert b'name="output_format"\r\n\r\npng' in request.data
        assert content in request.data
    else:
        assert request.full_url.endswith("/images/generations")
        payload = json.loads(request.data)
        assert payload["background"] == "transparent" and payload["output_format"] == "png"


@pytest.mark.parametrize("api", ["gemini", "chat_completions"])
def test_unsupported_api_does_not_silently_drop_transparency(api):
    provider = OpenAICompatibleImageProvider(base_url="https://fixture.invalid", provider_key="fixture", model="fixture", credentials=SimpleNamespace(get=lambda _: "fixture"), api=api)
    with patch("app.providers.http.urllib.request.urlopen") as network:
        with pytest.raises(ProviderError, match="不支持 background=transparent") as failure:
            provider.generate(prompt="A dryer", background="transparent")
        assert failure.value.status_code == 400
        network.assert_not_called()


@pytest.mark.parametrize("transparent", [True, False])
def test_tool_persists_bytes_effective_parameters_and_alpha_result(tmp_path, transparent):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name="透明验证", slug="alpha", brief="", budget_minor=None, currency="CNY", root_path=str(tmp_path / "alpha")))
    project_id = project["id"]
    assets, canvas = AssetStore(store), CanvasStore(store)
    # A gateway may flatten the image to JPEG despite the requested PNG.
    content = image_bytes() if transparent else image_bytes("RGB", format="JPEG")
    calls = []
    def generate(**kwargs): calls.append(kwargs); return content
    registry = SimpleNamespace(image=lambda *a, **kw: SimpleNamespace(generate=generate))
    tools = DesignToolRegistry(store, asset_store=assets, canvas_store=canvas, provider_registry=registry)
    result = tools.execute(project_id=project_id, task_id=None, name="generate_image", arguments={"prompt": "A dryer on a transparent background", "model": "gpt-image-2.5-flare", "provider": "openai-image"})
    assert calls[0]["background"] == "transparent" and calls[0]["output_format"] == "png"
    assert result["asset"]["metadata"]["params"]["background"] == "transparent"
    assert result["imageOutput"]["hasTransparency"] is transparent
    assert bool(result["warnings"]) is not transparent
    assert result["asset"]["mime"] == ("image/png" if transparent else "image/jpeg")
    saved = assets.get_asset(project_id=project_id, asset_id=result["assetId"])
    assert Path(saved["absolutePath"]).read_bytes() == content
    assert result["node"]["data"]["asset"]["metadata"]["imageOutput"] == result["imageOutput"]
    if transparent:
        tools.execute(project_id=project_id, task_id=None, name="generate_image", arguments={"prompt": "改为橙色", "source_asset_id": result["assetId"]})
        assert calls[1]["background"] == "transparent"


@pytest.mark.parametrize("opaque", [False, True])
def test_sdk_transparency_schema_and_node_setting_transport(opaque):
    root = Path(__file__).resolve().parents[1]
    payload = {"api": "chat_completions", "model": "fixture", "apiKey": "fixture", "baseUrl": "http://fixture.invalid/v1", "toolGateway": {"baseUrl": "http://fixture.invalid", "projectId": "fixture"},
               "context": {"brief": "透明背景的吹风机", "constraints": {"agentCollaboration": False, "canvasParams": {"kind": "image", "background": "transparent", "output_format": "png"}}}}
    result = subprocess.run([shutil.which("node"), "--import", str(root / "tests/fixtures/transparency_transport.mjs"), str(root / "app/openai_agent_worker.mjs")], input=json.dumps(payload), text=True, capture_output=True, env={**os.environ, "FIXTURE_ALPHA_OPAQUE": "1" if opaque else "0"}, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout[-6000:]
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    final = next(e["result"] for e in events if e["type"] == "result")
    assert final["tool_outputs"][0]["output"]["imageOutput"]["hasTransparency"] is not opaque
    if opaque:
        assert "返回图片没有透明像素" in final["structured_data"]["answer"]
        assert final["warnings"] == ["返回图片没有透明像素"]
