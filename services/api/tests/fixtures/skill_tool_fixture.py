import json
import os
import sys

from app.design_tools import DesignToolRegistry
from app.skills import SkillError
from app.storage import ProjectStore

request = json.load(sys.stdin)
registry = DesignToolRegistry(ProjectStore(os.environ['FIXTURE_WORKSPACE']))
try:
    result = registry.execute(project_id=request['projectId'], task_id=request['taskId'], name=request['name'],
                              arguments=request['arguments'], operation_id=request.get('callId'), agent_role=request.get('role', 'design'))
    print(json.dumps({'status': 200, 'body': result}, ensure_ascii=False))
except (SkillError, ValueError) as error:
    print(json.dumps({'status': getattr(error, 'status_code', 422), 'body': {'detail': str(error)}}))
