# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : category.py
@Time  : 2026-08-01
"""


class Category:
    """
    What kind of problem a failure is.

    The distinction that matters operationally is "is this the system under
    test being wrong" versus "is this our harness, our data, or the network".
    A suite that cannot separate those trains people to ignore red builds.
    """

    DEFECT = 'defect'
    """The system under test answered wrongly. Someone should look at the code."""

    CONTRACT = 'contract'
    """The response no longer matches its schema -- an interface changed."""

    ENVIRONMENT = 'environment'
    """Could not reach or talk to the system. Nothing was tested."""

    DATA = 'data'
    """Preconditions were unmet: no account, no balance, missing fixture data."""

    HARNESS = 'harness'
    """The test itself is broken -- setup blew up, a fixture is missing."""

    UNKNOWN = 'unknown'
    """Not enough signal to say. Deliberately not guessed at."""


class Confidence:
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'


# Whether a category means the system under test is implicated. Everything
# else is our own problem and should not be reported as a product defect.
BLAMES_SYSTEM_UNDER_TEST = {Category.DEFECT, Category.CONTRACT}

NEXT_STEP = {
    Category.DEFECT: 'compare the actual value against what the requirement says it should be',
    Category.CONTRACT: 'check whether the interface changed; regenerate the client/schema',
    Category.ENVIRONMENT: 'check the endpoint is up and reachable, then re-run',
    Category.DATA: 'check the fixture or account state this test depends on',
    Category.HARNESS: 'fix the test setup itself -- nothing was actually exercised',
    Category.UNKNOWN: 'read the full traceback via explain_failure',
}
