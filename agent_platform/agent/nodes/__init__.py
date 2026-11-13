"""Stage implementations extracted without changing their execution order."""
from agent_platform.agent.nodes.profile import run as profile
from agent_platform.agent.nodes.retrieve import run as retrieve
from agent_platform.agent.nodes.plan import run as plan
from agent_platform.agent.nodes.solve import run as solve
from agent_platform.agent.nodes.repair import run as repair
from agent_platform.agent.nodes.emergency import run as emergency
from agent_platform.agent.nodes.tool import run as tool
from agent_platform.agent.nodes.verify import run as verify
from agent_platform.agent.nodes.arbitrate import run as arbitrate
from agent_platform.agent.nodes.finalize import run as finalize

NODE_HANDLERS = {
    "profile": profile,
    "retrieve": retrieve,
    "plan": plan,
    "solve": solve,
    "repair": repair,
    "emergency": emergency,
    "tool": tool,
    "verify": verify,
    "arbitrate": arbitrate,
    "finalize": finalize,
}
