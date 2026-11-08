"""Run-finished notifications: results of chat-started runs are posted back into the conversation."""
import json
import time

from atom.notify import format_outcome
from tests.conftest import make_local_agent, read_sse, wait_run
from tests.test_api import DONE


def _messages(client, cid):
    return client.get(f"/api/conversations/{cid}").json()["messages"]


def _wait_for(pred, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("condition not met")


def test_finished_chat_run_posts_result_back(client, fake, site):
    make_local_agent(client, name="Runner")
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("run_agent", {"agent": "runner", "task": "say hello", "start_url": site.base + "/"})]},
              {"content": "Started; I can't wait for it."}, DONE("hello there"))
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "run it"})
    rid = next(e for e in events if e["type"] == "run_started")["run_id"]
    wait_run(client, rid)
    msg = _wait_for(lambda: next((m for m in _messages(client, conv["id"])
                                  if m["role"] == "assistant" and m["run_id"] == rid), None))
    assert "finished" in msg["content"] and "hello there" in msg["content"]


def test_not_duplicated_when_get_run_already_reported(client, fake, site, svc):
    make_local_agent(client, name="Runner")
    conv = client.post("/api/conversations", json={}).json()
    fake.push({"calls": [("run_agent", {"agent": "runner", "task": "say hello", "start_url": site.base + "/"})]},
              {"content": "started"}, DONE("hi"))
    events = read_sse(client, "POST", f"/api/conversations/{conv['id']}/messages", {"content": "run it"})
    rid = next(e for e in events if e["type"] == "run_started")["run_id"]
    wait_run(client, rid)
    _wait_for(lambda: any(m["run_id"] == rid and m["role"] == "assistant" for m in _messages(client, conv["id"])))
    # a second conversation whose model already saw the finished run through get_run must not get a repeat
    c2 = svc.conversations.create("other")["id"]
    svc.conversations.append(c2, "tool", "{}", tool_call_id="t1", run_id=rid)
    svc.conversations.append(c2, "tool", json.dumps({"id": rid, "status": "done"}), tool_call_id="t2")
    assert svc.notifier._already_reported(c2, rid)
    assert not svc.notifier._already_reported(conv["id"], rid)


def test_non_chat_runs_are_ignored(svc):
    import asyncio
    assert asyncio.run(svc.notifier.handle({"id": "x", "trigger": "schedule"})) is False


def test_format_outcome():
    ok = format_outcome({"id": "r1", "agent_name": "A", "status": "done", "success": True, "result": "all good",
                         "wall_seconds": 125})
    assert "finished after 2 min 5 s" in ok and "all good" in ok
    assert "failed" in format_outcome({"id": "r2", "status": "failed", "error": "boom"})
    assert "stopped" in format_outcome({"id": "r3", "status": "stopped"})


def test_telegram_bridge_forwards_only_to_matching_user(svc):
    import asyncio
    from atom.connectors import telegram as tg

    class Api:
        sent = []
        async def send(self, chat_id, text, **kw): self.sent.append((chat_id, text))

    api = Api()
    b = tg.Bridge("bot", {"allowed_user_ids": "111,222"}, svc, api)
    asyncio.run(b._notify(b._title(222), "done!"))
    asyncio.run(b._notify("Chat page", "ignored"))
    assert api.sent == [(222, "done!")]
