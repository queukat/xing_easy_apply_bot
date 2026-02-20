from __future__ import annotations

from dataclasses import dataclass

from xingbot.settings import Settings


@dataclass(frozen=True)
class XINGRetryPolicy:
    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    backoff_factor: float
    retry_statuses: tuple[int, ...]


@dataclass(frozen=True)
class XINGRateLimitPolicy:
    min_interval_s: float
    enabled: bool = True


@dataclass(frozen=True)
class XINGHttpPolicy:
    timeout_s: float
    user_agent: str
    proxy: str | None = None


@dataclass(frozen=True)
class XINGSafetyPolicy:
    action_interval_s: float
    max_actions_per_run: int
    rate_limit_enabled: bool
    dry_run_default: bool
    confirm_send_default: bool


@dataclass(frozen=True)
class XINGRuntimeConfig:
    retry: XINGRetryPolicy
    rate_limit: XINGRateLimitPolicy
    http: XINGHttpPolicy
    safety: XINGSafetyPolicy

    @classmethod
    def from_settings(cls, settings: Settings) -> "XINGRuntimeConfig":
        return cls(
            retry=XINGRetryPolicy(
                max_attempts=max(1, settings.xing_retries),
                base_delay_s=settings.xing_backoff_base_s,
                max_delay_s=settings.xing_backoff_max_s,
                backoff_factor=2.0,
                retry_statuses=tuple(settings.xing_retry_statuses),
            ),
            rate_limit=XINGRateLimitPolicy(
                min_interval_s=float(settings.xing_action_interval_s),
                enabled=bool(settings.xing_rate_limit_enabled),
            ),
            http=XINGHttpPolicy(
                timeout_s=float(settings.xing_http_timeout_s),
                user_agent=(settings.user_agent or ""),
                proxy=(None if not settings.xing_proxy else settings.xing_proxy),
            ),
            safety=XINGSafetyPolicy(
                action_interval_s=float(settings.xing_action_interval_s),
                max_actions_per_run=max(1, int(settings.xing_max_actions_per_run)),
                rate_limit_enabled=bool(settings.xing_rate_limit_enabled),
                dry_run_default=bool(settings.xing_dry_run_default),
                confirm_send_default=bool(settings.xing_confirm_send_default),
            ),
        )


__all__ = [
    "XINGHttpPolicy",
    "XINGRateLimitPolicy",
    "XINGRetryPolicy",
    "XINGSafetyPolicy",
    "XINGRuntimeConfig",
]
