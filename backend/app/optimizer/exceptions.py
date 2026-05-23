class OptimizerError(Exception):
    """Base error for the routing optimizer."""


class InfeasibleScheduleError(OptimizerError):
    """No feasible assignment exists for the given hard constraints."""

    def __init__(self, messages: list[str], unassigned_job_ids: list[str] | None = None) -> None:
        self.messages = messages
        self.unassigned_job_ids = unassigned_job_ids or []
        detail = "; ".join(messages) if messages else "infeasible"
        super().__init__(detail)
