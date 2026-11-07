"""API tests with a scripted fake LLM (no model needed; the browser runs against the local fixture site)."""
from __future__ import annotations

import time

from tests.conftest import make_local_agent, read_sse, wait_run

DONE = lambda r="ok": {"calls": [("done", {"evidence": "e", "result": r, "success": True})]}  # noqa: E731


# ---------------------------------------------------------------- settings / agents
def test_settings_roundtrip_and_validation(client):
    s = client.get("/api/settings").json()
    assert {"values", "defaults", "schema"} <= set(s)
    assert any(x["key"] == "agent_thinking" and x["type"] == "select" for x in s["schema"])
    r = client.put("/api/settings", json={"values": {"temperature": 0.9, "agent_thinking": "off"}})
    assert r.status_code == 200 and r.json()["values"]["temperature"] == 0.9
    assert client.put("/api/settings", json={"values": {"agent_thinking": "sometimes"}}).status_code == 422
    assert client.put("/api/settings", json={"values": {"nope": 1}}).status_code == 422
    assert client.put("/api/settings", json={"values": {"temperature": 9}}).status_code == 422
    assert client.get("/api/settings").json()["values"]["agent_thinking"] == "off"


def test_agents_crud_and_default_protection(client):
    agents = client.get("/api/agents").json()
    default = next(a for a in agents if a["is_default"])
    assert client.delete(f"/api/agents/{default['id']}").status_code == 409
    a = make_local_agent(client, name="Watcher", allowed_domains=["Example.com"], thinking="off", tools=["open_url"])
    assert a["allowed_domains"] == ["example.com"] and "done" in a["tools"]          # done always allowed
    assert client.post("/api/agents", json={"name": "watcher"}).status_code == 409   # case-insensitive unique
    assert client.post("/api/agents", json={"name": "x", "tools": ["rm_rf"]}).status_code == 422
    assert client.put(f"/api/agents/{a['id']}", json={"effort": "xhigh"}).json()["effort"] == "xhigh"
    assert client.delete(f"/api/agents/{a['id']}").status_code == 204
    assert {t["name"] for t in client.get("/api/tools").json()} >= {"click", "done", "use_skill", "remember"}


# ---------------------------------------------------------------- runs
def test_run_end_to_end_events_tokens_and_screenshots(client, fake, site):
    agent = make_local_agent(client)
    fake.push({"content": "Reading the page.", "reasoning": "hmm", "calls": [("read_text", {})], "prompt": 1200,
               "cached": 0, "out": 30},
              {"content": "Done.", "calls": [("done", {"evidence": "saw it", "result": "Fixture Home", "success": True})],
               "prompt": 1500, "cached": 1200, "out": 25})
    r = client.post(f"/api/agents/{agent['id']}/run", json={"task": "Say the heading", "start_url": site.base + "/"})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    run = wait_run(client, run_id)
    assert run["status"] == "done" and run["success"] is True and run["result"] == "Fixture Home"
    assert run["steps"] == 2 and run["prompt_tokens"] == 2700 and run["cached_tokens"] == 1200
    assert run["processed_tokens"] == 1500 and run["completion_tokens"] == 55 and run["wall_seconds"] > 0

    detail = client.get(f"/api/runs/{run_id}").json()
    kinds = [(s["kind"], s["name"]) for s in detail["steps"]]
    assert ("tool", "read_text") in kinds and ("tool", "done") in kinds
    llm_step = next(s for s in detail["steps"] if s["kind"] == "llm")
    assert llm_step["prompt_tokens"] == 1200 and llm_step["decode_tps"] == 10.0 and llm_step["prefill_ms"] == 500

    events = read_sse(client, "GET", f"/api/runs/{run_id}/events")          # replay of a finished run
    types = [e["type"] for e in events]
    for needed in ("run_status", "step_start", "llm_end", "tool_start", "tool_end", "screenshot", "run_finished"):
        assert needed in types, f"missing {needed} in {types}"
    assert "token" not in types                                              # live-only
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert events[-1]["type"] == "run_finished" and events[-1]["success"] is True

    shot = client.get(f"/api/runs/{run_id}/shots/1.jpg")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg" and len(shot.content) > 500
    assert client.get(f"/api/runs/{run_id}/shots/999.jpg").status_code == 404
    assert client.get(f"/api/runs/{run_id}/trace.zip").status_code == 200

    listing = client.get("/api/runs?status=done").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == run_id
    stats = client.get("/api/stats/summary?days=1").json()
    assert stats["runs"]["done"] == 1 and stats["tokens"]["input"] == 2700 and stats["tokens"]["output"] == 55
    assert stats["timing"]["avg_decode_tps"] == 10.0 and stats["by_agent"][0]["runs"] == 1
    assert stats["by_day"] and stats["slowest_runs"]


def test_live_stream_and_stop(client, fake, site):
    agent = make_local_agent(client)
    fake.push({"content": "thinking slowly", "calls": [("read_text", {})], "delay": 30})
    run_id = client.post(f"/api/agents/{agent['id']}/run", json={"task": "slow", "start_url": site.base + "/"}).json()["run_id"]
    deadline = time.time() + 20
    while client.get(f"/api/runs/{run_id}").json()["run"]["status"] != "running" and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)
    stopped = client.post(f"/api/runs/{run_id}/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 409
    events = read_sse(client, "GET", f"/api/runs/{run_id}/events")
    assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "stopped"


def test_thinking_modes_and_slots(client, fake, site):
    off = make_local_agent(client, name="off-agent", thinking="off")
    fake.push({"calls": [("click", {"ref": "e999"})]}, {"calls": [("click", {"ref": "e999"})]},
              {"calls": [("click", {"ref": "e999"})]}, {"calls": [("click", {"ref": "e999"})]}, DONE())
    rid = client.post(f"/api/agents/{off['id']}/run", json={"task": "x", "start_url": site.base + "/"}).json()["run_id"]
    wait_run(client, rid)
    assert not any(c["think"] for c in fake.calls), "thinking=off must never think, even after repeated errors"

    fake.calls.clear()
    on = make_local_agent(client, name="on-agent", thinking="on", effort="medium")
    fake.push({"calls": [("read_text", {})]}, DONE())
    rid = client.post(f"/api/agents/{on['id']}/run", json={"task": "x", "start_url": site.base + "/"}).json()["run_id"]
    wait_run(client, rid)
    assert all(c["think"] and c["effort"] == "medium" and c["slot"] == 0 for c in fake.calls)

    fake.calls.clear()
    auto = make_local_agent(client, name="auto-agent", thinking="auto")
    bad = {"calls": [("click", {"ref": "e999"})]}
    fake.push(bad, bad, bad, DONE())            # 3 consecutive errors -> next call escalates on the spare slot
    rid = client.post(f"/api/agents/{auto['id']}/run",
                      json={"task": "x", "start_url": site.base + "/", "overrides": {"effort": "low"}}).json()["run_id"]
    wait_run(client, rid)
    assert [c["think"] for c in fake.calls] == [False, False, False, True]
    assert fake.calls[3]["slot"] == 1 and fake.calls[0]["slot"] == 0


def test_memory_injection_search_and_agent_tools(client, fake, site):
    m1 = client.post("/api/memories", json={"content": "The staff directory lists salaries in USD.", "tags": ["staff"]}).json()
    client.post("/api/memories", json={"content": "Always answer in French.", "pinned": True})
    client.post("/api/memories", json={"content": "Unrelated gardening tip about tomatoes"})
    assert [m["id"] for m in client.get("/api/memories?q=salaries").json()] == [m1["id"]]
    assert len(client.get("/api/memories?pinned=true").json()) == 1
    agent = make_local_agent(client, memory_scope="global")
    fake.push({"calls": [("remember", {"text": "Staff page is at /staff", "tags": ["site"]})]}, DONE())
    rid = client.post(f"/api/agents/{agent['id']}/run",
                      json={"task": "Check staff salaries", "start_url": site.base + "/staff"}).json()["run_id"]
    wait_run(client, rid)
    first_user = fake.calls[0]["messages"][1]["content"]
    assert "Always answer in French" in first_user and "salaries in USD" in first_user and "tomatoes" not in first_user
    pend = client.get("/api/actions?status=pending").json()
    assert len(pend) == 1 and pend[0]["kind"] == "save_memory" and pend[0]["created_by"] == "agent"
    ok = client.post(f"/api/actions/{pend[0]['id']}/approve").json()
    assert ok["status"] == "approved"
    assert any("Staff page is at /staff" in m["content"] for m in client.get("/api/memories?scope=global").json())
    none = make_local_agent(client, name="amnesiac", memory_scope="none")
    fake.calls.clear()
    fake.push(DONE())
    rid = client.post(f"/api/agents/{none['id']}/run", json={"task": "x", "start_url": site.base + "/"}).json()["run_id"]
    wait_run(client, rid)
    assert "remember" not in fake.calls[0]["tools"] and "Always answer in French" not in fake.calls[0]["messages"][1]["content"]


def test_skills_crud_and_use_skill(client, fake, site):
    sk = client.post("/api/skills", json={"name": "read-staff", "description": "How to read the staff table",
                                          "when_to_use": "staff questions", "body": "# Steps\n1. Open /staff\n2. read_text"})
    assert sk.status_code == 201
    assert client.post("/api/skills", json={"name": "Bad Name!", "description": "x", "body": "y"}).status_code == 422
    assert client.post("/api/skills", json={"name": "read-staff", "description": "x", "body": "y"}).status_code == 409
    assert client.put("/api/skills/read-staff", json={"enabled": True, "body": "# Steps\n1. changed"}).json()["body"].endswith("changed")
    agent = make_local_agent(client, skills=["read-staff"], instructions="Be brief.")
    fake.push({"calls": [("use_skill", {"name": "read-staff"})]}, DONE())
    rid = client.post(f"/api/agents/{agent['id']}/run", json={"task": "x", "start_url": site.base + "/"}).json()["run_id"]
    run = wait_run(client, rid)
    system = fake.calls[0]["messages"][0]["content"]
    assert "read-staff: How to read the staff table" in system and "Be brief." in system
    tool_msg = next(m for m in fake.calls[1]["messages"] if m["role"] == "tool")
    assert "1. changed" in tool_msg["content"]
    assert client.delete("/api/skills/read-staff").status_code == 204
    assert client.get("/api/skills/read-staff").status_code == 404


# ---------------------------------------------------------------- schedules
def test_schedule_lifecycle_preview_and_run_now(client, fake, site):
    agent = make_local_agent(client)
    prev = client.post("/api/schedules/preview", json={"trigger": {"type": "cron", "expr": "0 8 * * 1-5"},
                                                       "timezone": "America/New_York", "count": 3}).json()
    assert len(prev["next"]) == 3 and "08:00" in prev["description"] and prev["next"][0].endswith(("-05:00", "-04:00"))
    bad = client.post("/api/schedules/preview", json={"trigger": {"type": "cron", "expr": "bad"}})
    assert bad.status_code == 200 and bad.json()["error"] and bad.json()["next"] == []
    assert "at least" in client.post("/api/schedules/preview", json={"trigger": {"type": "interval", "seconds": 5}}).json()["error"]
    body = {"name": "Home check", "agent_id": agent["id"], "task": "Read the home page", "start_url": site.base + "/",
            "trigger": {"type": "interval", "seconds": 3600}, "timezone": "UTC"}
    s = client.post("/api/schedules", json=body)
    assert s.status_code == 201
    s = s.json()
    assert s["enabled"] and s["next_run_at"] and s["created_by"] == "user" and s["agent_name"] == "Local test agent"
    assert client.get("/api/status").json()["scheduler"]["jobs"] == 1
    off = client.post(f"/api/schedules/{s['id']}/toggle", json={"enabled": False}).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    assert client.get("/api/status").json()["scheduler"]["jobs"] == 0
    fake.push(DONE("ran"))
    run_id = client.post(f"/api/schedules/{s['id']}/run").json()["run_id"]
    run = wait_run(client, run_id)
    assert run["schedule_id"] == s["id"] and run["status"] == "done" and run["trigger"] == "manual"
    after = client.get(f"/api/schedules/{s['id']}").json()
    assert after["run_count"] == 1 and after["last_status"] == "done" and after["last_run_id"] == run_id
    upd = client.put(f"/api/schedules/{s['id']}", json={"trigger": {"type": "cron", "expr": "*/15 * * * *"}, "enabled": True}).json()
    assert upd["trigger"]["expr"] == "*/15 * * * *" and upd["next_run_at"]
    assert client.delete(f"/api/agents/{agent['id']}").status_code == 409        # in use by a schedule
    assert client.delete(f"/api/schedules/{s['id']}").status_code == 204
    assert client.get("/api/schedules").json() == []


def test_scheduler_actually_fires(client, fake, site):
    agent = make_local_agent(client)
    fake.push(DONE("scheduled"))
    now = time.time()
    from datetime import datetime, timedelta
    at = (datetime.now() + timedelta(seconds=2)).replace(microsecond=0).isoformat()
    tz = client.get("/api/settings").json()["values"]["timezone"]
    s = client.post("/api/schedules", json={"name": "soon", "agent_id": agent["id"], "task": "t", "start_url": site.base + "/",
                                            "trigger": {"type": "once", "at": at}, "timezone": tz}).json()
    deadline = time.time() + 30
    run_id = None
    while time.time() < deadline:
        cur = client.get(f"/api/schedules/{s['id']}").json()
        if cur["last_run_id"]:
            run_id = cur["last_run_id"]
            break
        time.sleep(0.3)
    assert run_id, "scheduled run never fired"
    run = wait_run(client, run_id)
    assert run["trigger"] == "schedule" and run["status"] == "done"
    final = client.get(f"/api/schedules/{s['id']}").json()
    assert final["enabled"] is False and final["next_run_at"] is None            # one-off disables itself


# ---------------------------------------------------------------- chat + approvals
def test_chat_proposes_schedule_then_approval_creates_it(client, fake):
    conv = client.post("/api/conversations", json={}).json()
    fake.push(
        {"content": "I'll set that up.", "calls": [("propose_schedule", {
            "name": "Morning HN digest", "task": "Open Hacker News and list the top 5 stories", "schedule_type": "cron",
            "cron": "0 8 * * 1-5", "timezone": "America/New_York"})], "prompt": 900, "cached": 0, "out": 60},
        {"content": "Proposed: weekdays 08:00. Please approve the card.", "prompt": 1100, "cached": 900, "out": 15})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages",
                      {"content": "Every weekday at 8am give me the top 5 HN stories", "thinking": False})
    types = [e["type"] for e in events]
    assert types.count("message_start") == 2 and "tool_call" in types and "tool_result" in types
    assert "action_proposed" in types and types[-1] == "done"
    assert any(e["type"] == "token" and e["channel"] == "content" for e in events)
    action = next(e for e in events if e["type"] == "action_proposed")["action"]
    assert action["kind"] == "create_schedule" and action["status"] == "pending" and "Morning HN digest" in action["summary"]
    ends = [e for e in events if e["type"] == "llm_end"]
    assert ends[0]["prompt_tokens"] == 900 and ends[1]["cached_tokens"] == 900
    assert client.get("/api/schedules").json() == []                              # nothing created yet
    assert client.get("/api/status").json()["pending_actions"] == 1

    msgs = client.get(f"/api/conversations/{conv['id']}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[2]["action_id"] == action["id"] and msgs[1]["stats"]["completion_tokens"] == 60
    assert client.get("/api/conversations").json()[0]["title"].startswith("Every weekday")

    decided = client.post(f"/api/actions/{action['id']}/approve", json={}).json()
    assert decided["status"] == "approved" and decided["result"]["schedule_id"]
    sched = client.get("/api/schedules").json()
    assert len(sched) == 1 and sched[0]["created_by"] == "assistant" and sched[0]["timezone"] == "America/New_York"
    assert sched[0]["next_run_at"] and sched[0]["trigger"] == {"type": "cron", "expr": "0 8 * * 1-5"}
    assert client.post(f"/api/actions/{action['id']}/approve", json={}).status_code == 409


def test_chat_bad_proposal_goes_back_to_model_and_reject_flow(client, fake):
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("propose_schedule", {"name": "x", "task": "t", "schedule_type": "cron", "cron": "every day"})]},
              {"calls": [("propose_memory", {"content": "User prefers HN", "tags": ["prefs"]})]},
              {"content": "ok"})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "go"})
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["ok"] is False and "cron" in results[0]["result"].lower()
    prop = next(e for e in events if e["type"] == "action_proposed")["action"]
    assert prop["kind"] == "save_memory"
    assert client.post(f"/api/actions/{prop['id']}/reject").json()["status"] == "rejected"
    assert client.get("/api/memories").json() == []


def test_auto_approve_setting_and_assistant_run_agent(client, fake, site):
    client.put("/api/settings", json={"values": {"auto_approve_assistant_actions": True}})
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("propose_skill", {"name": "greeter", "description": "Say hi", "body": "Say hi politely."})]},
              {"content": "created"})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "make a skill"})
    action = next(e for e in events if e["type"] == "action_proposed")["action"]
    assert action["status"] == "approved"
    assert client.get("/api/skills/greeter").json()["created_by"] == "assistant"

    agent = make_local_agent(client, name="Runner")
    fake.calls.clear()
    fake.push({"calls": [("run_agent", {"agent": "runner", "task": "say hello", "start_url": site.base + "/"})]},
              {"content": "started"}, DONE("hello"))
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "run it"})
    started = next(e for e in events if e["type"] == "run_started")
    run = wait_run(client, started["run_id"])
    assert run["trigger"] == "chat" and run["result"] == "hello" and run["agent_name"] == "Runner"


def test_global_event_stream_has_status_first(client):
    import json as _json
    with client.stream("GET", "/api/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                ev = _json.loads(line[5:])
                assert ev["type"] == "status" and ev["status"]["llm"]["healthy"] is True
                assert [s["role"] for s in ev["status"]["llm"]["slots"]] == ["agent", "extract", "chat"]
                break
