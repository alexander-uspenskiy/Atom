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


def test_mcp_connector_tools(client, svc, tmp_path):
    import json, sys, textwrap
    srv = tmp_path / "srv.py"
    srv.write_text(textwrap.dedent('''
        from mcp.server.mcpserver import MCPServer
        m = MCPServer("t")
        @m.tool()
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        m.run()
    '''))
    svc.mcp.config_path.write_text(json.dumps({"mcpServers": {"calc": {"command": sys.executable, "args": [str(srv)]}}}))
    r = client.post("/api/mcp/reload").json()
    assert r["servers"][0]["state"] == "connected", r
    assert "mcp_calc_add" in [t["name"] for t in client.get("/api/tools").json()]


def test_mcp_server_crud(client, tmp_path):
    import sys
    srv = tmp_path / "s.py"
    srv.write_text("from mcp.server.mcpserver import MCPServer\nm = MCPServer('t')\n@m.tool()\ndef ping() -> str:\n    'p'\n    return 'pong'\nm.run()\n")
    assert client.put("/api/mcp/servers/bad name", json={"command": "x"}).status_code in (404, 422)
    assert client.put("/api/mcp/servers/x", json={}).status_code == 422
    r = client.put("/api/mcp/servers/demo", json={"command": sys.executable, "args": [str(srv)]}).json()
    s = r["servers"][0]
    assert s["name"] == "demo" and s["state"] == "connected" and s["tool_names"] == ["mcp_demo_ping"]
    assert "mcp_demo_ping" in [t["name"] for t in client.get("/api/tools").json()]
    r = client.put("/api/mcp/servers/demo", json={"command": sys.executable, "args": [str(srv)], "disabled": True}).json()
    assert r["servers"][0]["state"] == "disabled"
    assert "mcp_demo_ping" not in [t["name"] for t in client.get("/api/tools").json()]
    assert client.delete("/api/mcp/servers/demo").json()["servers"] == []


# ---------------------------------------------------------------- variables
def test_variables_api_masks_secrets(client):
    r = client.put("/api/variables/API_BASE", json={"value": "https://x.test", "description": "base"}).json()
    assert r["value"] == "https://x.test" and not r["secret"]
    s = client.put("/api/variables/TOKEN", json={"value": "s3cr3t-value", "secret": True, "domains": ["Example.com"]}).json()
    assert s["value"] is None and s["has_value"] and s["domains"] == ["example.com"]
    assert "s3cr3t-value" not in client.get("/api/variables").text
    # editing metadata without a value keeps the stored secret
    client.put("/api/variables/TOKEN", json={"secret": True, "description": "d"})
    assert client.put("/api/variables/NEW", json={"secret": True}).status_code == 422
    assert client.put("/api/variables/bad name", json={"value": "x"}).status_code in (404, 422)
    assert client.delete("/api/variables/TOKEN").status_code == 204
    assert client.delete("/api/variables/TOKEN").status_code == 404


def test_variable_substitution_and_redaction():
    from atom.variables import VariableSet
    vs = VariableSet({"USER": {"value": "bob", "secret": False, "description": "", "domains": []},
                      "PW": {"value": "hunter2!", "secret": True, "description": "", "domains": ["example.com"]}})
    a, e = vs.apply("type", {"ref": "e1", "text": "{{PW}}"}, "https://app.example.com/login")
    assert a["text"] == "hunter2!" and e is None
    _, e = vs.apply("type", {"text": "{{PW}}"}, "https://evil.test/")
    assert e and "example.com" in e
    _, e = vs.apply("find", {"query": "{{PW}}"}, "https://example.com")
    assert e and "secret" in e
    assert vs.apply("find", {"query": "{{USER}}"}, None)[0]["query"] == "bob"
    assert vs.apply("note", {"text": "{{PW}}"}, None)[0]["text"] == "{{PW}}"
    assert vs.redact("typed hunter2! ok") == "typed {{PW}} ok"
    assert "hunter2!" not in vs.prompt_section() and "bob" in vs.prompt_section()


# ---------------------------------------------------------------- connectors (gmail)
RAW = (b"From: Bob <bob@example.com>\r\nTo: me@gmail.com\r\nSubject: Hello there\r\nDate: Mon, 1 Jan 2026 10:00:00 +0000\r\n"
       b"Message-ID: <abc@x>\r\nContent-Type: text/plain\r\n\r\nSee you at noon.\r\n")


class FakeIMAP:
    sent_search: list = []

    def __init__(self, *a, **k): pass
    def login(self, u, p): assert p == "abcdefghijklmnop"          # spaces stripped
    def select(self, folder, readonly=False): return "OK", [b"2"]
    def logout(self): pass

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            FakeIMAP.sent_search.append(args)
            return "OK", [b"5 7"]
        if "HEADER.FIELDS" in args[1]:
            return "OK", [(b"1 (UID 7 BODY[HEADER.FIELDS (FROM SUBJECT)] {10}", RAW), b")",
                          (b"2 (UID 5 BODY[HEADER.FIELDS (FROM SUBJECT)] {10}", RAW), b")"]
        return "OK", [(b"1 (UID 7 BODY[] {10}", RAW), b")"]


def _gmail(client, allow_send=False):
    return client.put("/api/connectors/work", json={"type": "gmail", "enabled": True, "config": {
        "email": "me@gmail.com", "app_password": "abcd efgh ijkl mnop", "allow_send": allow_send}})


def test_gmail_connector_config_masks_secret_and_registers_tools(client, svc, _memory_keyring):
    r = _gmail(client)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["state"] == "ready" and "app_password" not in item["config"] and item["has_secret"]["app_password"]
    assert "abcd" not in client.get("/api/connectors").text
    assert [t["key"] for t in r.json()["types"][0]["fields"]] == ["email", "client_id", "client_secret", "app_password", "allow_send"]
    assert "abcd" not in str(svc.db.all("SELECT * FROM connectors")[0]["config"])          # secret is not in the DB
    assert _memory_keyring.get_password("atom-connector", "work:app_password") == "abcd efgh ijkl mnop"
    names = {t["name"] for t in client.get("/api/tools").json()}
    assert {"gmail_work_search", "gmail_work_read"} <= names and "gmail_work_send" not in names
    # editing with a blank password keeps it; enabling sending adds the send tool
    r = client.put("/api/connectors/work", json={"type": "gmail", "config": {"email": "me@gmail.com", "allow_send": True}})
    assert r.json()["items"][0]["state"] == "ready"
    assert "gmail_work_send" in {t["name"] for t in client.get("/api/tools").json()}
    assert client.put("/api/connectors/x", json={"type": "nope"}).status_code == 422
    assert client.put("/api/connectors/x", json={"type": "gmail", "config": {"email": "bad", "app_password": "p"}}).status_code == 422
    assert client.delete("/api/connectors/work").json()["items"] == []
    assert _memory_keyring.get_password("atom-connector", "work:app_password") is None
    assert client.delete("/api/connectors/work").status_code == 404


def test_gmail_tools_search_read_send(client, svc, monkeypatch):
    import asyncio
    import smtplib
    import imaplib
    from atom.connectors import gmail as g
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, u, p): pass
        def send_message(self, msg, to_addrs): sent.update(msg=msg, to=to_addrs)

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    _gmail(client, allow_send=True)
    tools = svc.connectors.tools
    ctx = type("C", (), {"settings": svc.settings.effective()})()
    out = asyncio.run(tools["gmail_work_search"].handler(ctx, {"query": "from:bob is:unread"}))
    assert out.ok and "id=7" in out.text and "Hello there" in out.text and out.text.index("id=7") < out.text.index("id=5")
    assert FakeIMAP.sent_search[-1] == ("X-GM-RAW", '"from:bob is:unread"')
    out = asyncio.run(tools["gmail_work_read"].handler(ctx, {"id": "7"}))
    assert "See you at noon." in out.text and "<email>" in out.text
    from atom.browser.session import ActionError
    import pytest
    with pytest.raises(ActionError):
        asyncio.run(tools["gmail_work_read"].handler(ctx, {"id": "7 ALL"}))
    out = asyncio.run(tools["gmail_work_send"].handler(ctx, {"to": "a@b.com", "body": "hi", "reply_to_id": "7"}))
    assert sent["to"] == ["a@b.com"] and sent["msg"]["Subject"] == "Re: Hello there" and sent["msg"]["In-Reply-To"] == "<abc@x>"
    with pytest.raises(ActionError):
        asyncio.run(tools["gmail_work_send"].handler(ctx, {"to": "a@b.com\nBcc: x@y.com", "subject": "s", "body": "b"}))
    assert client.post("/api/connectors/work/test").json()["ok"] is True


def test_gmail_oauth_sign_in_flow(client, svc, monkeypatch, _memory_keyring):
    import asyncio
    import imaplib
    from urllib.parse import parse_qs, urlparse
    from atom.connectors import oauth

    r = client.put("/api/connectors/g", json={"type": "gmail", "config": {"email": "me@gmail.com", "client_id": "cid", "client_secret": "csec"}})
    it = r.json()["items"][0]
    assert it["state"] == "needs_auth" and not it["signed_in"]
    assert client.put("/api/connectors/bad", json={"type": "gmail", "config": {"email": "me@gmail.com"}}).status_code == 422
    start = client.post("/api/connectors/g/oauth/start").json()
    q = parse_qs(urlparse(start["auth_url"]).query)
    assert q["client_id"] == ["cid"] and q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert q["redirect_uri"][0].endswith("/api/oauth/callback") and q["scope"] == ["https://mail.google.com/"]
    state = q["state"][0]
    assert "failed" in client.get("/api/oauth/callback", params={"state": "bogus", "code": "c"}).text

    class Resp:
        status_code, headers = 200, {"content-type": "application/json"}
        def json(self): return {"refresh_token": "rt-1", "access_token": "at-1", "expires_in": 3600}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, data):
            assert data["code"] == "the-code" and data["code_verifier"] and data["client_secret"] == "csec"
            return Resp()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(oauth.httpx, "post", lambda url, **k: Resp())
    assert "Signed in" in client.get("/api/oauth/callback", params={"state": state, "code": "the-code"}).text
    it = client.get("/api/connectors").json()["items"][0]
    assert it["state"] == "ready" and it["signed_in"] and "gmail_g_search" in it["tool_names"]
    assert _memory_keyring.get_password("atom-connector", "g:oauth_refresh_token") == "rt-1"
    assert "rt-1" not in str(svc.db.all("SELECT * FROM connectors")[0]["config"])
    assert "rt-1" not in client.get("/api/connectors").text

    used = {}

    class OAuthIMAP(FakeIMAP):
        def authenticate(self, mech, fn): used["mech"], used["auth"] = mech, fn(b"").decode()
    monkeypatch.setattr(imaplib, "IMAP4_SSL", OAuthIMAP)
    ctx = type("C", (), {"settings": svc.settings.effective()})()
    out = asyncio.run(svc.connectors.tools["gmail_g_search"].handler(ctx, {"query": "x"}))
    assert out.ok and used["mech"] == "XOAUTH2" and used["auth"] == "user=me@gmail.com\x01auth=Bearer at-1\x01\x01"
    assert client.post("/api/connectors/g/oauth/signout").json()["items"][0]["state"] == "needs_auth"
    assert _memory_keyring.get_password("atom-connector", "g:oauth_refresh_token") is None


def test_projects_group_chats_and_set_folder(client, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    assert client.post("/api/projects", json={"name": " "}).status_code == 422
    assert client.post("/api/projects", json={"name": "X", "folder": str(tmp_path / "nope")}).status_code == 422
    p = client.post("/api/projects", json={"name": "Site", "folder": str(folder)}).json()
    assert p["folder"] == str(folder.resolve())
    c = client.post("/api/conversations", json={"project_id": p["id"]}).json()
    assert c["project_id"] == p["id"]
    assert client.post("/api/conversations", json={"project_id": "nope"}).status_code == 404
    assert client.get(f"/api/conversations/{c['id']}").json()["project_id"] == p["id"]
    assert client.get("/api/projects").json()[0]["chat_count"] == 1
    other = client.post("/api/conversations", json={}).json()
    client.put(f"/api/conversations/{other['id']}", json={"project_id": p["id"]})
    assert client.get("/api/projects").json()[0]["chat_count"] == 2
    upd = client.put(f"/api/projects/{p['id']}", json={"name": "Site 2", "folder": ""}).json()
    assert upd["name"] == "Site 2" and upd["folder"] is None
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    chats = {x["id"]: x["project_id"] for x in client.get("/api/conversations").json()}
    assert chats == {c["id"]: None, other["id"]: None}


def test_user_and_project_skills(client, tmp_path):
    folder = tmp_path / "proj"
    (folder / ".agents" / "skills" / "deploy").mkdir(parents=True)
    (folder / ".agents" / "skills" / "deploy" / "SKILL.md").write_text(
        "---\ndescription: Ship it\nlicense: MIT\n---\nrun make deploy\n")
    proj = client.post("/api/projects", json={"name": "P", "folder": str(folder)}).json()
    client.post("/api/skills", json={"name": "greet", "description": "say hi", "body": "hi"})
    # project skills only show up with the project; user ones are always there
    assert [s["name"] for s in client.get("/api/skills").json()] == ["greet"]
    got = {s["name"]: s for s in client.get(f"/api/skills?project_id={proj['id']}").json()}
    assert got["deploy"]["scope"] == "project" and got["greet"]["scope"] == "user"
    # create at project level -> <folder>/.atom/skills
    r = client.post(f"/api/skills?project_id={proj['id']}", json={"name": "lint", "description": "d", "body": "b", "scope": "project"})
    assert r.status_code == 201 and (folder / ".atom" / "skills" / "lint" / "SKILL.md").is_file()
    assert client.post("/api/skills", json={"name": "x", "description": "d", "body": "b", "scope": "project"}).status_code == 422
    # editing an external skill keeps its extra frontmatter
    client.put(f"/api/skills/deploy?project_id={proj['id']}", json={"body": "run make ship"})
    assert "license: MIT" in (folder / ".agents" / "skills" / "deploy" / "SKILL.md").read_text()
    # a project skill shadows a user skill of the same name
    client.post(f"/api/skills?project_id={proj['id']}", json={"name": "greet", "description": "p", "body": "project hi", "scope": "project"})
    assert client.get(f"/api/skills/greet?project_id={proj['id']}").json()["body"] == "project hi"
    assert client.get("/api/skills/greet").json()["body"] == "hi"
    assert client.delete(f"/api/skills/lint?project_id={proj['id']}").status_code == 204


# ---------------------------------------------------------------- chat modes
def test_plan_mode_is_read_only(client, fake):
    client.put("/api/settings", json={"values": {"terminal_enabled": True}})
    conv = client.post("/api/conversations", json={}).json()
    fake.push(
        {"calls": [("run_command", {"command": "rm -rf build"}), ("run_command", {"command": "git status | head"}),
                   ("run_agent", {"task": "x"}), ("propose_memory", {"content": "x"})]},
        {"content": "Plan: 1. ..."})
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages",
                      {"content": "clean up", "mode": "plan"})
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results][:1] == [False] and "Plan mode" in results[0]["result"]
    assert results[1]["ok"] is True                              # read-only command is allowed
    assert all(not r["ok"] for r in results[2:])
    offered = fake.calls[0]["tools"]
    assert "run_agent" not in offered and not any(n.startswith("propose_") for n in offered) and "run_command" in offered
    assert "PLAN" in fake.calls[0]["messages"][0]["content"]
    assert client.get("/api/status").json()["pending_actions"] == 0


def test_manual_mode_asks_before_acting(client, fake):
    import asyncio
    from atom.assistant import Assistant

    class Call:
        id, name, arguments = "c1", "run_command", {"command": "ls"}

    async def go(approve):
        a = Assistant(client.app.state.svc) if hasattr(client.app.state, "svc") else Assistant(None)
        q: asyncio.Queue = asyncio.Queue()
        t = asyncio.create_task(a._gate(Call, "manual", q, True))
        ev = await q.get()
        assert ev["type"] == "approval_required" and ev["id"] == "c1"
        assert a.decide("c1", approve)
        return await t

    assert asyncio.run(go(True)) is None
    assert "denied" in asyncio.run(go(False))
    assert client.post("/api/chat/approvals/nope", json={"approve": True}).status_code == 404


def test_mode_validation_and_noninteractive_manual(client):
    conv = client.post("/api/conversations", json={}).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi", "mode": "yolo"})
    assert r.status_code == 422 or r.status_code == 400


def test_conversation_context_usage(client, fake):
    conv = client.post("/api/conversations", json={}).json()
    empty = client.get(f"/api/conversations/{conv['id']}/context").json()
    assert empty["exact"] is False and empty["limit"] == 32768 and empty["source"] == "server"
    assert empty["budget"] == 32768 - empty["reserve"]
    fake.push({"content": "hi", "prompt": 4000, "cached": 0, "out": 100})
    read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "hello"})
    u = client.get(f"/api/conversations/{conv['id']}/context").json()
    assert u["exact"] is True and u["used"] == 4100 and 0 < u["pct"] < 1
    assert client.get("/api/conversations/nope/context").status_code == 404
