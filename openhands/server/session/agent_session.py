import asyncio
import json
import time
from logging import LoggerAdapter
from pathlib import Path  # Added import
from types import MappingProxyType
from typing import Callable, cast

from openhands.controller import AgentController
from openhands.controller.agent import Agent
from openhands.controller.replay import ReplayManager
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig, AppConfig, LLMConfig
from openhands.core.exceptions import AgentRuntimeUnavailableError
from openhands.core.logger import OpenHandsLoggerAdapter
from openhands.core.schema.agent import AgentState
from openhands.events.action import ChangeAgentStateAction, MessageAction
from openhands.events.event import Event, EventSource
from openhands.events.stream import EventStream
from openhands.integrations.provider import PROVIDER_TOKEN_TYPE, ProviderHandler
from openhands.memory.memory import Memory
from openhands.microagent.microagent import BaseMicroAgent
from openhands.runtime import get_runtime_cls
from openhands.runtime.base import Runtime
from openhands.runtime.impl.remote.remote_runtime import RemoteRuntime
from openhands.security import SecurityAnalyzer, options
from openhands.storage.files import FileStore
from openhands.utils.async_utils import EXECUTOR, call_sync_from_async
from openhands.utils.shutdown_listener import should_continue

WAIT_TIME_BEFORE_CLOSE = 90
WAIT_TIME_BEFORE_CLOSE_INTERVAL = 5


class AgentSession:
    """Represents a session with an Agent

    Attributes:
        controller: The AgentController instance for controlling the agent.
    """

    sid: str
    user_id: str | None
    event_stream: EventStream
    file_store: FileStore
    controller: AgentController | None = None
    runtime: Runtime | None = None
    security_analyzer: SecurityAnalyzer | None = None
    _starting: bool = False
    _started_at: float = 0
    _closed: bool = False
    loop: asyncio.AbstractEventLoop | None = None
    logger: LoggerAdapter

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        status_callback: Callable | None = None,
        user_id: str | None = None,
    ):
        """Initializes a new instance of the Session class

        Parameters:
        - sid: The session ID
        - file_store: Instance of the FileStore
        """

        self.sid = sid
        self.event_stream = EventStream(sid, file_store, user_id)
        self.file_store = file_store
        self._status_callback = status_callback
        self.user_id = user_id
        self.logger = OpenHandsLoggerAdapter(
            extra={'session_id': sid, 'user_id': user_id}
        )

    async def start(
        self,
        runtime_name: str,
        config: AppConfig,
        agent: Agent,
        max_iterations: int,
        git_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
        max_budget_per_task: float | None = None,
        agent_to_llm_config: dict[str, LLMConfig] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        selected_repository: str | None = None,
        selected_branch: str | None = None,
        initial_message: MessageAction | None = None,
        replay_json: str | None = None,
    ):
        """Starts the Agent session
        Parameters:
        - runtime_name: The name of the runtime associated with the session
        - config:
        - agent:
        - max_iterations:
        - max_budget_per_task:
        - agent_to_llm_config:
        - agent_configs:
        """
        if self.controller or self.runtime:
            raise RuntimeError(
                'Session already started. You need to close this session and start a new one.'
            )

        if self._closed:
            self.logger.warning('Session closed before starting')
            return
        self._starting = True
        started_at = time.time()
        self._started_at = started_at
        finished = False  # For monitoring
        runtime_connected = False
        try:
            self._create_security_analyzer(config.security.security_analyzer)
            runtime_connected = await self._create_runtime(
                runtime_name=runtime_name,
                config=config,
                agent=agent,
                git_provider_tokens=git_provider_tokens,
                selected_repository=selected_repository,
                selected_branch=selected_branch,
            )

            if replay_json:
                initial_message = self._run_replay(
                    initial_message,
                    replay_json,
                    agent,
                    config,
                    max_iterations,
                    max_budget_per_task,
                    agent_to_llm_config,
                    agent_configs,
                )
            else:
                self.controller = self._create_controller(
                    agent,
                    config.security.confirmation_mode,
                    max_iterations,
                    max_budget_per_task=max_budget_per_task,
                    agent_to_llm_config=agent_to_llm_config,
                    agent_configs=agent_configs,
                )

            repo_directory = None
            if self.runtime and runtime_connected and selected_repository:
                repo_directory = selected_repository.split('/')[-1]
            self.memory = await self._create_memory(
                selected_repository=selected_repository,
                repo_directory=repo_directory,
            )

            if git_provider_tokens:
                provider_handler = ProviderHandler(provider_tokens=git_provider_tokens)
                await provider_handler.set_event_stream_secrets(self.event_stream)

            if not self._closed:
                if initial_message:
                    self.event_stream.add_event(initial_message, EventSource.USER)
                    self.event_stream.add_event(
                        ChangeAgentStateAction(AgentState.RUNNING),
                        EventSource.ENVIRONMENT,
                    )
                else:
                    self.event_stream.add_event(
                        ChangeAgentStateAction(AgentState.AWAITING_USER_INPUT),
                        EventSource.ENVIRONMENT,
                    )
            finished = True
        finally:
            self._starting = False
            success = finished and runtime_connected
            self.logger.info(
                'Agent session start',
                extra={
                    'signal': 'agent_session_start',
                    'success': success,
                    'duration': (time.time() - started_at),
                },
            )

    async def close(self):
        """Closes the Agent session"""
        if self._closed:
            return
        self._closed = True
        while self._starting and should_continue():
            self.logger.debug(
                f'Waiting for initialization to finish before closing session {self.sid}'
            )
            await asyncio.sleep(WAIT_TIME_BEFORE_CLOSE_INTERVAL)
            if time.time() <= self._started_at + WAIT_TIME_BEFORE_CLOSE:
                self.logger.error(
                    f'Waited too long for initialization to finish before closing session {self.sid}'
                )
                break
        if self.event_stream is not None:
            self.event_stream.close()
        if self.controller is not None:
            end_state = self.controller.get_state()
            end_state.save_to_session(self.sid, self.file_store, self.user_id)
            await self.controller.close()
        if self.runtime is not None:
            EXECUTOR.submit(self.runtime.close)
        if self.security_analyzer is not None:
            await self.security_analyzer.close()

    def _run_replay(
        self,
        initial_message: MessageAction | None,
        replay_json: str,
        agent: Agent,
        config: AppConfig,
        max_iterations: int,
        max_budget_per_task: float | None,
        agent_to_llm_config: dict[str, LLMConfig] | None,
        agent_configs: dict[str, AgentConfig] | None,
    ) -> MessageAction:
        """
        Replays a trajectory from a JSON file. Note that once the replay session
        finishes, the controller will continue to run with further user instructions,
        so we still need to pass llm configs, budget, etc., even though the replay
        itself does not call LLM or cost money.
        """
        assert initial_message is None
        replay_events = ReplayManager.get_replay_events(json.loads(replay_json))
        self.controller = self._create_controller(
            agent,
            config.security.confirmation_mode,
            max_iterations,
            max_budget_per_task=max_budget_per_task,
            agent_to_llm_config=agent_to_llm_config,
            agent_configs=agent_configs,
            replay_events=replay_events[1:],
        )
        assert isinstance(replay_events[0], MessageAction)
        return replay_events[0]

    def _create_security_analyzer(self, security_analyzer: str | None):
        """Creates a SecurityAnalyzer instance that will be used to analyze the agent actions

        Parameters:
        - security_analyzer: The name of the security analyzer to use
        """

        if security_analyzer:
            self.logger.debug(f'Using security analyzer: {security_analyzer}')
            self.security_analyzer = options.SecurityAnalyzers.get(
                security_analyzer, SecurityAnalyzer
            )(self.event_stream)

    async def _create_runtime(
        self,
        runtime_name: str,
        config: AppConfig,
        agent: Agent,
        git_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
        selected_repository: str | None = None,
        selected_branch: str | None = None,
    ) -> bool:
        """Creates a runtime instance

        Parameters:
        - runtime_name: The name of the runtime associated with the session
        - config:
        - agent:

        Return True on successfully connected, False if could not connect.
        Raises if already created, possibly in other situations.
        """

        if self.runtime is not None:
            raise RuntimeError('Runtime already created')

        self.logger.debug(f'Initializing runtime `{runtime_name}` now...')
        runtime_cls = get_runtime_cls(runtime_name)

        # ==========================================================================
        # Dynamically determine and set workspace paths for this conversation
        # ==========================================================================
        base_workspace_path = config.workspace_base or './workspace'
        conversation_id = self.sid
        host_conversation_path = Path(base_workspace_path).resolve() / conversation_id
        host_conversation_path.mkdir(parents=True, exist_ok=True)
        host_conversation_path_str = str(host_conversation_path)
        sandbox_conversation_path_str = '/workspace'  # Standard path inside sandbox

        self.logger.info(
            f'Setting up workspace for conversation {conversation_id} at: {host_conversation_path_str}'
        )

        # Create a deep copy of the AppConfig to modify for this specific runtime instance
        temp_config_for_runtime = config.model_copy(deep=True)

        # Set the dynamic workspace paths directly on the AppConfig copy
        # This ensures both LocalRuntime (reading workspace_base) and DockerRuntime (reading mount paths) get the correct per-conversation paths.
        temp_config_for_runtime.workspace_base = host_conversation_path_str
        temp_config_for_runtime.workspace_mount_path = host_conversation_path_str
        temp_config_for_runtime.workspace_mount_path_in_sandbox = (
            sandbox_conversation_path_str
        )
        # ==========================================================================

        if runtime_cls == RemoteRuntime:
            # RemoteRuntime might need different handling or might not support this dynamic workspace concept easily.
            # For now, we'll pass the modified config, but this might need further review if RemoteRuntime is used.
            self.runtime = runtime_cls(
                config=temp_config_for_runtime,  # Use modified config
                event_stream=self.event_stream,
                sid=self.sid,
                plugins=agent.sandbox_plugins,
                # Removed duplicated arguments below
                status_callback=self._status_callback,
                headless_mode=False,
                attach_to_existing=False,
                git_provider_tokens=git_provider_tokens,
                user_id=self.user_id,
            )
        else:
            provider_handler = ProviderHandler(
                provider_tokens=git_provider_tokens
                or cast(PROVIDER_TOKEN_TYPE, MappingProxyType({}))
            )
            env_vars = await provider_handler.get_env_vars(expose_secrets=True)

            self.runtime = runtime_cls(
                config=temp_config_for_runtime,  # Use modified config
                event_stream=self.event_stream,
                sid=self.sid,
                plugins=agent.sandbox_plugins,
                status_callback=self._status_callback,
                headless_mode=False,
                attach_to_existing=False,
                env_vars=env_vars,
            )

        # FIXME: this sleep is a terrible hack.
        # This is to give the websocket a second to connect, so that
        # the status messages make it through to the frontend.
        # We should find a better way to plumb status messages through.
        await asyncio.sleep(1)
        try:
            await self.runtime.connect()
        except AgentRuntimeUnavailableError as e:
            self.logger.error(f'Runtime initialization failed: {e}')
            if self._status_callback:
                self._status_callback(
                    'error', 'STATUS$ERROR_RUNTIME_DISCONNECTED', str(e)
                )
            return False

        if selected_repository and git_provider_tokens:
            await call_sync_from_async(
                self.runtime.clone_repo,
                git_provider_tokens,
                selected_repository,
                selected_branch,
            )
            await call_sync_from_async(self.runtime.maybe_run_setup_script)

        self.logger.debug(
            f'Runtime initialized with plugins: {[plugin.name for plugin in self.runtime.plugins]}'
        )
        return True

    def _create_controller(
        self,
        agent: Agent,
        confirmation_mode: bool,
        max_iterations: int,
        max_budget_per_task: float | None = None,
        agent_to_llm_config: dict[str, LLMConfig] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        replay_events: list[Event] | None = None,
    ) -> AgentController:
        """Creates an AgentController instance

        Parameters:
        - agent:
        - confirmation_mode: Whether to use confirmation mode
        - max_iterations:
        - max_budget_per_task:
        - agent_to_llm_config:
        - agent_configs:
        """

        if self.controller is not None:
            raise RuntimeError('Controller already created')
        if self.runtime is None:
            raise RuntimeError(
                'Runtime must be initialized before the agent controller'
            )

        msg = (
            '\n--------------------------------- OpenHands Configuration ---------------------------------\n'
            f'LLM: {agent.llm.config.model}\n'
            f'Base URL: {agent.llm.config.base_url}\n'
        )

        msg += (
            f'Agent: {agent.name}\n'
            f'Runtime: {self.runtime.__class__.__name__}\n'
            f'Plugins: {agent.sandbox_plugins}\n'
            '-------------------------------------------------------------------------------------------'
        )
        self.logger.debug(msg)

        controller = AgentController(
            sid=self.sid,
            event_stream=self.event_stream,
            agent=agent,
            max_iterations=int(max_iterations),
            max_budget_per_task=max_budget_per_task,
            agent_to_llm_config=agent_to_llm_config,
            agent_configs=agent_configs,
            confirmation_mode=confirmation_mode,
            headless_mode=False,
            status_callback=self._status_callback,
            initial_state=self._maybe_restore_state(),
            replay_events=replay_events,
        )

        return controller

    async def _create_memory(
        self, selected_repository: str | None, repo_directory: str | None
    ) -> Memory:
        memory = Memory(
            event_stream=self.event_stream,
            sid=self.sid,
            status_callback=self._status_callback,
        )

        if self.runtime:
            # sets available hosts and other runtime info
            memory.set_runtime_info(self.runtime)

            # loads microagents from repo/.openhands/microagents
            microagents: list[BaseMicroAgent] = await call_sync_from_async(
                self.runtime.get_microagents_from_selected_repo, selected_repository
            )
            memory.load_user_workspace_microagents(microagents)

            if selected_repository and repo_directory:
                memory.set_repository_info(selected_repository, repo_directory)
        return memory

    def _maybe_restore_state(self) -> State | None:
        """Helper method to handle state restore logic."""
        restored_state = None

        # Attempt to restore the state from session.
        # Use a heuristic to figure out if we should have a state:
        # if we have events in the stream.
        try:
            restored_state = State.restore_from_session(
                self.sid, self.file_store, self.user_id
            )
            self.logger.debug(f'Restored state from session, sid: {self.sid}')
        except Exception as e:
            if self.event_stream.get_latest_event_id() > 0:
                # if we have events, we should have a state
                self.logger.warning(f'State could not be restored: {e}')
            else:
                self.logger.debug('No events found, no state to restore')
        return restored_state

    def get_state(self) -> AgentState | None:
        controller = self.controller
        if controller:
            return controller.state.agent_state
        if time.time() > self._started_at + WAIT_TIME_BEFORE_CLOSE:
            # If 5 minutes have elapsed and we still don't have a controller, something has gone wrong
            return AgentState.ERROR
        return None

    def is_closed(self) -> bool:
        return self._closed
