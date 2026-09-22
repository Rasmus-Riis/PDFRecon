1. **Fix `subprocess` UnboundLocalError in `src/data_processing.py`:**
   - Pre-existing error in `src/data_processing.py` where `subprocess` is imported conditionally inside a `if sys.platform == "win32"` block, but accessed globally. According to memory, it should be imported at the top level of the file.
   - Modify `src/data_processing.py` to import `subprocess` globally.
2. **Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.**
   - Run tests and linting to ensure no regressions and verify the optimization works.
3. **Submit changes**:
   - Submit the PR with the required format describing the performance impact.
