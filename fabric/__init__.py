"""Fabric coordination — routing, swarm selection, and multi-agent primitives."""

from fabric.router import IntentRouter, RoutingAssignment
from fabric.swarm import (
    AgentExecutionResult,
    AgentFailureKind,
    ConsensusStrategy,
    SwarmAssignment,
    SwarmCoordinator,
    SwarmExecutionMetrics,
    SwarmResult,
    SwarmStrategy,
)

__all__ = [
    "AgentExecutionResult",
    "AgentFailureKind",
    "ConsensusStrategy",
    "IntentRouter",
    "RoutingAssignment",
    "SwarmAssignment",
    "SwarmCoordinator",
    "SwarmExecutionMetrics",
    "SwarmResult",
    "SwarmStrategy",
]