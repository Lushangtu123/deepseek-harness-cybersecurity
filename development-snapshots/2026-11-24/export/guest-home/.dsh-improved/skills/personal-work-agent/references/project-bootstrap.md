# New-project bootstrap

Use this mode for a new software project or the unfinished initial build of one. A new component explicitly requested inside a monorepo must respect its existing architecture. Ordinary enhancements to an established product use code maintenance.

## Use Project Builder when available

Resolve `project-builder` in the current skill catalog, including its actual namespace, then read its entrypoint. It is bundled alongside PWA but catalog availability must still be checked. Read [capability-routing.md](capability-routing.md) before selecting helpers.

Pass the current intent (plan/build/review/resume), target path and existing state, confirmed requirements and non-goals, acceptance criteria, constraints, relevant personal preferences, approvals, and current progress. Reuse the conversation; do not make the user repeat an approved brief. Personal stack defaults are preferences, not requirements or proof that dependencies are installed.

Project Builder owns the scoped initial build. PWA retains the overall outcome, permissions, and final evidence gate; do not run two competing implementation workflows or recursively route the build between skills. Resume unfinished slices even after files exist. After the agreed first release is verified, later fixes and enhancements normally return to maintenance. No automatic new chat, commit, publication, or deployment is implied.

If Project Builder is unavailable, use the native fallback below without silently installing it. Planning and review requests remain read-only except for requested deliverables. Inspect the actual target before scaffolding and preserve existing user work.

## Native fallback

## Establish the project contract

Use [task-sizing.md](task-sizing.md) to choose the amount of discussion and planning. A new directory alone does not justify a lengthy design process; unresolved material choices do.

Before scaffolding, resolve or make explicit assumptions about:

- Target user and primary job to be done.
- Core use cases and measurable success.
- First-release scope and non-goals.
- Runtime, deployment environment, privacy, security, and budget constraints.
- Key data entities, external systems, and interfaces.

Offer materially different architecture choices when the decision affects cost, complexity, or future constraints. Obtain direction before a choice would substantially change the product.

## Select the smallest viable architecture

Use repository or user constraints first. When none exist, use the personal engineering defaults in `user-profile.md`.

- Start as a modular monolith unless independent scaling, ownership, or fault-isolation requirements justify services.
- Prefer one primary transactional data store.
- Add caching, queues, search engines, analytics stores, or additional databases only for a demonstrated requirement.
- Include meaningful tests and appropriate available lint, type, build, and CI checks; do not add irrelevant tools solely to fill a checklist.
- Keep secrets out of source control and provide non-sensitive environment examples.

## Build in vertical slices

Create the smallest end-to-end path that demonstrates the core value, then add capabilities incrementally. Each slice should include appropriate tests and an observable completion condition.

## Handoff

Provide setup commands, architecture decisions, supported workflows, verification results, environment requirements, and deferred scope. Avoid aspirational claims that are not represented in the implementation.

When the user requests a reusable project contract, adapt the optional [project-brief template](../assets/templates/project-brief.md) and remove sections that do not apply.
