---
name: project-builder
description: Build new software projects from an idea or approved brief through a verified first release. Use when starting an app, service, CLI, library, or prototype from scratch, or resuming its unfinished initial build. Works directly or as Personal Work Agent's greenfield specialist; not the default for routine changes to an established project.
metadata:
  version: "0.9.8"
---

# Project Builder

Turn an agreed product boundary into working software, not just a scaffold. Keep the first release small without dropping required behavior, security, accessibility, or verification. Use the user's language for communication.

Use this host's actual skill names, tools and execution environment. A cloud Desktop session cannot assume access to a local repository or Codex APIs. Resolve supporting files from this loaded skill and report unavailable capabilities without fabricating execution.

Before the first verification command, read [references/acceptance.md](references/acceptance.md). When routed from PWA, retain its verification checkpoint: read the available [quality gates](../personal-work-agent/references/quality-gates.md), and for multiple commands or exact runtime versions read [command evidence](../personal-work-agent/references/command-evidence.md) before execution, then capture commands and derive/check the report. Standalone use without those resources retains native results and discloses the missing structured gate. A passing unit suite without the requested user flow and required evidence is not a verified release.

## Enter without restarting the conversation

When Personal Work Agent (PWA) routes here, or when continuing a previous build, read [references/pwa-handoff.md](references/pwa-handoff.md). Reuse confirmed requirements, decisions, acceptance checks, current artifacts, and permission limits. Do not route back to PWA to start the same build again; using this skill does not launch another agent or chat.

For direct use, establish only missing context. A request for a plan, comparison, or review stays read-only unless the user requests a saved deliverable; it does not authorize scaffolding or installation.

Inspect the intended target directory and applicable repository instructions before writing. Do not assume the current directory is empty or intended for the new product. Preserve existing files, Git state, and parent-workspace conventions; clarify a conflicting or ambiguous destination. An explicitly requested new component in a monorepo must respect that repository, not replace its architecture.

If this is ordinary maintenance of an established project, use the available maintenance workflow instead. An unfinished initial build stays here even after its first files exist.

## Define the smallest useful release

Reuse answers already provided. Resolve only choices that materially change implementation:

- Who uses it, their primary task, and an observable success condition.
- First-release capabilities, non-goals, and prototype versus maintained-product intent.
- Target directory, platform/runtime, data sensitivity, external systems, hosting and cost constraints.
- Acceptance examples for the core flow and its important failure paths.

For a clear small request, state reasonable assumptions and proceed. For consequential uncertainty, use an available clarification/design skill or ask the smallest useful question before committing to that choice. Do not silently turn a multi-user product into a local demo, or invent user approval. Keep a durable brief only when it helps substantial or cross-session work; do not create a fixed pile of planning documents for every project.

When project terms or lasting design decisions need documentation, read the bundled [project-knowledge guidance](../personal-work-agent/references/project-knowledge.md), without re-entering PWA routing. If used outside the bundle and that reference is unavailable, reuse existing docs, distinguish confirmed decisions from proposals, and preserve exact acceptance criteria; do not install PWA just to write notes. Plan-only work still does not authorize document changes unless a saved deliverable was requested.

## Choose architecture and establish a runnable baseline

1. Follow explicit choices and repository constraints first. Treat PWA's passed personal defaults as preferences, not requirements or evidence of installed tools. For direct use, choose the smallest suitable stack and disclose material assumptions; no framework is mandatory.
2. Compare alternatives only when they change cost, privacy, deployment, or maintenance. Prefer a single deployable and, when persistence is needed, one primary store until requirements justify more. A CLI or library need not become a web application.
3. Check available runtime/tool versions and authoritative documentation where compatibility matters. Before executing a generator, package script, downloaded template, or test/build command, inspect its real effects, including lifecycle scripts. For an unresolved command chain or missing execution prerequisite, use the bundled [execution preflight](../personal-work-agent/references/execution-preflight.md); if unavailable, inspect actual definitions, preserve unknowns, and propose the smallest authorized setup without installing implicitly. Pin chosen tooling where supported; do not run a floating scaffolder by habit.
4. Build a minimal baseline with a documented entry command and a meaningful smoke check. Use an appropriate test runner and available lint/type/build checks; do not add tools merely to fill a checklist. Record resolved dependencies with the native lock mechanism after an authorized install; never fabricate a lockfile or successful installation.
5. Add non-secret environment examples and ignores when relevant. Configure local/CI checks for the chosen host when in scope, but do not activate a remote workflow, publish a repository, or create cloud resources as an implicit bootstrap step.

## Implement complete vertical slices

Start with the smallest user journey that proves the product's value across its real boundaries. Define its acceptance check, build it, and observe its final result before widening the feature set. Keep interfaces and data contracts simple and explicit.

Use the existing test-first workflow when appropriate; select one test methodology, not several overlapping skills. Choose frontend, backend, framework, debugging, browser, or security specialists only for the current slice. Resolve their actual catalog names and prerequisites, read the chosen instructions, and keep their side effects within this task. Missing specialists do not authorize installation; use native tools and disclose consequential limitations.

Mock or fixture external services when access is unavailable, with the substitute clearly labeled. Do not present mock-only flows as live integrations. Avoid placeholder authentication, swallowed failures, fabricated data, or disabled checks that make an unfinished feature look complete.

For independent parallel work, assign non-overlapping owned paths and explicit interface contracts. Integrate and verify the combined result before claiming completion; a worker's report is not evidence by itself.

## Verify and hand off

Read [references/acceptance.md](references/acceptance.md) before the first-release claim. A scaffold, server startup, screenshot, or green unit suite alone does not establish the requested outcome. If the environment blocks execution, preserve useful work and report the exact blocked check instead of claiming readiness.

Provide the project location, actual start/test commands and prerequisites, supported user flows, acceptance evidence, relevant decisions, and remaining gaps. Update an existing README or equivalent entry document when appropriate; do not leave essential setup only in chat.

Use [references/pwa-handoff.md](references/pwa-handoff.md) when returning to PWA or preserving a continuation. Once the agreed first release is verified, subsequent fixes and enhancements normally use PWA's maintenance mode. Do not automatically begin the next feature, create a new chat, commit, publish, or deploy.

## Action boundaries

In-scope local code, documentation, and safe checks are allowed by a build request. Preserve unrelated work and inspect commands before running them. Obtain authorization for the concrete dependency installation, external/shared mutation, commit/push/PR, migration, or out-of-workspace change, and obey host approval. An exact already-authorized action does not need duplicate conceptual confirmation.

Production deployment, deletion, purchases, access/security changes, and credentials need explicit action-specific direction. A proposed deployment target or supplied credential is not permission to act. Do not expose secrets, operate investment accounts, place trades, or transfer money. For an uncertain previous external mutation, reconcile read-only state or documented idempotency before retrying. Return the blocker and next safe action when authority or a consequential decision is missing.
