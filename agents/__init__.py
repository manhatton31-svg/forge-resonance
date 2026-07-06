"""
Concrete sovereign agent implementations and Fabric agent directory.

Place custom ResonanceAgent subclasses here. Each agent owns its goals,
memory, and offer catalog independently of the Fabric core.
"""

from agents.registry import AgentRegistry, RegisteredAgent

__all__ = ["AgentRegistry", "RegisteredAgent"]