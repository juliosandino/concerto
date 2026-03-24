"""Structured chaos verification scenarios and runner."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

import httpx
from concerto_chaos.managed_agent import ManagedAgent
from concerto_shared.enums import Product
from loguru import logger

SCENARIO_AGENT_PREFIX = "chaos-sc-"
ALL_PRODUCTS = list(Product)
JOB_DURATION_RANGE = (5.0, 10.0)


@dataclass
class ScenarioResult:
    """Result of a single chaos scenario run."""

    name: str
    description: str
    passed: bool
    detail: str
    duration_sec: float


# ------------------------------------------------------------------
# REST helpers
# ------------------------------------------------------------------


async def _create_job(
    http: httpx.AsyncClient,
    product: Product,
    duration: float | None = None,
) -> dict:
    """POST /jobs and return the created job dict."""
    payload: dict = {"product": product.value}
    if duration is not None:
        payload["duration"] = duration
    resp = await http.post("/jobs", json=payload)
    resp.raise_for_status()
    return resp.json()


async def _get_job(http: httpx.AsyncClient, job_id: str) -> dict:
    resp = await http.get(f"/jobs/{job_id}")
    resp.raise_for_status()
    return resp.json()


async def _get_agent(http: httpx.AsyncClient, agent_id: str) -> dict | None:
    resp = await http.get(f"/agents/{agent_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def _delete_agent(http: httpx.AsyncClient, agent_id: str) -> None:
    resp = await http.delete(f"/agents/{agent_id}")
    if resp.status_code not in (204, 404):
        resp.raise_for_status()


async def _poll_job(
    http: httpx.AsyncClient,
    job_id: str,
    target_statuses: set[str],
    timeout: float = 30.0,
) -> dict:
    """Poll GET /jobs/{id} every 0.5s until status is in target_statuses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        job = await _get_job(http, job_id)
        if job["status"] in target_statuses:
            return job
        await asyncio.sleep(0.5)
    job = await _get_job(http, job_id)
    raise TimeoutError(
        f"Job {job_id} status={job['status']}, expected one of {target_statuses}"
    )


async def _poll_agent_status(
    http: httpx.AsyncClient,
    agent_id: str,
    target_status: str,
    timeout: float = 15.0,
) -> dict:
    """Poll GET /agents/{id} every 0.5s until status matches."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        agent = await _get_agent(http, agent_id)
        if agent and agent["status"] == target_status:
            return agent
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Agent {agent_id} never reached status={target_status}")


def _random_duration() -> float:
    return round(random.uniform(*JOB_DURATION_RANGE), 1)


def _make_agent(
    name_suffix: str, ws_url: str, caps: list[Product] | None = None
) -> ManagedAgent:
    caps = caps or ALL_PRODUCTS
    return ManagedAgent(
        name=f"{SCENARIO_AGENT_PREFIX}{name_suffix}",
        capabilities=caps,
        ws_url=ws_url,
    )


# ------------------------------------------------------------------
# Scenarios
# ------------------------------------------------------------------


async def scenario_normal_completion(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Smoke test: 1 agent + 1 job → verify job completes."""
    t0 = time.monotonic()
    agent = _make_agent("normal-1", ws_url)
    try:
        await agent.start()
        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=5.0)
        job_id = job["id"]
        await _poll_job(http, job_id, {"completed"}, timeout=30.0)
        return ScenarioResult(
            name="normal_completion",
            description="Submit job → verify COMPLETED",
            passed=True,
            detail=f"Job {job_id[:8]} completed (product={product.value})",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="normal_completion",
            description="Submit job → verify COMPLETED",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


async def scenario_kill_agent_requeue(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Kill agent mid-job → verify job goes back to QUEUED."""
    t0 = time.monotonic()
    agent = _make_agent("kill-rq-1", ws_url)
    try:
        await agent.start()
        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=_random_duration())
        job_id = job["id"]

        # Wait for agent to receive the job (instant via WS queue)
        await agent.wait_for_job(timeout=15.0)
        # Let the RUNNING status propagate to the controller
        await asyncio.sleep(0.5)

        # Kill the agent via REST
        await _delete_agent(http, str(agent.agent_id))

        # Verify job goes back to queued
        await _poll_job(http, job_id, {"queued"}, timeout=15.0)
        return ScenarioResult(
            name="kill_agent_requeue",
            description="Kill agent mid-job → verify job re-queued",
            passed=True,
            detail=f"Job {job_id[:8]} correctly re-queued after agent killed",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="kill_agent_requeue",
            description="Kill agent mid-job → verify job re-queued",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


async def scenario_kill_agent_failover(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Kill assigned agent → backup agent picks up the job."""
    t0 = time.monotonic()
    agent_a = _make_agent("fail-a", ws_url)
    agent_b = _make_agent("fail-b", ws_url)
    try:
        await agent_a.start()
        await agent_b.start()

        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=_random_duration())
        job_id = job["id"]

        # Wait for one of the agents to receive the job
        try:
            await agent_a.wait_for_job(timeout=15.0)
            assigned_id = str(agent_a.agent_id)
        except asyncio.TimeoutError:
            await agent_b.wait_for_job(timeout=5.0)
            assigned_id = str(agent_b.agent_id)

        # Let the RUNNING status propagate to the controller
        await asyncio.sleep(0.5)

        # Kill whichever agent got the job
        await _delete_agent(http, assigned_id)

        # Verify the backup picks it up and completes it
        await _poll_job(http, job_id, {"completed"}, timeout=45.0)
        return ScenarioResult(
            name="kill_agent_failover",
            description="Kill assigned agent → backup completes job",
            passed=True,
            detail=f"Job {job_id[:8]} completed by backup agent after failover",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="kill_agent_failover",
            description="Kill assigned agent → backup completes job",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent_a.stop()
        await agent_b.stop()


async def scenario_fail_job_early(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Fail job after 2s → verify agent returns to ONLINE and job is FAILED."""
    t0 = time.monotonic()
    agent = _make_agent("fail-job-1", ws_url)
    try:
        await agent.start()
        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=_random_duration())
        job_id = job["id"]

        # Wait for agent to receive the job (instant via WS)
        await agent.wait_for_job(timeout=15.0)
        # Let the RUNNING status propagate, then force-fail after 2s
        await asyncio.sleep(2.0)

        # Force-fail the job
        await agent.fail_current_job()

        # Verify job is FAILED
        await _poll_job(http, job_id, {"failed"}, timeout=15.0)

        # Verify agent goes back to ONLINE
        await _poll_agent_status(http, str(agent.agent_id), "online", timeout=15.0)

        return ScenarioResult(
            name="fail_job_early",
            description="Fail job after 2s → agent ONLINE, job FAILED",
            passed=True,
            detail=f"Job {job_id[:8]} failed, agent back to online",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="fail_job_early",
            description="Fail job after 2s → agent ONLINE, job FAILED",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


async def scenario_agent_disconnect_requeue(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Agent disconnects (WS close) mid-job → job re-queued."""
    t0 = time.monotonic()
    agent = _make_agent("disc-rq-1", ws_url)
    try:
        await agent.start()
        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=_random_duration())
        job_id = job["id"]

        # Wait for agent to receive the job (instant via WS)
        await agent.wait_for_job(timeout=15.0)
        # Let the RUNNING status propagate
        await asyncio.sleep(0.5)

        # Abruptly close the WebSocket (simulates network loss)
        await agent.stop()

        # Verify job goes back to queued
        await _poll_job(http, job_id, {"queued"}, timeout=15.0)
        return ScenarioResult(
            name="agent_disconnect_requeue",
            description="Agent WS disconnect mid-job → job re-queued",
            passed=True,
            detail=f"Job {job_id[:8]} correctly re-queued after disconnect",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="agent_disconnect_requeue",
            description="Agent WS disconnect mid-job → job re-queued",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


async def scenario_agent_reconnect(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Agent disconnects → goes offline → reconnects with same name → ONLINE."""
    t0 = time.monotonic()
    agent_name_suffix = "reconn-1"
    agent = _make_agent(agent_name_suffix, ws_url)
    try:
        await agent.start()
        agent_id = str(agent.agent_id)

        # Verify agent is online
        await _poll_agent_status(http, agent_id, "online", timeout=10.0)

        # Disconnect
        await agent.stop()

        # Verify agent goes offline
        await _poll_agent_status(http, agent_id, "offline", timeout=15.0)

        # Reconnect with same name
        agent2 = _make_agent(agent_name_suffix, ws_url)
        await agent2.start()

        # Should reuse the same agent record — verify it's online again
        await _poll_agent_status(http, agent_id, "online", timeout=10.0)
        await agent2.stop()

        return ScenarioResult(
            name="agent_reconnect",
            description="Disconnect → offline → reconnect same name → ONLINE",
            passed=True,
            detail=f"Agent {agent_id[:8]} reconnected successfully",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="agent_reconnect",
            description="Disconnect → offline → reconnect same name → ONLINE",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


async def scenario_queue_then_dispatch(
    ws_url: str, http: httpx.AsyncClient
) -> ScenarioResult:
    """Submit job with no agents → stays QUEUED → start agent → job COMPLETED."""
    t0 = time.monotonic()
    agent = _make_agent("qtd-1", ws_url)
    try:
        # Ensure no leftover scenario agents can pick up this job
        await _cleanup_chaos_agents(http)

        product = random.choice(ALL_PRODUCTS)
        job = await _create_job(http, product, duration=5.0)
        job_id = job["id"]

        # Verify it stays queued (no agents online)
        await asyncio.sleep(2.0)
        job_state = await _get_job(http, job_id)
        if job_state["status"] != "queued":
            return ScenarioResult(
                name="queue_then_dispatch",
                description="Job queued with no agents → start agent → COMPLETED",
                passed=False,
                detail=f"Expected queued, got {job_state['status']}",
                duration_sec=time.monotonic() - t0,
            )

        # Now start an agent — job should be dispatched
        await agent.start()

        await _poll_job(http, job_id, {"completed"}, timeout=30.0)
        return ScenarioResult(
            name="queue_then_dispatch",
            description="Job queued with no agents → start agent → COMPLETED",
            passed=True,
            detail=f"Job {job_id[:8]} dispatched and completed after agent joined",
            duration_sec=time.monotonic() - t0,
        )
    except Exception as exc:
        return ScenarioResult(
            name="queue_then_dispatch",
            description="Job queued with no agents → start agent → COMPLETED",
            passed=False,
            detail=str(exc),
            duration_sec=time.monotonic() - t0,
        )
    finally:
        await agent.stop()


# ------------------------------------------------------------------
# All scenarios in execution order
# ------------------------------------------------------------------

ALL_SCENARIOS = [
    scenario_normal_completion,
    scenario_kill_agent_requeue,
    scenario_kill_agent_failover,
    scenario_fail_job_early,
    scenario_agent_disconnect_requeue,
    scenario_agent_reconnect,
    scenario_queue_then_dispatch,
]


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------


async def _cleanup_chaos_agents(http: httpx.AsyncClient) -> int:
    """Delete all agents whose name starts with the scenario prefix."""
    resp = await http.get("/agents")
    resp.raise_for_status()
    agents = resp.json()
    count = 0
    for agent in agents:
        if agent["name"].startswith(SCENARIO_AGENT_PREFIX):
            await _delete_agent(http, agent["id"])
            count += 1
    return count


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------


async def run_scenarios(
    ws_url: str,
    http_base_url: str,
    runtime: float,
) -> list[ScenarioResult]:
    """Execute scenarios within the runtime budget, then clean up."""
    results: list[ScenarioResult] = []
    deadline = time.monotonic() + runtime

    async with httpx.AsyncClient(base_url=http_base_url, timeout=10.0) as http:
        # Clean up leftover agents from any prior run
        cleaned = await _cleanup_chaos_agents(http)
        if cleaned:
            logger.info(f"Pre-run cleanup: removed {cleaned} leftover agent(s)")

        for scenario_fn in ALL_SCENARIOS:
            if time.monotonic() >= deadline:
                logger.warning(
                    "Runtime budget exhausted — skipping remaining scenarios"
                )
                break

            name = scenario_fn.__name__.removeprefix("scenario_")
            logger.info(f"▶ Running scenario: {name}")
            result = await scenario_fn(ws_url, http)
            results.append(result)

            icon = "✅" if result.passed else "❌"
            logger.info(
                f"  {icon} {name} ({result.duration_sec:.1f}s) — {result.detail}"
            )

        # Cleanup
        cleaned = await _cleanup_chaos_agents(http)
        if cleaned:
            logger.info(f"Cleaned up {cleaned} scenario agent(s)")

    return results


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------


def print_report(results: list[ScenarioResult]) -> None:
    """Print an ASCII summary table of scenario results."""
    w_name = 38
    w_result = 10
    w_time = 8
    w_detail = 44
    w_total = w_name + w_result + w_time + w_detail + 6  # separators

    print()
    print("═" * w_total)
    print(f"{'CHAOS SCENARIO REPORT':^{w_total}}")
    print("═" * w_total)
    print(
        f"  {'Scenario':<{w_name}}  {'Result':<{w_result}}"
        f"  {'Time':>{w_time}}  {'Detail':<{w_detail}}"
    )
    print("─" * w_total)

    total_time = 0.0
    passed = 0
    failed = 0

    for r in results:
        icon = "✅ PASS" if r.passed else "❌ FAIL"
        if r.passed:
            passed += 1
        else:
            failed += 1
        total_time += r.duration_sec
        detail = r.detail[:w_detail] if len(r.detail) > w_detail else r.detail
        print(
            f"  {r.name:<{w_name}}  {icon:<{w_result}}"
            f"  {r.duration_sec:>{w_time - 1}.1f}s  {detail}"
        )

    print("─" * w_total)
    summary = f"Total: {len(results)} | Passed: {passed} | Failed: {failed} | Duration: {total_time:.1f}s"
    print(f"  {summary}")
    print("═" * w_total)
    print()
