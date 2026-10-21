import json
import os
import sys
from app.storage import ProjectStore
from app.agent_sessions import AgentSessionStore

data=json.load(sys.stdin)
result=AgentSessionStore(ProjectStore(os.environ['FIXTURE_WORKSPACE'])).dispatch(data['projectId'],data['taskId'],data['payload'])
print(json.dumps(result,ensure_ascii=False))
