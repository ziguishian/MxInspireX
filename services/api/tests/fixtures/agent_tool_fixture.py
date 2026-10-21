import json
import os
import sys
from app.assets import AssetStore
from app.design_tools import DesignToolRegistry
from app.storage import ProjectStore
from app.providers.registry import ProviderRegistry
from app.model_catalog import ModelCatalog

store = ProjectStore(os.environ["FIXTURE_WORKSPACE"])
providers = ProviderRegistry()
providers.catalog = ModelCatalog(store)
tools = DesignToolRegistry(store, asset_store=AssetStore(store), provider_registry=providers)
result = tools.execute(project_id=os.environ["FIXTURE_PROJECT"], task_id=os.environ.get("FIXTURE_TASK", "sdk-fixture"), name=sys.argv[1], arguments=json.load(sys.stdin))
print(json.dumps(result, ensure_ascii=False))
