---
name: code-review
description: >
  Structured code review following team standards. Use this skill whenever the
  user asks to "review my code", "review this PR", "check my changes", "what's
  wrong with this diff", "review the last N commits", or any variation of code
  review, code critique, or change review. Also trigger when the user pastes a
  diff or asks for feedback on code quality, even if they don't use the exact
  phrase "code review". Enforces team conventions: security-first review order,
  structured findings with severity levels (CRITICAL/WARNING/SUGGESTION),
  30-line function limit, no `any` types, no empty catches.
---

# Code Review Skill

Perform structured, actionable code reviews on any set of changes.

## Workflow

### 1. Identify what to review

Determine the scope from the user's request:

- **Staged changes**: `git diff --cached`
- **Unstaged changes**: `git diff`
- **All uncommitted changes**: `git diff HEAD`
- **A branch vs main**: `git diff main...HEAD` (or the repo's default branch)
- **Last N commits**: `git diff HEAD~N..HEAD`
- **Specific files**: review the files the user names
- **A PR**: use `gh pr diff <number>` if the GitHub CLI is available

If the scope is ambiguous, check `git status` and `git log --oneline -5` to orient yourself, then ask the user to confirm what they want reviewed.

### 2. Gather context

Before reviewing, quickly understand the project:

- Glance at the repo structure (`ls` the root, check for a README, config files, CI config)
- Note the language(s), framework, and test setup
- Check for linting/formatting configs (`.eslintrc`, `pyproject.toml`, `.prettierrc`, etc.)
- Look at any related tests or modules that the changed code touches

This helps you give feedback that fits the project's conventions rather than generic advice.

### 3. Perform the review

Go through the diff methodically. Review in this exact priority order — always check security first.

#### 1. Security (always first)
- SQL/NoSQL injection — is user input parameterized or concatenated?
- Unvalidated input — are request bodies, query params, and path params validated and sanitized?
- Missing auth — are endpoints and operations properly gated behind authentication and authorization?
- Secrets in code — any API keys, tokens, passwords, or connection strings hardcoded?
- CORS issues — are origins overly permissive? Is `Access-Control-Allow-Origin: *` used in production?

#### 2. Error Handling
- Async operations must be wrapped in try/catch
- Errors must be logged with context (what operation failed, with what input)
- Use a consistent error format across the codebase
- No empty catch blocks — every catch must log or rethrow

#### 3. Performance
- N+1 queries — look for database calls inside loops
- Missing indexes — are queried/filtered fields indexed?
- Unbounded queries — are there queries without `LIMIT` that could return massive result sets?
- Large payloads without pagination — are list endpoints paginated?

#### 4. Code Quality
- Functions should be under 30 lines; flag anything longer
- No magic numbers — constants should be named and explained
- No `any` types (TypeScript) — use proper type annotations
- Dead code must be removed, not commented out

#### 5. Testing
- Is this change testable? If so, are there tests?
- If no tests exist, suggest specific test cases that should be written (with example descriptions)

### 4. Present findings

Start with a 2-3 sentence **Summary** of the overall assessment.

Then list each finding in this structured format:

- **Severity**: `CRITICAL` | `WARNING` | `SUGGESTION`
- **Location**: `file:line` (e.g. `src/api/users.ts:42`)
- **Issue**: What's wrong and why it matters
- **Fix**: What to do about it (concrete suggestion or code snippet)

Use `CRITICAL` for bugs, security vulnerabilities, and data-loss risks that block merging. Use `WARNING` for problems that should be fixed but aren't emergencies. Use `SUGGESTION` for improvements and style feedback.

Group findings by severity — all CRITICALs first, then WARNINGs, then SUGGESTIONs.

End with a **What's good** section — call out things done well. Good naming, solid test coverage, clean abstractions. This matters.

### 5. Offer to help fix

After presenting the review, offer to implement any of the suggested changes. For critical issues, proactively suggest making the fix right now.

## Guidelines

- Be direct but respectful. "This will crash when `user` is null" is better than "You might want to consider the possibility that `user` could perhaps be null."
- Explain *why*, not just *what*. The author learns more from "This races because the check and the update aren't atomic" than from "Add a lock here."
- Distinguish opinion from fact. "I'd prefer X" is different from "This breaks Y."
- Don't bikeshed. If it works, is readable, and follows conventions, don't suggest a rewrite just because you'd have done it differently.
- Scale your review to the change size. A one-line typo fix doesn't need a full security audit. A new auth module does.
- If the diff is very large (>500 lines), summarize the overall structure first, then focus your detailed review on the riskiest parts. Tell the user which files you examined closely and which you skimmed.
