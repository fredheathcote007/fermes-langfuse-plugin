"""OBS-002 synthetic opt-in attribution boundary adversarial tests for PR293.

No real credentials, users, traces, I/O, or runtime services.
"""
import contextlib

import pytest
from hermes_constants import hermes_home_key
from test_langfuse_multiprofile_lifecycle import plugin, profile, open_turn

class ScopedConfig:
    plugin_id = "langfuse"
    profile_name = "synthetic-profile"
    def current_cron_execution(self):
        return None
    def __init__(self, opt_in):
        self.opt_in = opt_in
    def get_config(self, name, default=False):
        assert name == "end_user_attribution"
        return bool(self.opt_in.get(hermes_home_key(), False))

def setup(module, homes, enabled):
    module._sdk_identity_queue_discard_verified = lambda: True
    with profile(homes[0]):
        a = hermes_home_key()
    with profile(homes[1]):
        b = hermes_home_key()
    module._PLUGIN_CTX = ScopedConfig({a: enabled[0], b: enabled[1]})
    return a, b

def prepare_turn(module, *, turn="collision", sender="synthetic-a", session="same-session"):
    module.on_pre_llm_call(turn_id=turn, sender_id=sender)
    module.on_pre_llm_request(
        session_id=session, turn_id=turn, api_request_id="request",
        provider="provider", model="model", messages=[]
    )
    return module._TRACE_STATE[module._trace_key("", session, turn_id=turn)]

def test_optout_profile_does_not_inherit_sender_from_optin_profile(plugin):
    module, homes, _ = plugin
    setup(module, homes, (True, False))
    with profile(homes[0]):
        first = prepare_turn(module)
        assert first.propagated.get("user_id") == "synthetic-a"
    with profile(homes[1]):
        second = prepare_turn(module, sender="synthetic-b")
        assert second.propagated.get("user_id", "") == ""

def test_same_turn_id_does_not_swap_two_opted_in_senders(plugin):
    module, homes, _ = plugin
    setup(module, homes, (True, True))
    with profile(homes[0]):
        module.on_pre_llm_call(turn_id="collision", sender_id="synthetic-a")
    with profile(homes[1]):
        module.on_pre_llm_call(turn_id="collision", sender_id="synthetic-b")
    with profile(homes[0]):
        first = module.on_pre_llm_request(
            session_id="same-session", turn_id="collision", api_request_id="request",
            provider="provider", model="model", messages=[]
        )
        state = module._TRACE_STATE[module._trace_key("", "same-session", turn_id="collision")]
        assert state.propagated.get("user_id") == "synthetic-a"

def test_child_session_inheritance_is_isolated_from_opted_out_profile(plugin):
    module, homes, _ = plugin
    setup(module, homes, (True, False))
    with profile(homes[0]):
        parent = prepare_turn(module, turn="parent-turn", sender="synthetic-a")
        assert parent.propagated.get("user_id") == "synthetic-a"
        module.on_subagent_start(parent_turn_id="parent-turn", child_session_id="same-child", child_role="helper")
    with profile(homes[1]):
        child = prepare_turn(module, turn="new-child-turn", sender="synthetic-b", session="same-child")
        assert child.propagated.get("user_id", "") == ""

def test_other_profile_cannot_clear_child_attribution(plugin):
    module, homes, _ = plugin
    setup(module, homes, (True, False))
    with profile(homes[0]):
        prepare_turn(module, turn="parent-turn", sender="synthetic-a")
        module.on_subagent_start(parent_turn_id="parent-turn", child_session_id="same-child", child_role="helper")
        before = dict(module._USER_BY_CHILD_SESSION)
        assert before
    with profile(homes[1]):
        module.on_subagent_stop(child_session_id="same-child")
    with profile(homes[0]):
        assert dict(module._USER_BY_CHILD_SESSION) == before


def test_revoking_opt_in_before_request_clears_cached_sender(plugin):
    module, homes, _ = plugin
    a, _ = setup(module, homes, (True, False))
    with profile(homes[0]):
        module.on_pre_llm_call(turn_id="toggle-turn", sender_id="synthetic-a")
        assert module._SENDER_BY_TURN
        module._PLUGIN_CTX.opt_in[a] = False
        module.on_pre_llm_request(
            session_id="same-session", turn_id="toggle-turn",
            api_request_id="request", provider="provider", model="model",
            messages=[]
        )
        state = module._TRACE_STATE[
            module._trace_key("", "same-session", turn_id="toggle-turn")
        ]
        assert state.propagated.get("user_id", "") == ""
        assert not module._SENDER_BY_TURN


def test_revoking_opt_in_suppresses_new_child_attribution(plugin):
    module, homes, _ = plugin
    a, _ = setup(module, homes, (True, False))
    with profile(homes[0]):
        parent = prepare_turn(module, turn="revoked-parent")
        assert parent.propagated.get("user_id") == "synthetic-a"
        module._PLUGIN_CTX.opt_in[a] = False
        module.on_subagent_start(
            parent_turn_id="revoked-parent",
            child_session_id="new-child", child_role="helper"
        )
        assert parent.propagated.get("user_id", "") == ""
        assert not module._USER_BY_CHILD_SESSION


def test_concurrent_profile_turns_keep_attribution_isolated(plugin):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    module, homes, _ = plugin
    a, b = setup(module, homes, (True, False))
    # Repeated same-ID A/B racing calls, with B alternating opt-in/out.
    # 64 iterations stays below the plugin's 256 live trace limit.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for iteration in range(64):
            module._PLUGIN_CTX.opt_in[b] = bool(iteration % 2)
            barrier = Barrier(2)
            turn_id = f"same-turn-{iteration}"
            def run(side):
                with profile(homes[side]):
                    sender = f"synthetic-{side}-{iteration}"
                    module.on_pre_llm_call(turn_id=turn_id, sender_id=sender)
                    barrier.wait(timeout=4)
                    module.on_pre_llm_request(
                        session_id="shared-session", turn_id=turn_id,
                        api_request_id="request", provider="provider",
                        model="model", messages=[]
                    )
                    state = module._TRACE_STATE[
                        module._trace_key("", "shared-session", turn_id=turn_id)
                    ]
                    return state.propagated.get("user_id", "")
            futures = [pool.submit(run, side) for side in (0, 1)]
            actual = [future.result(timeout=7) for future in futures]
            expected = [f"synthetic-0-{iteration}",
                        f"synthetic-1-{iteration}" if iteration % 2 else ""]
            assert actual == expected, f"attribution cross-profile mismatch in iteration {iteration}"


def test_revoked_profile_cannot_propagate_stale_user_to_tool_but_opted_in_profile_can(plugin, monkeypatch):
    module, homes, _ = plugin
    a, b = setup(module, homes, (True, True))
    propagated = []

    @contextlib.contextmanager
    def capture(**attributes):
        propagated.append(dict(attributes))
        yield

    monkeypatch.setattr(module, "propagate_attributes", capture)
    with profile(homes[0]):
        parent = prepare_turn(module, turn="revoked-tool", sender="synthetic-a")
        module._PLUGIN_CTX.opt_in[a] = False
        module.on_pre_tool_call(
            session_id="same-session", turn_id="revoked-tool", tool_name="terminal",
            tool_call_id="a-tool", args={"command": "pwd"},
        )
        assert parent.propagated.get("user_id", "") == ""
        revoked_tool = propagated[-1]

    with profile(homes[1]):
        prepare_turn(module, turn="enabled-tool", sender="synthetic-b", session="other-session")
        module.on_pre_tool_call(
            session_id="other-session", turn_id="enabled-tool", tool_name="terminal",
            tool_call_id="b-tool", args={"command": "pwd"},
        )
        enabled_tool = propagated[-1]

    assert "user_id" not in revoked_tool
    assert enabled_tool["user_id"] == "synthetic-b"


def test_revoked_profile_cannot_propagate_stale_user_to_moa_but_opted_in_profile_can(plugin, monkeypatch):
    module, homes, _ = plugin
    a, b = setup(module, homes, (True, True))
    propagated = []

    @contextlib.contextmanager
    def capture(**attributes):
        propagated.append(dict(attributes))
        yield

    monkeypatch.setattr(module, "propagate_attributes", capture)
    references = [{"label": "advisor", "model": "advisor-model", "output": "answer"}]
    with profile(homes[0]):
        parent = prepare_turn(module, turn="revoked-moa", sender="synthetic-a")
        module._PLUGIN_CTX.opt_in[a] = False
        module._emit_moa_reference_generations(parent, client=object(), references=references)
        assert parent.propagated.get("user_id", "") == ""
        revoked_moa = propagated[-1]

    with profile(homes[1]):
        enabled_parent = prepare_turn(module, turn="enabled-moa", sender="synthetic-b", session="other-session")
        module._emit_moa_reference_generations(enabled_parent, client=object(), references=references)
        enabled_moa = propagated[-1]

    assert "user_id" not in revoked_moa
    assert enabled_moa["user_id"] == "synthetic-b"


def test_unsafe_sdk_explicit_optin_fails_closed_for_every_profile(plugin, caplog):
    """Opt-in is not permission to leak through an unpurgeable SDK batch queue."""
    module, homes, _ = plugin
    setup(module, homes, (True, True))
    module._sdk_identity_queue_discard_verified = lambda: False
    for index, home in enumerate(homes):
        with profile(home):
            state = prepare_turn(module, turn="unsafe-optin", sender=f"SYNTHETIC-{index}")
            assert "user_id" not in state.propagated
            assert "SYNTHETIC-" not in str(state.propagated)
            assert module._SENDER_BY_TURN == {}
            assert module._USER_BY_CHILD_SESSION == {}
    assert "verified queue-discard capability" in caplog.text
    assert "SYNTHETIC-" not in caplog.text


def test_unsupported_sdk_mode_never_creates_pre_revocation_identity(plugin):
    """A prior request to attribute cannot enqueue identity when SDK purge is unsupported."""
    module, homes, clients = plugin
    a, b = setup(module, homes, (True, False))
    module._sdk_identity_queue_discard_verified = lambda: False
    with profile(homes[0]):
        state = prepare_turn(module, turn="before-optout", sender="SYNTHETIC-SECRET")
        assert "user_id" not in state.propagated
        module._PLUGIN_CTX.opt_in[a] = False
        module.on_session_finalize(session_id="same-session")
        module._flush(clients[a])
        assert module._SENDER_BY_TURN == {}
    with profile(homes[1]):
        state = prepare_turn(module, turn="other-profile", sender="SYNTHETIC-OTHER")
        assert "user_id" not in state.propagated
    assert all(not value for value in module._USER_BY_CHILD_SESSION.values())
