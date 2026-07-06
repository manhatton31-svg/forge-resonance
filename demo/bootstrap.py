"""
ForgeResonance demo bootstrap layer.

Provides reusable functions to spin up agents, run resonance cycles, and
exercise multi-agent ranking — used by the CLI demo and tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from config import load_config
from core.memory import FileMemoryStore
from core.resonance_agent import ResonanceAgent, ResonanceOutcome
from core.scoring import InMemoryScoreStore, ResonanceScorer
from core.state import StateManager
from generation.resonance_engine import ResonanceEngine
from harvesting.intent_harvester import EmbeddingIntentHarvester
from injection.value_injector import DeliveryMode, ValueInjector
from integration.arcly_handoff import ArclyHandoff
from agents.registry import AgentRegistry, RegisteredAgent
from fabric.swarm import SwarmCoordinator, SwarmStrategy
from reputation.score_layer import (
    AgentAnalytics,
    AgentReputation,
    InMemoryOutcomeHistoryStore,
    ReputationLayer,
    ResonanceScoreManager,
    create_score_manager,
)
from core.resonance_agent import IntentSignal

# Realistic intents that clear harvesting thresholds in local embedding mode.
SINGLE_AGENT_INTENTS: tuple[str, ...] = (
    "I want to buy analytics software and need pricing for the enterprise plan",
    "Compare HubSpot vs Salesforce for our small sales team — pros and cons",
    "I'm researching project management tools and need a solid overview",
    "I need support with my billing account and want to request a refund",
)

MULTI_AGENT_SCENARIOS: dict[str, tuple[str, ...]] = {
    "atlas-analytics": (
        "I want to buy analytics software and need pricing for the enterprise plan",
        "Compare Looker vs Tableau for a data team of ten engineers",
        "Ready to purchase and need a quote for the analytics enterprise plan",
        "What's the pricing for the enterprise analytics plan with annual billing?",
    ),
    "nova-research": (
        "I'm researching project management tools and need an overview",
        "Can you help me understand how AI analytics platforms work?",
    ),
    "echo-support": (
        "I need support with my billing account and a refund request",
    ),
}

PIPELINE_PHASES = ("Harvest", "Generate", "Inject", "Handoff", "Reflect")


@dataclass
class CycleResult:
    """Summary of one resonance cycle for demo output."""

    cycle_number: int
    intent_text: str
    outcome: str
    score: float
    formatted_message: str = ""
    structured_card: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False


@dataclass
class DemoResult:
    """Aggregate result from a demo run."""

    agent_name: str
    cycles: list[CycleResult] = field(default_factory=list)
    analytics: AgentAnalytics | None = None


PrintFn = Callable[[str], None]


def _default_print(msg: str, *, stream: TextIO | None = None) -> None:
    (stream or __import__("sys").stdout).write(msg + "\n")


def banner(title: str, *, print_fn: PrintFn = _default_print) -> None:
    line = "═" * 60
    print_fn(line)
    print_fn(f"  {title}")
    print_fn(line)


def section(title: str, *, print_fn: PrintFn = _default_print) -> None:
    print_fn(f"\n── {title} ──")


def _truncate_intent(text: str, limit: int = 72) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _summarize_message(formatted: str, max_lines: int = 2) -> str:
    """First meaningful lines of resonant value for compact display."""
    lines = [ln.strip() for ln in formatted.splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(f"    {ln}" for ln in lines[:max_lines])


def _print_cycle_compact(
    cycle: CycleResult,
    *,
    print_fn: PrintFn,
) -> None:
    """One-line cycle summary for default demo output."""
    intent = _truncate_intent(cycle.intent_text, 56)
    if cycle.skipped:
        print_fn(f"  Cycle {cycle.cycle_number}: skipped — intent below threshold")
        print_fn(f"    Intent: {intent}")
        return

    phases = " → ".join(PIPELINE_PHASES)
    print_fn(
        f"  Cycle {cycle.cycle_number}: {cycle.outcome} "
        f"(score {cycle.score:.1f})  [{phases}]"
    )
    print_fn(f"    Intent: {intent}")
    if cycle.formatted_message:
        summary = _summarize_message(cycle.formatted_message)
        if summary:
            print_fn("    Value:")
            print_fn(summary)


def create_demo_stack(
    *,
    data_dir: Path | None = None,
    shared_manager: ResonanceScoreManager | None = None,
    delivery_mode: DeliveryMode = DeliveryMode.FORMATTED_MESSAGE,
    show_cards: bool = False,
) -> tuple[ResonanceScoreManager, ReputationLayer]:
    """Create shared reputation stack for one or more demo agents."""
    load_config().ensure_directories()
    manager = shared_manager or create_score_manager(
        scorer=ResonanceScorer(InMemoryScoreStore()),
        history_store=InMemoryOutcomeHistoryStore(),
    )
    return manager, ReputationLayer(manager)


def create_demo_agent(
    name: str,
    goals: list[str],
    *,
    data_dir: Path,
    score_manager: ResonanceScoreManager,
    delivery_mode: DeliveryMode = DeliveryMode.FORMATTED_MESSAGE,
    show_cards: bool = False,
) -> ResonanceAgent:
    """Wire a fully functional demo agent with quiet Arcly handoff."""
    agent_dir = data_dir / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    state_dir = data_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    mode = (
        DeliveryMode.STRUCTURED_CARD
        if show_cards
        else delivery_mode
    )

    return ResonanceAgent(
        name=name,
        goals=goals,
        memory_store=FileMemoryStore(base_dir=agent_dir),
        score_manager=score_manager,
        state_manager=StateManager(base_dir=state_dir),
        intent_harvester=EmbeddingIntentHarvester(),
        resonance_engine=ResonanceEngine(api_key=""),
        value_injector=ValueInjector(
            delivery_mode=mode,
            echo=False,
            prepare_handoff=True,
        ),
        arcly_handoff=ArclyHandoff(force_dry_run=True, quiet=True),
    )


def run_agent_cycles(
    agent: ResonanceAgent,
    intents: list[str],
    *,
    print_fn: PrintFn = _default_print,
    verbose: bool = True,
) -> DemoResult:
    """Feed intents and run one cycle per intent; return structured summary."""
    result = DemoResult(agent_name=agent.name)
    agent.start()

    for i, text in enumerate(intents, start=1):
        if verbose:
            section(f"Cycle {i}: {agent.name}", print_fn=print_fn)
            print_fn(f"  Intent: {_truncate_intent(text)}")

        agent.submit_intent(text)
        outcome = agent.run_once()
        skipped = outcome == ResonanceOutcome.SKIPPED

        formatted = ""
        card: dict[str, Any] = {}
        injector = agent.value_injector
        if hasattr(injector, "last_result") and injector.last_result:
            formatted = injector.last_result.formatted_message
            card = dict(injector.last_result.structured_card)

        cycle = CycleResult(
            cycle_number=i,
            intent_text=text,
            outcome=outcome.value,
            score=agent.resonance_score,
            formatted_message=formatted,
            structured_card=card,
            skipped=skipped,
        )
        result.cycles.append(cycle)

        if verbose:
            if skipped:
                print_fn("  Outcome: skipped (intent below threshold)")
            else:
                print_fn(
                    f"  Outcome: {outcome.value}  |  Score: {agent.resonance_score:.2f}"
                )
                for phase in PIPELINE_PHASES:
                    print_fn(f"    [{phase}] complete")
                if formatted:
                    print_fn("\n  Resonant value:")
                    for line in formatted.splitlines():
                        print_fn(f"    {line}")
                if card and card.get("type") == "resonance_card":
                    print_fn(
                        f"\n  Card CTA: {card.get('cta', {}).get('label', 'n/a')}"
                    )

    result.analytics = agent.get_reputation_stats()
    if verbose:
        print_reputation_stats(agent.name, result.analytics, print_fn=print_fn)

    return result


def run_agent_cycles_compact(
    agent: ResonanceAgent,
    intents: list[str],
    *,
    print_fn: PrintFn = _default_print,
) -> DemoResult:
    """Run cycles with compact one-line summaries (default demo mode)."""
    result = DemoResult(agent_name=agent.name)
    agent.start()

    for i, text in enumerate(intents, start=1):
        agent.submit_intent(text)
        outcome = agent.run_once()
        skipped = outcome == ResonanceOutcome.SKIPPED

        formatted = ""
        card: dict[str, Any] = {}
        injector = agent.value_injector
        if hasattr(injector, "last_result") and injector.last_result:
            formatted = injector.last_result.formatted_message
            card = dict(injector.last_result.structured_card)

        cycle = CycleResult(
            cycle_number=i,
            intent_text=text,
            outcome=outcome.value,
            score=agent.resonance_score,
            formatted_message=formatted,
            structured_card=card,
            skipped=skipped,
        )
        result.cycles.append(cycle)
        _print_cycle_compact(cycle, print_fn=print_fn)

    result.analytics = agent.get_reputation_stats()
    print_reputation_stats(agent.name, result.analytics, print_fn=print_fn)
    return result


def print_reputation_stats(
    agent_name: str,
    analytics: AgentAnalytics,
    *,
    print_fn: PrintFn = _default_print,
) -> None:
    """Pretty-print reputation analytics."""
    section(f"Reputation — {agent_name}", print_fn=print_fn)
    print_fn(f"  Resonance Score:       {analytics.resonance_score:.2f}")
    print_fn(f"  Visibility multiplier: {analytics.visibility_multiplier:.2f}")
    print_fn(f"  Total resonances:      {analytics.total_resonances}")
    print_fn(f"  Success rate:          {analytics.success_rate:.0%}")
    print_fn(f"  Average quality:       {analytics.average_quality:.2f}")
    print_fn(f"  Trend:                 {analytics.trend.direction.value}")


def print_ranking(
    ranked: list[AgentReputation],
    *,
    print_fn: PrintFn = _default_print,
) -> None:
    """Display multi-agent ranking table."""
    section("Fabric Agent Ranking (by selection weight)", print_fn=print_fn)
    print_fn(
        f"  {'Rank':<5} {'Agent':<18} {'Score':>6} {'Visibility':>10} "
        f"{'Weight':>7} {'Success':>8} {'Trend':<12}"
    )
    print_fn("  " + "-" * 72)
    for rep in ranked:
        label = rep.agent_name or rep.agent_id[:12]
        print_fn(
            f"  {rep.rank:<5} {label:<18} {rep.resonance_score:>6.1f} "
            f"{rep.visibility_multiplier:>10.2f} {rep.selection_weight:>7.3f} "
            f"{rep.success_rate:>7.0%} {rep.trend_direction:<12}"
        )
    print_fn(
        "\n  Selection weight = visibility × (score / 100). "
        "Higher weight → preferred for intent routing in agent swarms."
    )


def run_single_agent_demo(
    *,
    data_dir: Path | None = None,
    intents: list[str] | None = None,
    print_fn: PrintFn = _default_print,
    verbose: bool = False,
    show_banners: bool = True,
) -> DemoResult:
    """Run the single-agent showcase demo."""
    base = data_dir or Path("data/demo")
    manager, _ = create_demo_stack(data_dir=base)

    if show_banners:
        banner("ForgeResonance — Single Agent Demo", print_fn=print_fn)
        print_fn("  Pipeline: Harvest → Generate → Inject → Handoff → Reflect")
        print_fn("  Mode: template generation (no API keys)\n")

    agent = create_demo_agent(
        "atlas-demo",
        goals=[
            "help teams evaluate analytics platforms",
            "deliver contextual value at purchase intent",
        ],
        data_dir=base,
        score_manager=manager,
    )

    intent_list = list(intents or SINGLE_AGENT_INTENTS)
    if verbose:
        return run_agent_cycles(
            agent,
            intent_list,
            print_fn=print_fn,
            verbose=True,
        )
    return run_agent_cycles_compact(agent, intent_list, print_fn=print_fn)


def run_multi_agent_ranking_demo(
    *,
    data_dir: Path | None = None,
    print_fn: PrintFn = _default_print,
    verbose: bool = False,
    show_banners: bool = True,
) -> list[AgentReputation]:
    """
    Run 2–3 agents on similar intents and rank by reputation.

    Demonstrates how the Fabric will route intent across agent swarms:
    agents that accumulate stronger resonance earn higher selection weight.
    """
    base = data_dir or Path("data/demo")
    manager, reputation = create_demo_stack(data_dir=base)

    if show_banners:
        banner("ForgeResonance — Multi-Agent Ranking Demo", print_fn=print_fn)
        print_fn(
            "  Three sovereign agents compete on overlapping intents.\n"
            "  Reputation determines who the Fabric surfaces first.\n"
        )

    specs: list[tuple[str, list[str], tuple[str, ...]]] = [
        (
            "atlas-analytics",
            ["maximize analytics conversion", "compare BI tools fairly"],
            MULTI_AGENT_SCENARIOS["atlas-analytics"],
        ),
        (
            "nova-research",
            ["educate buyers during research phase"],
            MULTI_AGENT_SCENARIOS["nova-research"],
        ),
        (
            "echo-support",
            ["resolve billing issues quickly"],
            MULTI_AGENT_SCENARIOS["echo-support"],
        ),
    ]

    agents: list[ResonanceAgent] = []
    for name, goals, _ in specs:
        agents.append(
            create_demo_agent(name, list(goals), data_dir=base, score_manager=manager)
        )

    for agent, (_, _, intent_list) in zip(agents, specs):
        section(f"Agent: {agent.name}", print_fn=print_fn)
        if verbose:
            run_agent_cycles(
                agent,
                list(intent_list),
                print_fn=print_fn,
                verbose=True,
            )
        else:
            run_agent_cycles_compact(agent, list(intent_list), print_fn=print_fn)

    agent_ids = [a.agent_id for a in agents]
    names = {a.agent_id: a.name for a in agents}
    ranked = reputation.rank_agents(agent_ids, agent_names=names)

    print_ranking(ranked, print_fn=print_fn)
    if show_banners:
        section("Swarm scaling note", print_fn=print_fn)
        print_fn(
            "  Today: rank_agents() orders agents by selection weight.\n"
            "  Next:  Fabric router samples proportionally across edge agents\n"
            "         (Cloudflare KV reputation cache + Neon source of truth)."
        )

    return ranked


SWARM_ROUTING_INTENTS: tuple[tuple[str, str], ...] = (
    (
        "purchase_intent",
        "I want to buy analytics software and need pricing for the enterprise plan",
    ),
    (
        "research_intent",
        "I'm researching project management tools and need a solid overview",
    ),
    (
        "support_intent",
        "I need support with my billing account and want to request a refund",
    ),
)

SWARM_AGENT_SPECS: tuple[tuple[str, list[str], list[str]], ...] = (
    (
        "atlas-analytics",
        ["maximize analytics conversion", "compare BI tools fairly"],
        ["commercial", "analytics", "purchase"],
    ),
    (
        "nova-research",
        ["educate buyers during research phase"],
        ["research", "education"],
    ),
    (
        "echo-support",
        ["resolve billing issues quickly"],
        ["support", "billing"],
    ),
)


def run_swarm_routing_demo(
    *,
    data_dir: Path | None = None,
    print_fn: PrintFn = _default_print,
    show_banners: bool = True,
) -> list[dict[str, Any]]:
    """
    Demonstrate intent routing across a small agent swarm.

    Uses ``IntentRouter`` + ``SwarmCoordinator`` with reputation ranking
    (edge-aware when ``EDGE_REPUTATION_ENABLED``).
    """
    base = data_dir or Path("data/demo")
    manager, reputation = create_demo_stack(data_dir=base)

    if show_banners:
        banner("ForgeResonance — Swarm Routing Demo", print_fn=print_fn)
        print_fn(
            "  Routes intents to the best-suited agents by reputation + capability.\n"
        )

    registry = AgentRegistry()
    agents: list[ResonanceAgent] = []
    for name, goals, specialties in SWARM_AGENT_SPECS:
        agent = create_demo_agent(name, goals, data_dir=base, score_manager=manager)
        agents.append(agent)
        registry.register(
            RegisteredAgent(
                agent_id=agent.agent_id,
                name=agent.name,
                goals=goals,
                specialties=specialties,
            )
        )

    swarm = SwarmCoordinator(registry, reputation)
    for agent in agents:
        swarm.bind_agent(agent)

    for agent in agents:
        run_agent_cycles_compact(
            agent,
            list(MULTI_AGENT_SCENARIOS.get(agent.name, SINGLE_AGENT_INTENTS[:2])),
            print_fn=lambda _: None,
        )

    results: list[dict[str, Any]] = []
    for intent_label, text in SWARM_ROUTING_INTENTS:
        section(f"Route: {intent_label}", print_fn=print_fn)
        signal = IntentSignal.from_context(
            {"matched_intent": intent_label, "text": text},
            confidence=0.85,
        )
        assignment = swarm.dispatch(
            signal,
            strategy=SwarmStrategy.BEST_SINGLE,
            submit_intent=False,
        )
        if assignment.assignments:
            best = assignment.assignments[0]
            print_fn(
                f"  → {best.agent_name}  "
                f"(weight={best.selection_weight:.3f}, "
                f"capability={best.capability_score:.2f}, "
                f"source={best.score_source})"
            )
            results.append({
                "intent": intent_label,
                "agent": best.agent_name,
                "weight": best.selection_weight,
                "capability": best.capability_score,
                "source": best.score_source,
            })
        else:
            print_fn("  → no agent available")

    section("Broadcast top 3 (purchase)", print_fn=print_fn)
    purchase = IntentSignal.from_context(
        {"matched_intent": "purchase_intent", "text": SWARM_ROUTING_INTENTS[0][1]},
        confidence=0.9,
    )
    broadcast = swarm.dispatch(
        purchase,
        strategy=SwarmStrategy.BROADCAST_TOP_N,
        top_n=3,
        submit_intent=False,
    )
    names = [a.agent_name for a in broadcast.assignments]
    print_fn(f"  Agents: {', '.join(names)}")

    return results


def run_full_demo(
    *,
    data_dir: Path | None = None,
    print_fn: PrintFn = _default_print,
    skip_multi: bool = False,
    verbose: bool = False,
    show_banners: bool = True,
) -> dict[str, Any]:
    """Run single-agent demo then multi-agent ranking."""
    single = run_single_agent_demo(
        data_dir=data_dir,
        print_fn=print_fn,
        verbose=verbose,
        show_banners=show_banners,
    )
    ranked: list[AgentReputation] = []
    if not skip_multi:
        print_fn("")
        ranked = run_multi_agent_ranking_demo(
            data_dir=data_dir,
            print_fn=print_fn,
            verbose=verbose,
            show_banners=show_banners,
        )

    return {
        "single_agent": single,
        "ranked_agents": ranked,
    }


def format_cycle_json(cycle: CycleResult) -> str:
    """Serialize a cycle for programmatic consumers."""
    return json.dumps({
        "cycle": cycle.cycle_number,
        "intent": cycle.intent_text,
        "outcome": cycle.outcome,
        "score": cycle.score,
        "skipped": cycle.skipped,
        "formatted_message": cycle.formatted_message,
        "structured_card": cycle.structured_card,
    }, indent=2)