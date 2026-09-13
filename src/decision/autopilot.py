"""End-to-end auto-pilot state machine for the labyrinth.

This module is the driver that turns the individual, already-verified live
task scripts into a continuous, hands-off run.  It is deliberately pure: it
never touches ADB or OCR itself.  It only decides *which* guarded live script
to run next and interprets that script's JSON result.  A ``ScriptInvoker``
callable performs the actual input; the CLI in ``scripts/tool_autopilot.py``
supplies the real one, while tests supply fakes.

The traversal it orchestrates:

    boss gacha  ->  initial characters  ->  map scan  ->  spatial route
        (matched)        (selected)          (nodes)        (node path)
        -> tile-by-tile traversal (normal battles,
                                                            relics, events)
    area boss  ->  final result

Safety invariants carried over from the orchestrator and the live scripts:

* ``帰還する`` / ``終了する`` are never issued by this driver.
* A battle defeat never retries the identical composition; the run withdraws.
* A missing map graph, an unrecognised screen, or a script safety_stop stops
  the run instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import json
from pathlib import Path

from .route_planner import AREA1_REQUIRED_TYPES, find_route_node_path, find_route_node_sequence, spatial_map_graph, verified_map_graph

# A live script result is a mapping with at least a ``status`` key.
ScriptResult = Mapping[str, Any]
# The invoker runs one guarded live script and returns its JSON result.
ScriptInvoker = Callable[[str, list[str]], ScriptResult]

# Script names (relative to scripts/) the driver may call.  Keeping this an
# explicit allow-list means the driver can never be talked into an arbitrary
# command by a bad OCR result.
ALLOWED_SCRIPTS = frozenset({
    "task_boss_gacha_live.py",
    "task_return_initial_char_live.py",
    "task_select_initial_characters_live.py",
    "task_prepare_l03_screen_live.py",
    "task_scan_map_live.py",
    "task_move_map_node_live.py",
    "task_confirm_move_live.py",
    "task_run_normal_battle_live.py",
    "task_start_area_boss_live.py",
    "task_wait_battle_result_live.py",
    "task_next_live.py",
    "task_close_live.py",
    "task_select_relic_live.py",
    "task_select_character_bonus_live.py",
    "task_select_event_live.py",
    "task_withdraw_live.py",
    "task_confirm_withdraw_live.py",
    "task_check_current_screen_live.py",
    "task_shop_exit_live.py",
})

# Tile types that lead into a battle the driver can start on its own.
BATTLE_TILES = frozenset({"normal", "extreme", "hell"})
# Tile types that hand a reward directly (no battle).
REWARD_TILES = frozenset({"relic", "connect_sign"})


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return default


def _node_type(graph: Mapping[str, Any], node_id: str) -> str:
    node = graph.get("nodes", {}).get(node_id)
    if isinstance(node, Mapping):
        return str(node.get("type", ""))
    return ""


@dataclass
class AutoPilotState:
    """Mutable, JSON-serializable run state for one auto-pilot session."""

    phase: str = "boss_gacha"
    passports: int = 0
    max_passports: int = 0
    boss_names: dict[str, str] = field(default_factory=dict)
    # Areas are 1-based.  Zero used to make every route look like Area 1 and
    # incorrectly trigger the mandatory Area 1 withdrawal gate.
    area: int = 1
    area_graph: dict[str, Any] | None = None
    node_positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    route: list[str] = field(default_factory=list)
    route_index: int = 0
    player_position: str = "unknown"
    player_position_confirmed: bool = False
    current_tile: str = ""
    battle_outcome: str = ""
    consecutive_defeats: int = 0
    max_consecutive_defeats: int = 3
    battles_won: int = 0
    tiles_visited: int = 0
    stop_reason: str | None = None
    status: str = "idle"
    difficulty: int = 10
    guild: str = "美食殿"
    allowed_bosses: dict[str, list[str]] = field(default_factory=lambda: {
        "3": ["ベノムサラマンドラ", "グレーターゴーレム"],
        "5": ["ゴブリンロード"],
    })
    log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "passports": self.passports,
            "max_passports": self.max_passports,
            "boss_names": self.boss_names,
            "area": self.area,
            "area_graph": self.area_graph,
            "node_positions": self.node_positions,
            "route": self.route,
            "route_index": self.route_index,
            "player_position": self.player_position,
            "player_position_confirmed": self.player_position_confirmed,
            "current_tile": self.current_tile,
            "battle_outcome": self.battle_outcome,
            "consecutive_defeats": self.consecutive_defeats,
            "battles_won": self.battles_won,
            "tiles_visited": self.tiles_visited,
            "stop_reason": self.stop_reason,
            "status": self.status,
            "difficulty": self.difficulty,
            "guild": self.guild,
            "allowed_bosses": self.allowed_bosses,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AutoPilotState":
        state = cls()
        for key, value in data.items():
            if hasattr(state, key) and key != "log":
                setattr(state, key, value)
        # Migrate states written before areas became explicitly 1-based.
        # Area 0 was never a valid labyrinth area; retaining it re-enabled the
        # Area 1 mandatory-route gate on every resumed run.
        if state.area == 0:
            state.area = 1
        return state


class AutoPilot:
    """Sequence guarded live scripts into a continuous labyrinth run."""

    def __init__(
        self,
        invoker: ScriptInvoker,
        *,
        passports: int = 0,
        avoid_hell: bool = True,
        max_consecutive_defeats: int = 3,
        battle_character_indices: str | None = None,
        difficulty: int = 10,
        guild: str = "美食殿",
        allowed_bosses: Mapping[str, list[str]] | None = None,
        step_logger: Callable[[dict[str, Any]], None] | None = None,
        state_file: str | Path | None = None,
    ) -> None:
        if passports < 0:
            raise ValueError("passports must be non-negative")
        if not 1 <= difficulty <= 10:
            raise ValueError("difficulty must be between 1 and 10")
        self.invoker = invoker
        self.step_logger = step_logger
        self.state_file = Path(state_file) if state_file else None
        self.state = AutoPilotState(passports=passports, max_passports=passports,
                                    max_consecutive_defeats=max_consecutive_defeats,
                                    difficulty=difficulty, guild=guild,
                                    allowed_bosses=allowed_bosses or {
                                        "3": ["ベノムサラマンドラ", "グレーターゴーレム"],
                                        "5": ["ゴブリンロード"],
                                    })
        self.avoid_hell = avoid_hell
        self.battle_character_indices = battle_character_indices
        self._stop_reason: str | None = None
        self._route_recheck_count = 0

    # -- public API ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        result = self.state.to_dict()
        result["stopped"] = self._stop_reason is not None
        result["stop_reason"] = self._stop_reason
        return result

    def request_stop(self) -> None:
        """Ask the driver to stop at the next safe boundary."""
        self.state.status = "stopping"

    def request_finish(self, reason: str = "finished_by_user") -> None:
        """Terminate the run at the next safe boundary."""
        self._stop_reason = reason
        self.state.stop_reason = reason
        self.state.status = "stopped"

    def resume(self) -> None:
        """Clear a stop so the run can continue from the current phase."""
        # Keep the persisted reason before clearing it.  The reason is the
        # resume routing signal; clearing it first made a stopped mandatory
        # route look like an ordinary plan phase and caused the same stale
        # graph to be reused.
        previous_stop_reason = str(self.state.stop_reason or self._stop_reason or "")
        self._stop_reason = None
        self.state.stop_reason = None
        # Manual/scripted withdrawal returns to the labyrinth TOP while the
        # persisted phase may still point at the old route.  Start a fresh
        # attempt from TOP rather than replaying stale coordinates.
        if self.state.phase != "boss_gacha":
            screen_check = self._invoke("task_check_current_screen_live.py", [])
            if str(screen_check.get("screen_id", "")) == "labyrinth_top":
                self.state.phase = "boss_gacha"
                self.state.area_graph = None
                self.state.route = []
                self.state.route_index = 0
            elif (str(screen_check.get("screen_id", "")) == "boss_map"
                  and self.state.phase == "start_battle"
                  and self.state.route_index > 0):
                # A manually resumed result may already have advanced past
                # the battle while the persisted phase still says start.
                self.state.phase = "scan_map"
                self.state.area_graph = None
                self.state.route = []
                self.state.route_index = 0
        # A guarded move failure clears the stale route before stopping.  A
        # resume must therefore begin with a fresh full scan; otherwise the
        # old phase would immediately hit route_unknown_before_action.
        if self.state.phase == "move_to_node" and (
            not self.state.route or not isinstance(self.state.area_graph, Mapping)
        ):
            self.state.phase = "scan_map"
            self.state.route_index = 0
        if self.state.phase == "plan_route" and (
            previous_stop_reason.startswith("area1_required_route_not_verified")
            or previous_stop_reason.startswith("verified_connection_graph_invalid")
        ):
            self.state.phase = "scan_map"
            self.state.area_graph = None
            self.state.route = []
            self.state.route_index = 0
        self.state.status = "running"

    def save_state(self) -> None:
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")

    def load_state(self) -> bool:
        if self.state_file is None or not self.state_file.exists():
            return False
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.state = AutoPilotState.from_dict(data)
        self._stop_reason = self.state.stop_reason
        return True

    def step(self) -> dict[str, Any]:
        """Run exactly one driver decision and return its outcome.

        Returns a dict with ``action`` (the script name or a control token),
        ``result`` (the script JSON, if any), and ``phase``.  A terminal run
        returns ``action`` of ``"stopped"`` or ``"completed"``.
        """
        if self.state.status in {"stopping", "stopped"}:
            reason = self.state.stop_reason or self._stop_reason or "stopped_by_user"
            if self._stop_reason is None:
                self._stop_reason = reason
            self.state.status = "stopped"
            self.state.stop_reason = reason
            self.save_state()
            return self._terminal("stopped", reason)
        if self._stop_reason is not None:
            return self._terminal("stopped", self._stop_reason)
        # A passport is an entry ticket: it gates starting a run, not
        # continuing one.  Once boss gacha has matched and the run is in
        # progress, the counter must not abort the traversal mid-labyrinth.
        if self.state.passports <= 0 and self.state.phase == "boss_gacha":
            return self._terminal("stopped", "passports_depleted")
        if self.state.consecutive_defeats >= self.state.max_consecutive_defeats:
            return self._terminal("stopped", "consecutive_defeats_limit")

        handler = self._handlers().get(self.state.phase)
        if handler is None:
            self._stop_reason = f"unknown_phase:{self.state.phase}"
            outcome = self._terminal("stopped", self._stop_reason)
        else:
            outcome = handler()
        self._finalize_step(outcome)
        if self.step_logger is not None:
            try:
                self.step_logger(dict(outcome))
            except Exception:
                pass
        return outcome

    def _finalize_step(self, outcome: dict[str, Any]) -> None:
        """Record the run status after a step and persist it for resume."""
        if outcome["action"] == "completed":
            self.state.status = "completed"
        elif outcome["action"] == "stopped" or self._stop_reason is not None:
            self.state.status = "stopped"
            self.state.stop_reason = self.state.stop_reason or self._stop_reason
        elif self.state.status != "stopping":
            self.state.status = "running"
        self.save_state()

    def run(self, *, max_steps: int = 500) -> dict[str, Any]:
        """Drive the run to a terminal state, bounded by ``max_steps``."""
        steps = 0
        while steps < max_steps:
            outcome = self.step()
            steps += 1
            if outcome["action"] in {"stopped", "completed"}:
                return outcome
        return self._terminal("stopped", "max_steps_exhausted")

    # -- phase handlers -----------------------------------------------------

    def _handlers(self) -> dict[str, Callable[[], dict[str, Any]]]:
        return {
            "boss_gacha": self._do_boss_gacha,
            "select_initial_characters": self._do_select_initial_characters,
            "scan_map": self._do_scan_map,
            "plan_route": self._do_plan_route,
            "withdraw_run": self._do_withdraw_run,
            "confirm_withdraw": self._do_confirm_withdraw,
            "move_to_node": self._do_move_to_node,
            "confirm_move": self._do_confirm_move,
            "handle_tile": self._do_handle_tile,
            "start_battle": self._do_start_battle,
            "wait_battle_result": self._do_wait_battle_result,
            "after_battle": self._do_after_battle,
            "finish_tile": self._finish_tile,
            "finish": self._do_finish,
        }

    def _do_boss_gacha(self) -> dict[str, Any]:
        # ボス名確定後の復帰で、ゲーム画面がすでに初期キャラ選択へ
        # 戻っている場合は、再ガチャせず選択フェーズへ引き継ぐ。
        if all(str(area) in self.state.boss_names for area in ("3", "5")):
            screen_check = self._invoke("task_check_current_screen_live.py", [])
            current_screen = str(screen_check.get("screen_id", ""))
            if current_screen in {"initial_char", "boss_map", "boss_detail"}:
                returned = self._invoke("task_return_initial_char_live.py", [])
                if str(returned.get("status", "")) != "ready":
                    self._stop_reason = f"return_initial_character_failed:{returned.get('status', 'unknown')}"
                    return self._terminal("stopped", self._stop_reason)
                self.state.phase = "select_initial_characters"
                return self._action("boss_gacha", {"status": "recovered_matched_bosses", "screen": current_screen})
        # The boss-gacha flow is template-driven; missing live evidence must
        # stop safely instead of falling back to OCR or guessed coordinates.
        result = self._invoke("task_boss_gacha_live.py",
                             ["--execute", "--default-models",
                              "--difficulty", str(self.state.difficulty), "--guild", self.state.guild,
                              *sum(([f"--area{area}-boss", name] for area, names in self.state.allowed_bosses.items()
                                    for name in names), [])])
        status = str(result.get("status", ""))
        self._log("boss_gacha", status, result)
        if status == "matched":
            self.state.boss_names = dict(result.get("boss_names", {}))
            self.state.passports = max(0, self.state.passports - 1)
            returned = self._invoke("task_return_initial_char_live.py", [])
            returned_status = str(returned.get("status", ""))
            self._log("boss_gacha", f"return_initial_char:{returned_status}", returned)
            if returned_status != "ready":
                self._stop_reason = f"return_initial_character_failed:{returned_status}"
                return self._terminal("stopped", self._stop_reason)
            # 新規出発では、ボス確定後に初期キャラを選択する。
            # gacha内部で初期キャラ画面まで遷移しても、ここではまだ
            # マップスキャンへ進めない。
            self.state.phase = "select_initial_characters"
            return self._action("boss_gacha", result)
        if status in {"safety_stop", "max_attempts"}:
            if status == "max_attempts" and self.state.passports > 0:
                # 10回の内部抽選上限は1バッチの境界。ユーザー方針の
                # 「止めずにガチャ継続」に従い、残りパスポートがある
                # 限り次バッチへ進む。無限ループにはしない。
                self.state.passports = max(0, self.state.passports - 1)
                if self.state.passports > 0:
                    self.state.phase = "boss_gacha"
                    return self._action("boss_gacha", {
                        "status": "retry_batch",
                        "completed_batch": int(result.get("attempt", 0)),
                        "remaining_passports": self.state.passports,
                    })
            self._stop_reason = str(result.get("reason", status))
            return self._terminal("stopped", self._stop_reason)
        if status == "user_confirmation_required" and str(result.get("reason", "")) == "challenge_active_requires_resume_assistance":
            # A battle is already in progress; wait for its result instead of re-rolling.
            self.state.phase = "wait_battle_result"
            return self._action("boss_gacha", result)
        # Any other status (e.g. a runner that withdraws and retries internally)
        # leaves the phase unchanged so the next step re-rolls.
        return self._action("boss_gacha", result)

    def _do_select_initial_characters(self) -> dict[str, Any]:
        result = self._invoke(
            "task_select_initial_characters_live.py",
            # The route policy already supplies the three confirmed card
            # positions.  Use the confirmed-position path so every gacha does
            # not reload PaddleOCR just to rediscover the same cards; it still
            # verifies the card crops are visible before tapping.
            ["--indices", "1,2,6", "--manual-confirmed", "--guild", self.state.guild],
        )
        status = str(result.get("status", ""))
        self._log("select_initial_characters", status, result)
        if status != "selected":
            self._stop_reason = f"initial_character_selection_failed:{status}"
            return self._terminal("stopped", self._stop_reason)
        prepared = self._invoke("task_prepare_l03_screen_live.py", [])
        prepared_status = str(prepared.get("status", ""))
        self._log("prepare_initial_map", prepared_status, prepared)
        if prepared_status != "ready":
            self._stop_reason = f"initial_map_prepare_failed:{prepared_status}"
            return self._terminal("stopped", self._stop_reason)
        self.state.phase = "scan_map"
        return self._action("select_initial_characters", prepared)

    def _do_scan_map(self) -> dict[str, Any]:
        result = self._invoke("task_scan_map_live.py", ["--full-scan"])
        status = str(result.get("status", ""))
        self._log("scan_map", status, result)
        if status != "scanned" or not isinstance(result.get("nodes"), list):
            reason = str(result.get("reason", ""))
            if status == "safety_stop" and reason in {"stopped_by_user", "finished_by_user"}:
                self._stop_reason = reason
            else:
                self._stop_reason = f"map_scan_failed:{status}"
            return self._terminal("stopped", self._stop_reason)
        nodes = result["nodes"]
        # A resolved tile is rendered as CLEAR_CURRENT and can obscure the
        # original tile label.  The prior battle result is authoritative for
        # this run: bind the next required Area 1 step to the real CONNECT_SIGN
        # in the next physical column when one is present.  Do not invent a
        # node or accept another type as a substitute.
        current_id = str(result.get("current_node_id", ""))
        current_node = next((node for node in nodes
                             if isinstance(node, Mapping) and str(node.get("id", "")) == current_id), None)
        if (self.state.area == 1 and self.state.tiles_visited == 0
                and isinstance(current_node, Mapping)
                and str(current_node.get("label", "")) == "CLEAR_CURRENT"):
            current_x = int(current_node.get("x", 0))
            next_x_values = sorted({int(node.get("x", 0)) for node in nodes
                                    if isinstance(node, Mapping)
                                    and int(node.get("x", 0)) > current_x + 150
                                    and str(node.get("type", "")) != "area_start"})
            if next_x_values:
                next_x = next_x_values[0]
                signs = [node for node in nodes
                         if isinstance(node, Mapping)
                         and str(node.get("type", "")) == "connect_sign"
                         and int(node.get("x", 0)) == next_x]
                if signs:
                    result["verified_edges"] = list(result.get("verified_edges", []))
                    for sign in signs:
                        result["verified_edges"].append({
                            "from": current_id, "to": str(sign["id"]),
                            "source": "known_rightward_continuation_area1",
                            "score": 1.0,
                        })
                    self.state.tiles_visited = 1
        self.state.node_positions = {
            str(node.get("id")): {
                "x": node.get("x"),
                "y": node.get("y"),
                "type": node.get("type"),
                "panel": node.get("panel"),
                "panel_x": node.get("panel_x"),
                "panel_fingerprint": node.get("panel_fingerprint"),
            }
            for node in nodes if isinstance(node, Mapping) and node.get("id") is not None
        }
        has_terminal = any(
            isinstance(node, Mapping) and str(node.get("type", "")) in {"area_boss", "area_exit"}
            for node in nodes
        )
        # Area 1 is known to end with a relic-only column.  When the optional
        # terminal-chest reference is unavailable, that confirmed relic is
        # the route endpoint; do not invent a chest node.
        area1_relic_endpoint = self.state.area == 1 and any(
            isinstance(node, Mapping) and str(node.get("type", "")) == "relic"
            for node in nodes
        )
        if not has_terminal and not area1_relic_endpoint:
            self._stop_reason = "map_terminal_node_not_recognized"
            return self._terminal("stopped", self._stop_reason)
        graph = spatial_map_graph(nodes, allow_relic_terminal=area1_relic_endpoint)
        if graph is None:
            self._stop_reason = "map_graph_not_derivable"
            return self._terminal("stopped", self._stop_reason)
        # Preserve only edges that the scanner actually verified.  The
        # spatial fallback may suggest adjacency, but suggestions are not
        # enough to authorize a tap.
        graph["verified_edges"] = result.get("verified_edges", [])
        self.state.area_graph = graph
        self.state.phase = "plan_route"
        return self._action("scan_map", result)

    def _do_plan_route(self) -> dict[str, Any]:
        graph = self.state.area_graph
        if not isinstance(graph, Mapping):
            self._stop_reason = "area_graph_missing"
            return self._terminal("stopped", self._stop_reason)
        start = str(graph.get("start", ""))
        goal_types = ("relic",) if self.state.area == 1 and not any(
            isinstance(node, Mapping) and str(node.get("type", "")) in {"area_boss", "area_exit"}
            for node in self.state.node_positions.values()
        ) else ("area_boss", "area_exit")
        node_path = find_route_node_path(graph, start=start, goal_types=goal_types, avoid_hell=self.avoid_hell)
        if not node_path:
            self._stop_reason = "no_reachable_route"
            return self._terminal("stopped", self._stop_reason)
        verified_pairs = {
            (str(edge.get("from")), str(edge.get("to")))
            for edge in graph.get("verified_edges", [])
            if isinstance(edge, Mapping) and edge.get("from") is not None and edge.get("to") is not None
        }
        # Prefer a route composed entirely of scanner-verified connections.
        # The spatial graph can contain plausible adjacency suggestions; use
        # those only as a fallback for diagnostics, never as an authorization
        # to tap.
        verified_graph = verified_map_graph(
            [dict(node, id=node_id) for node_id, node in graph.get("nodes", {}).items()],
            [{"from": left_id, "to": right_id} for left_id, right_id in verified_pairs],
            start=start,
        )
        if verified_graph is None:
            self._stop_reason = "verified_connection_graph_invalid"
            return self._terminal("stopped", self._stop_reason)
        # Persist the visually detected current platform even when the
        # mandatory-sequence check below has to stop for missing evidence.
        start_info = graph.get("nodes", {}).get(start) if isinstance(graph.get("nodes"), Mapping) else None
        if isinstance(start_info, Mapping) and str(start_info.get("type", "")) == "area_start":
            self.state.player_position = start
            self.state.player_position_confirmed = True
        if self.state.area == 1:
            # Area 1 is a prescribed route, not a shortest-path choice.
            full_sequence = list(AREA1_REQUIRED_TYPES)
            # ``normal`` occurs twice in the Area 1 sequence.  Derive the
            # remaining sequence from the number of confirmed visits instead
            # of searching by tile name, otherwise the second NORMAL can be
            # mistaken for the first one.  The start node is not a visit.
            consumed = max(0, min(int(self.state.tiles_visited), len(full_sequence)))
            sequence = full_sequence[consumed:]
            verified_path = find_route_node_sequence(
                verified_graph, start=start, required_types=sequence
            ) if sequence else []
            if sequence and not verified_path:
                # First re-scan once before withdrawing.  A single missing
                # measured edge can be caused by an overlapping viewport or
                # a transient connector frame; it is not enough evidence to
                # discard a map that may still be traversable.
                if self._route_recheck_count < 1:
                    self._route_recheck_count += 1
                    self.state.area_graph = None
                    self.state.route = []
                    self.state.route_index = 0
                    self.state.phase = "scan_map"
                    self._log("plan_route", "required_sequence_recheck", {
                        "start": start, "required": sequence,
                    })
                    return self._action("plan_route", {
                        "status": "required_sequence_recheck",
                        "next": "scan_map",
                        "required": sequence,
                    })
                # Area 1's two CONNECT_SIGN gates and final RELIC are hard
                # constraints.  Do not replace them with a generic terminal
                # route: an unreachable mandatory sequence requires withdrawal.
                self._log("plan_route", "area1_required_sequence_unreachable", {
                    "start": start, "required": sequence,
                })
                self.state.phase = "withdraw_run"
                return self._action("plan_route", {
                    "status": "area1_required_sequence_unreachable",
                    "next": "withdraw_run",
                    "required": sequence,
                })
        else:
            verified_path = find_route_node_path(verified_graph, start=start, avoid_hell=self.avoid_hell)
        if verified_path:
            node_path = verified_path
        unverified = [
            (node_path[index], node_path[index + 1])
            for index in range(len(node_path) - 1)
            if (node_path[index], node_path[index + 1]) not in verified_pairs
            and (node_path[index + 1], node_path[index]) not in verified_pairs
        ]
        if unverified:
            if self._route_recheck_count >= 1:
                self._stop_reason = "route_connection_unverified"
                self._log("plan_route", "stopped_unverified_connection", {"edges": unverified})
                return self._terminal("stopped", self._stop_reason)
            self._route_recheck_count += 1
            # A resumed run may contain a graph captured before the current
            # viewport was fully scanned.  Do not tap from that stale graph:
            # invalidate it and perform the guarded full scan again.
            self.state.area_graph = None
            self.state.route = []
            self.state.route_index = 0
            self.state.phase = "scan_map"
            self._log("plan_route", "route_recheck_required", {"edges": unverified})
            return self._action("plan_route", {"status": "route_recheck_required",
                                                "next": "scan_map", "edges": unverified})
        self.state.route = list(node_path)
        self.state.route_index = 0
        # Full scans also detect the platform carrying the current player.
        # Preserve that concrete node across a re-plan; resetting it to the
        # initial S after every event/reward scan makes the next route start
        # from the wrong tile.
        start_node = str(graph.get("start", ""))
        start_info = graph.get("nodes", {}).get(start_node) if isinstance(graph.get("nodes"), Mapping) else None
        if isinstance(start_info, Mapping) and str(start_info.get("type", "")) == "area_start":
            self.state.player_position = start_node
            self.state.player_position_confirmed = True
        elif not self.state.player_position_confirmed:
            self.state.player_position = "S"
            self.state.player_position_confirmed = True
        self.state.phase = "move_to_node"
        self._log("plan_route", "planned", {"route": node_path})
        return self._action("plan_route", {"route": node_path})

    def _do_withdraw_run(self) -> dict[str, Any]:
        """Withdraw an NG route using the explicit safe first step."""
        result = self._invoke("task_withdraw_live.py", [])
        status = str(result.get("status", ""))
        self._log("withdraw_run", status, result)
        if status != "withdraw_selected":
            self._stop_reason = f"withdraw_failed:{status}"
            return self._terminal("stopped", self._stop_reason)
        self.state.phase = "confirm_withdraw"
        return self._action("withdraw_run", result)

    def _do_confirm_withdraw(self) -> dict[str, Any]:
        """Confirm withdrawal, then reset only per-run traversal state."""
        result = self._invoke("task_confirm_withdraw_live.py", [])
        status = str(result.get("status", ""))
        self._log("confirm_withdraw", status, result)
        if status != "withdraw_confirmed":
            # The confirmation task may refuse a transient dialog.  If the
            # map is still visibly present, preserve the run and re-scan it
            # instead of treating the failed withdrawal as permission to
            # discard a potentially valid route.
            screen_check = self._invoke("task_check_current_screen_live.py", [])
            if str(screen_check.get("screen_id", "")) == "boss_map":
                self.state.area_graph = None
                self.state.route = []
                self.state.route_index = 0
                self.state.phase = "scan_map"
                self._route_recheck_count = 0
                self._log("confirm_withdraw", "withdraw_not_confirmed_map_recheck", {
                    "screen": "boss_map",
                })
                return self._action("confirm_withdraw", {
                    "status": "map_recheck",
                    "next": "scan_map",
                })
            self._stop_reason = f"withdraw_confirm_failed:{status}"
            return self._terminal("stopped", self._stop_reason)
        self.state.area = 1
        self.state.area_graph = None
        self.state.node_positions = {}
        self.state.route = []
        self.state.route_index = 0
        self.state.player_position = "unknown"
        self.state.player_position_confirmed = False
        self.state.current_tile = ""
        self.state.battle_outcome = ""
        self.state.consecutive_defeats = 0
        self.state.boss_names = {}
        self.state.tiles_visited = 0
        self._route_recheck_count = 0
        self.state.phase = "boss_gacha"
        return self._action("confirm_withdraw", {"status": status, "next": "boss_gacha"})

    def _current_node(self) -> tuple[str, dict[str, Any]] | None:
        if not (0 <= self.state.route_index < len(self.state.route)):
            return None
        node_id = self.state.route[self.state.route_index]
        position = self.state.node_positions.get(node_id)
        if position is None or position.get("x") is None or position.get("y") is None:
            return None
        return node_id, position

    def _do_move_to_node(self) -> dict[str, Any]:
        # Never act on a stale route after returning from a battle or an
        # externally completed step.  Prove that the map is visible first;
        # an unknown screen is a hard stop, not a coordinate guess.
        screen_check = self._invoke("task_check_current_screen_live.py", [])
        if str(screen_check.get("screen_id", "")) != "boss_map":
            self._stop_reason = "route_check_screen_unknown"
            return self._terminal("stopped", self._stop_reason)
        if not isinstance(self.state.area_graph, Mapping) or not self.state.route:
            # A child task may complete a direct-entry battle while the
            # orchestrator is stopped between move and confirm.  On the map,
            # an empty stale route is recoverable by a fresh full scan.
            self.state.phase = "scan_map"
            self.state.route = []
            self.state.route_index = 0
            return self._action("move_to_node", {"status": "recovered_to_scan_map"})
        node = self._current_node()
        if node is None:
            self._stop_reason = "route_node_position_missing"
            return self._terminal("stopped", self._stop_reason)
        node_id, position = node
        if self.state.route_index > 0:
            expected_current = self.state.route[self.state.route_index - 1]
            if self.state.player_position != expected_current or not self.state.player_position_confirmed:
                self._stop_reason = "player_position_unknown_before_action"
                return self._terminal("stopped", self._stop_reason)
        node_type = _node_type(self.state.area_graph or {}, node_id) or str(position.get("type", ""))
        if node_type not in ALLOWED_TILE_TYPES:
            self._stop_reason = f"unknown_tile_type:{node_type}"
            return self._terminal("stopped", self._stop_reason)
        args = ["--x", str(int(position["x"])), "--y", str(int(position["y"])), "--type", node_type]
        panel = position.get("panel")
        if panel is not None:
            panel_x = position.get("panel_x")
            panel_fingerprint = str(position.get("panel_fingerprint") or "")
            if panel_x is None or not panel_fingerprint:
                self._stop_reason = "route_node_panel_metadata_missing"
                return self._terminal("stopped", self._stop_reason)
            args.extend([
                "--panel", str(int(panel)),
                "--panel-x", str(int(panel_x)),
                "--panel-fingerprint", panel_fingerprint,
            ])
        result = self._invoke("task_move_map_node_live.py", args)
        status = str(result.get("status", ""))
        self._log("move_to_node", status, {"node": node_id, "type": node_type})
        if status not in {"moved", "confirmed_move"}:
            # A failed move is an unknown map state.  Do not discard the
            # route and immediately re-enter scan_map: that used to create
            # an unbounded scroll/re-scan loop when the destination could not
            # be confirmed.  Stop once, preserving the exact failure for the
            # AI-assisted diagnosis/fix path.
            self.state.route = []
            self.state.area_graph = None
            self.state.phase = "move_to_node"
            reason = str(result.get("reason") or status or "move_failed")
            self._stop_reason = f"move_failed:{node_id}:{reason}"
            self._log("move_to_node", "stopped_unknown_destination", {
                "node": node_id,
                "status": status,
                "reason": reason,
            })
            return self._terminal("stopped", self._stop_reason)
        self.state.current_tile = node_type
        self.state.phase = "confirm_move"
        return self._action("move_to_node", result)

    def _do_confirm_move(self) -> dict[str, Any]:
        result = self._invoke("task_confirm_move_live.py", [])
        status = str(result.get("status", ""))
        self._log("confirm_move", status, {})
        if status == "confirmed":
            self.state.player_position = self.state.route[self.state.route_index]
            self.state.player_position_confirmed = True
            self.state.tiles_visited += 1
            self.state.route_index += 1
            self.state.phase = "handle_tile"
            return self._action("confirm_move", result)
        if status == "safety_stop":
            # The move confirmation dialog is optional; some tiles enter
            # directly without a confirm dialog.  A safety_stop here means
            # the OK button was not found, so the move already took effect.
            self.state.player_position = self.state.route[self.state.route_index]
            self.state.player_position_confirmed = True
            self.state.tiles_visited += 1
            self.state.route_index += 1
            self.state.phase = "handle_tile"
            return self._action("confirm_move", result)
        self._stop_reason = f"move_confirm_failed:{status}"
        return self._terminal("stopped", self._stop_reason)

    def _do_handle_tile(self) -> dict[str, Any]:
        tile = self.state.current_tile
        if tile in BATTLE_TILES:
            self.state.phase = "start_battle"
            return self._action("handle_tile", {"tile": tile, "next": "start_battle"})
        if tile in REWARD_TILES:
            # Relic / connect-sign tiles hand a reward; close and continue.
            result = self._invoke("task_select_relic_live.py", ["--auto"])
            status = str(result.get("status", ""))
            self._log("handle_tile", f"reward:{status}", {"tile": tile})
            if status != "selected":
                self._stop_reason = f"reward_failed:{status}"
                return self._terminal("stopped", self._stop_reason)
            self.state.phase = "finish_tile"
            return self._action("handle_tile", result)
        if tile == "event":
            # Normal is the conservative default; the event script accepts
            # "normal"/"extreme" only, not a numeric index.
            result = self._invoke("task_select_event_live.py", ["--choice", "normal"])
            status = str(result.get("status", ""))
            self._log("handle_tile", f"event:{status}", {})
            if status != "selected":
                self._stop_reason = f"event_failed:{status}"
                return self._terminal("stopped", self._stop_reason)
            self.state.phase = "finish_tile"
            return self._action("handle_tile", result)
        if tile == "shop":
            # Shop automation is intentionally out of scope; skip it safely.
            result = self._invoke("task_shop_exit_live.py", [])
            status = str(result.get("status", ""))
            self._log("handle_tile", f"shop:{status}", {})
            if status != "completed":
                self._stop_reason = f"shop_failed:{status}"
                return self._terminal("stopped", self._stop_reason)
            self.state.phase = "finish_tile"
            return self._action("handle_tile", result)
        if tile == "area_boss":
            self.state.phase = "start_battle"
            return self._action("handle_tile", {"tile": tile, "next": "area_boss"})
        if tile == "area_exit":
            # The tap leaves the map.  The next screen is intentionally not
            # guessed here; a fresh current-screen preflight must classify it.
            self._stop_reason = "area_exit_destination_screen_requires_revalidation"
            return self._terminal("stopped", self._stop_reason)
        self._stop_reason = f"unhandled_tile:{tile}"
        return self._terminal("stopped", self._stop_reason)

    def _finish_tile(self) -> dict[str, Any]:
        # Rewards and recruit events can leave a character-join dialog open.
        # Prove and close it before treating the map as visible again.
        screen_check = self._invoke("task_check_current_screen_live.py", [])
        screen_id = str(screen_check.get("screen_id", ""))
        for _ in range(2):
            if screen_id not in {"character_join", "item_reward"}:
                break
            closed = self._invoke("task_close_live.py", [])
            if str(closed.get("status", "")) != "closed":
                self._stop_reason = f"tile_dialog_close_failed:{closed.get('reason', closed.get('status', 'unknown'))}"
                return self._terminal("stopped", self._stop_reason)
            screen_check = self._invoke("task_check_current_screen_live.py", [])
            screen_id = str(screen_check.get("screen_id", ""))
        if screen_id not in {"boss_map", "map"}:
            self._stop_reason = f"tile_screen_not_confirmed:{screen_id or 'unknown'}"
            return self._terminal("stopped", self._stop_reason)
        # After a non-battle tile the map is now confirmed; continue the route.
        if self.state.route_index < len(self.state.route):
            self.state.phase = "move_to_node"
        else:
            self.state.phase = "finish"
        return self._action("finish_tile", {"route_index": self.state.route_index})

    def _do_start_battle(self) -> dict[str, Any]:
        tile = self.state.current_tile
        # Recovery path: a battle may have been started by the live task
        # while the dashboard worker was stopped.  If the game is already
        # back on the map, do not start the same battle again; continue with
        # the next route node.
        if tile != "area_boss":
            screen_check = self._invoke("task_check_current_screen_live.py", [])
            if str(screen_check.get("screen_id", "")) in {"boss_map", "map"}:
                self.state.phase = "scan_map"
                self.state.route = []
                self.state.area_graph = None
                self._log("start_battle", "recovered_after_battle", {"screen": screen_check.get("screen_id")})
                return self._action("start_battle", {"status": "recovered_after_battle", "next": "scan_map"})
        if tile == "area_boss":
            result = self._invoke("task_start_area_boss_live.py", ["--formations", "1"])
        else:
            args: list[str] = []
            # Initial normal battles use every available character when the
            # visible pool is five or fewer; fixed indices can refer to cards
            # that are not present in this run.
            if self.battle_character_indices and self.state.tiles_visited > 1:
                args += ["--character-indices", self.battle_character_indices]
            if self.state.tiles_visited <= 1 and not self.state.boss_names:
                args.append("--initial-battle")
            result = self._invoke("task_run_normal_battle_live.py", args)
        status = str(result.get("status", ""))
        self._log("start_battle", status, {"tile": tile})
        if tile == "area_boss" and status == "user_assist_required":
            self._stop_reason = "area_boss_ex_equipment_manual_required"
            return self._terminal("stopped", self._stop_reason)
        if status not in {"started", "equipment_ready"}:
            self._stop_reason = f"battle_start_failed:{status}"
            return self._terminal("stopped", self._stop_reason)
        self.state.phase = "wait_battle_result"
        return self._action("start_battle", result)

    def _do_wait_battle_result(self) -> dict[str, Any]:
        result = self._invoke("task_wait_battle_result_live.py", ["--timeout", "120"])
        status = str(result.get("status", ""))
        text = str(result.get("text", ""))
        self._log("wait_battle_result", status, {"text": text[:80]})
        if status != "result_detected":
            self._stop_reason = f"battle_result_timeout:{status}"
            return self._terminal("stopped", self._stop_reason)
        compact = text.replace(" ", "")
        if "敗北" in compact or "リトライ" in compact or "LOSE" in compact.upper():
            self.state.battle_outcome = "defeat"
        else:
            self.state.battle_outcome = "victory"
        self.state.phase = "after_battle"
        return self._action("wait_battle_result", result)

    def _do_after_battle(self) -> dict[str, Any]:
        if self.state.battle_outcome == "defeat":
            self.state.consecutive_defeats += 1
            self._stop_reason = "battle_defeat"
            return self._terminal("stopped", "battle_defeat")
        self.state.consecutive_defeats = 0
        self.state.battles_won += 1
        # Advance through the victory screen, then any reward screens that
        # appear after extreme/hell or area-boss victories (relic selection,
        # character bonus).  Each script returns safety_stop when its screen
        # is absent, so it is safe to try them in sequence.
        for script, extra_args in (
            ("task_next_live.py", []),
            ("task_select_relic_live.py", ["--auto"]),
            ("task_select_character_bonus_live.py", ["--auto"]),
            ("task_close_live.py", []),
        ):
            result = self._invoke(script, extra_args)
            status = str(result.get("status", ""))
            self._log("after_battle", f"{script}:{status}", {})
            if status not in {"advanced", "closed", "selected", "safety_stop"}:
                self._stop_reason = f"reward_advance_failed:{status}"
                return self._terminal("stopped", self._stop_reason)
        if self.state.current_tile == "area_boss":
            self.state.phase = "finish"
            return self._action("after_battle", {"result": "area_boss_cleared"})
        # Back on the map; continue the route.
        if self.state.route_index < len(self.state.route):
            self.state.phase = "move_to_node"
        else:
            self.state.phase = "finish"
        return self._action("after_battle", {"route_index": self.state.route_index})

    def _do_finish(self) -> dict[str, Any]:
        self._log("finish", "completed", self.state.to_dict())
        return self._terminal("completed", "run_completed")

    # -- helpers ------------------------------------------------------------

    def _invoke(self, script: str, args: list[str]) -> ScriptResult:
        if script not in ALLOWED_SCRIPTS:
            raise ValueError(f"script_not_allowed:{script}")
        result = self.invoker(script, list(args))
        if not isinstance(result, Mapping):
            raise ValueError(f"invoker_returned_non_mapping:{script}")
        return result

    def _action(self, action: str, result: ScriptResult | dict[str, Any]) -> dict[str, Any]:
        return {"action": action, "result": dict(result), "phase": self.state.phase}

    def _terminal(self, action: str, reason: str) -> dict[str, Any]:
        self._log(action, reason, self.state.to_dict())
        return {"action": action, "result": {"reason": reason}, "phase": self.state.phase,
                "status": action, "reason": reason}

    def _stop(self, reason: str) -> None:
        self._stop_reason = reason

    def _log(self, action: str, status: str, detail: Mapping[str, Any]) -> None:
        self.state.log.append({"action": action, "status": status, "detail": dict(detail)})


ALLOWED_TILE_TYPES = frozenset({
    "normal", "extreme", "hell", "relic", "connect_sign", "shop", "event", "area_boss", "area_exit",
})
