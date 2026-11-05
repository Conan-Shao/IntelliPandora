# IntelliPandora

> A general-purpose test framework for the AI era, built on pytest: **agents write the tests, the framework judges them, people review.**
>
> HTTP API testing today; UI automation (Web / App) is planned. Nothing here is tied to a business domain — flows, environments and data live in the user's own repository.

The full documentation is in Chinese: [README.md](README.md).

## What it adds on top of pytest

Tests are ordinary pytest tests. What you get in addition:

- **Checks as values.** `assert_all` reports every failed judgement at once, each with actual value, expected value and source — not just the first `assert`.
- **Strict, explicit comparisons.** `field(r, 'data.fee') <= 100`, `.is_in()`, `.matches()`, `.each('price')`, `.decimal()`. Booleans are not numbers, numeric strings are not silently coerced, and anything that cannot be judged is a failed check with the reason — never an exception.
- **Failure triage.** Each failure is classified as product defect, contract change, environment, data, or harness, so a broken test environment does not read as a broken product.
- **One run, three readers.** `ipandora run` writes HTML, JSON and JUnit XML from the same data, redacted before rendering. `core.runner.run()` returns a structured result. An optional MCP server (`ipandora mcp`) gives AI agents the same runner with context-sized summaries.
- **No LLM at test time.** LLM support is optional, off by default, and structurally kept out of the assertion path.

```python
from ipandora.core.assertion import assert_all, field, status_ok

def test_create_order():
    r = OrderService().create(100)
    assert_all(
        status_ok(r),
        field(r, 'data.amount') == 100,
        field(r, 'data.items').each('price').decimal() > 0,
    )
```

```shell
pip install intellipandora          # core: 8 dependencies
pip install intellipandora[mcp]     # optional: agent entry point
ipandora run tests -e staging       # overlays ./conf/staging.yaml for this run
```

## Relation to other tools

| Tool | Its job | Ours |
|---|---|---|
| pytest | discover and run tests, fixtures, plugins | built on it; adds checks, triage, reports, a programmable runner and MCP |
| Playwright / Appium / requests | drive the system under test | judge the result; the planned UI layer uses them as drivers |
| AI device agents (e.g. Google ARTEMIS) | explore, smoke-test and reproduce bugs in natural language | deterministic verdicts for regression |

## License

Apache License 2.0
