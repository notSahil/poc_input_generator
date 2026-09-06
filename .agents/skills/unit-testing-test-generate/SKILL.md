---
name: unit-testing-test-generate
description: Generates robust, isolated unit tests using pytest following the Arrange-Act-Assert pattern.
---

# Unit Testing & Generation Guidelines

When this skill is activated to write or update tests:

## 1. Pytest over Unittest
- Always use `pytest` paradigms. Do not use `unittest.TestCase` class structures unless modifying an existing legacy test suite.
- Use raw `assert` statements instead of `self.assertEqual()`.

## 2. The AAA Pattern
- Visually separate test phases with comments or newlines:
  - **Arrange**: Set up the data, mocks, and state.
  - **Act**: Call the function being tested.
  - **Assert**: Verify the results and side effects.

## 3. Fixtures and Mocking
- Use `@pytest.fixture` for any reusable setup logic or mock data.
- Thoroughly mock external API calls (e.g., Salesforce HTTP requests) using `unittest.mock.patch` or `responses`. A unit test should **never** make a real network request.

## 4. Coverage
- Test the "Happy Path" (expected successful behavior).
- Test Edge Cases (empty lists, boundary values, nulls).
- Test Error Handling (ensure the correct exceptions are raised using `pytest.raises()`).
