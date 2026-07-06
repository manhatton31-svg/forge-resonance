"""Fabric coordination — routing, swarm selection, and multi-agent primitives."""

from fabric.router import IntentRouter, RoutingAssignment
from fabric.swarm import (
    AgentExecutionResult,
    SwarmAssignment,
    SwarmCoordinator,
    SwarmResult,
    SwarmStrategy,
)

__all__ = [
    "AgentExecutionResult",
    "IntentRouter",
    "RoutingAssignment",
    "SwarmAssignment",
    "SwarmCoordinator",
    "SwarmResult",
    "SwarmStrategy",
]