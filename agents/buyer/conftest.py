import pytest


@pytest.fixture(autouse=True)
def _no_goal_drafts_between_tests():
    """#449 RT-6: goal.DRAFTS is module state (a half-said goal per chat sender); one test's draft must never reach another."""
    import goal
    goal.DRAFTS.clear()
    yield
    goal.DRAFTS.clear()
