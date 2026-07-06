"""Fabric coordination — routing, swarm selection, and multi-agent primitives."""

from fabric.router import IntentRouter, RoutingAssignment
from fabric.swarm import SwarmAssignment, SwarmCoordinator, SwarmStrategy

__all__ = [
    "IntentRouter",
    "RoutingAssignment",
    "SwarmAssignment",
    "SwarmCoordinator",
    "SwarmStrategy",
]