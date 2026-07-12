# Observability v1 verification — 2026-07-12 (Asia/Shanghai)

This is bounded audit evidence from this Mac. It contains no credentials, tokens,
customer data, or full logs.

| Command | Exit | Result |
|---|---:|---|
| `python3 -m unittest discover -s experiments/gmail-inbox -p 'test_*.py' -v` | 1 | System Python 3.9 lacked the `google` package; one test indentation error was then corrected. |
| `experiments/gmail-inbox/.venv/bin/python -m unittest discover -s experiments/gmail-inbox -p 'test_*.py' -v` | 0 | 17 tests passed, including lifecycle cleanup/retry, missing executable continuation, callbacks, validation, and review. |
| `swift test --package-path experiments/gmail-inbox/MenuBar` | 1 | Selected Command Line Tools compiler/SDK mismatch and cache permission failure before package compilation. |
| `env HOME=/tmp/project-brain-swift-home CLANG_MODULE_CACHE_PATH=/tmp/project-brain-clang-cache SWIFTPM_MODULECACHE_OVERRIDE=/tmp/project-brain-swift-cache swift test --disable-sandbox --package-path experiments/gmail-inbox/MenuBar` | 1 | App sources compiled after the entry-file fix; this Command Line Tools installation has no `XCTest` module, so tests could not compile. |
| `env HOME=/tmp/project-brain-swift-home CLANG_MODULE_CACHE_PATH=/tmp/project-brain-clang-cache SWIFTPM_MODULECACHE_OVERRIDE=/tmp/project-brain-swift-cache swift build --disable-sandbox -c release --package-path experiments/gmail-inbox/MenuBar` | 0 | Production build completed successfully. |

Known gap: rerun `swift test` with a matching full Xcode installation that provides
XCTest. The failed test command is not represented as accepted evidence.
