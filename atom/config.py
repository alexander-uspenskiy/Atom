from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


def _local_tz() -> str:
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name() or "UTC"
    except Exception:  # noqa: BLE001
        return "UTC"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATOM_", env_file=".env", extra="ignore")

    # --- LLM (OpenAI-compatible server, llama-server by default) ---
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "qwen3.8-27b"
    llm_api_key: str = "local"
    agent_slot: int = 0          # llama-server slot kept warm for the agent loop
    extract_slot: int = 1        # separate slot for extraction / escalated thinking
    chat_slot: int = 2           # slot for the dashboard chat assistant
    # Sampling for tool-driving steps (non-thinking). presence_penalty is 0 rather than the model card's
    # 1.5 because a penalty on repeated tokens hurts exact refs / arguments in tool calls.
    temperature: float = 0.6
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 0.0

    # --- Thinking ---
    agent_thinking: str = "auto"     # off | auto (off, escalate when stuck) | on (always; slow, uses agent slot)
    agent_effort: str = "low"        # low | medium | xhigh
    chat_thinking: bool = False
    chat_effort: str = "low"

    # --- Agent budgets ---
    max_steps: int = 38              # was 25 (+50%, rounded up)
    max_wall_s: int = 1350           # was 900 (+50%)
    ctx_per_slot: int = 32768
    compact_at_tokens: int = 20000   # compact history once the prompt grows past this
    max_observation_tokens: int = 1500
    max_read_tokens: int = 3000
    max_extract_tokens: int = 4000
    max_tool_calls_per_step: int = 3
    max_concurrent_runs: int = 1

    # --- Browser ---
    headless: bool = True
    live_screenshots: bool = True
    agent_vision: bool = True        # give agents a `look` tool (page screenshot) when the model server has vision
    nav_timeout_ms: int = 30000
    action_timeout_ms: int = 8000
    block_resources: tuple[str, ...] = ("image", "media", "font")
    profile_dir: Path = ROOT / "data" / "profile"

    # --- Terminal (shell access for agents and chat; off by default) ---
    terminal_enabled: bool = False
    terminal_dir: str = ""           # working directory; empty = data/workspace
    terminal_timeout_s: int = 60
    terminal_restrict: bool = True   # guardrail: commands must stay inside the project folder

    # --- Assistant / memory ---
    auto_approve_assistant_actions: bool = False
    chat_mode: str = "auto"            # default chat mode: auto | manual | plan
    memory_inject_k: int = 4
    timezone: str = _local_tz()

    # --- Server / storage ---
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    data_dir: Path = ROOT / "data"
    skills_dir: Path = Path.home() / ".atom" / "skills"     # user-level skills; projects add <folder>/.atom/skills

    @property
    def db_path(self) -> Path:
        return self.data_dir / "atom.db"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def get_settings() -> Settings:
    return Settings()
