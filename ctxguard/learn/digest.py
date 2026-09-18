"""Digest builder for distilling high-density failure/recovery episodes within token budget."""

from dataclasses import dataclass
from typing import List
from ctxguard.learn.scanner import LogEvent


@dataclass
class DigestEpisode:
    """A self-contained episode of failure, retries, and eventual recovery."""
    session_id: str
    events: List[LogEvent]
    has_error: bool = False
    has_recovery: bool = False
    has_user_interrupt: bool = False


class DigestBuilder:
    """Condenses raw conversation events into high-signal episodes within token budget.
    Inspired by CtxGuard Engine's 80K token budget with exponential decay fallback.
    """

    def __init__(self, token_budget: int = 80000):
        self.token_budget = token_budget

    def build_digest(self, raw_events: List[LogEvent]) -> List[LogEvent]:
        """Filter out normal chitchat and extract high-density failure-recovery sequences."""
        if not raw_events:
            return []

        # 1. Group events by session_id
        session_groups: dict[str, List[LogEvent]] = {}
        for ev in raw_events:
            session_groups.setdefault(ev.session_id, []).append(ev)

        critical_events: List[LogEvent] = []

        # 2. Extract failure-recovery windows
        for session_id, events in session_groups.items():
            episodes = self._extract_session_episodes(events)
            for ep in episodes:
                if ep.has_error or ep.has_user_interrupt or ep.has_recovery:
                    critical_events.extend(ep.events)

        # 3. Budget enforcement with halving fallback
        return self._enforce_budget(critical_events, self.token_budget)

    def _extract_session_episodes(self, events: List[LogEvent]) -> List[DigestEpisode]:
        """Scan a session's events and isolate failure -> retry -> recovery episodes."""
        episodes: List[DigestEpisode] = []
        n = len(events)
        i = 0

        while i < n:
            ev = events[i]
            # Check if this event is an error or user interrupt
            if ev.is_error or ev.user_interrupt:
                # Build an episode window: [context_before, error, retries..., recovery/end]
                start_idx = max(0, i - 1)  # Include the triggering tool call
                end_idx = min(n, i + 6)    # Window to observe up to 5 subsequent retry steps

                window_events = events[start_idx:end_idx]
                has_recovery = any(
                    (not w.is_error and w.role == "tool" and w.output.strip() != "")
                    for w in window_events[1:]
                )

                episodes.append(DigestEpisode(
                    session_id=ev.session_id,
                    events=window_events,
                    has_error=ev.is_error,
                    has_recovery=has_recovery,
                    has_user_interrupt=ev.user_interrupt,
                ))
                i = end_idx
            else:
                i += 1

        return episodes

    def _estimate_tokens(self, events: List[LogEvent]) -> int:
        """Heuristic character-to-token count estimate (approx 4 chars/token)."""
        char_count = sum(len(e.output) + len(str(e.tool_input)) + len(e.tool_name) for e in events)
        return max(1, char_count // 4)

    def _enforce_budget(self, events: List[LogEvent], budget: int) -> List[LogEvent]:
        """Apply exponential decay / halving truncation if events exceed token budget."""
        current_tokens = self._estimate_tokens(events)
        if current_tokens <= budget:
            return events

        # If overflowing, take most recent episodes first
        active_budget = budget
        trimmed = events[:]
        while self._estimate_tokens(trimmed) > active_budget and len(trimmed) > 1:
            # Cut oldest 25% of events
            cut_count = max(1, len(trimmed) // 4)
            trimmed = trimmed[cut_count:]

        return trimmed
