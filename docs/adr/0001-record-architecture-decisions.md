# 1. Record architecture decisions

Date: 2026-07-17
Status: Accepted

## Context

This repo inherits the ADR practice from `twin-services`, whose decisions
(gRPC internal / REST edge, schema evolution, health-check design) remain
in force here — the stack is vendored, and so is its reasoning. What needs
capturing now are the choices this repo adds: where faults are injected,
what a feature is, and how a model earns its place over a rule. ML work is
unusually good at hiding decisions inside notebook cells; ADRs are how they
stay visible.

## Decision

We will use Architecture Decision Records (ADRs) as described by Michael
Nygard. Each ADR is a short markdown file in `docs/adr/`, numbered in
sequence. Format: Context → Decision → Consequences.

Status is one of: Proposed, Accepted, Deprecated, Superseded by ADR-XXXX.

Inherited `twin-services` ADRs are referenced by their upstream numbers,
not copied; this repo's sequence records only its own decisions.

## Consequences

- Every meaningful design decision is discoverable via `ls docs/adr/`.
- PRs that introduce a new dependency or cross a layer boundary must
  include an ADR (or a dependency note inside an existing one).
- Decisions with measurable claims (detection quality, approximation
  limits) cite their numbers; an ADR that could not be wrong is a blog
  post.
- ADRs are append-only. Corrections happen via a new ADR that supersedes.
