# Product

## Product Identity

**Primary program name:** Open Formal Workflows

**Deployment subtitle:** Formal Conjectures · Review, Verification & Preservation

The repository and public deployment use the `open-formal-workflows` slug. The
legacy `fc-review-board.pr-audit-projection.v1` schema identifier remains stable
for evidence-consumer compatibility. The name does not imply Formal Conjectures
maintainer endorsement or transfer authority away from the upstream repository.

## Register

brand at the public root; product at `/workbench/`

## Users

Cold public readers and AI for Math Seed Grant evaluators who need to understand the program before inspecting it, plus Formal Conjectures maintainers and technically fluent reviewers who need the exact evidence workbench without confusing advisory checks for repository authority.

## Product Purpose

Orient a public reader to Open Formal Workflows, then provide a review workbench over Formal Conjectures pull requests plus a bounded review, verification, and preservation loop for one calibration case. The landing explains the evidence-to-decision boundary and leads directly to the deployment. The queue helps reviewers triage what is ready; the selected case identifies the exact source and revision, exposes pinned evidence and typed outcomes, distinguishes checked facts from errors and interpretation, leaves maintainer disposition explicitly unfilled, and makes drift or recurrence visible. Success means a reader can understand the program quickly, inspect the work and its limits, then return to Formal Conjectures for every authoritative action.

## Brand Personality

Forensic, calm, and accountable. The interface should feel like a well-kept lab notebook or code-review evidence packet: precise enough to trust, modest about what it knows, and direct about what remains unresolved.

## Anti-references

- Generic AI-agent control planes, autonomous governance dashboards, and multi-agent orchestration theater.
- Green-score dashboards that collapse evidence into approval, merge readiness, or mathematical truth.
- Marketing-heavy grant demos that hide exact inputs, hashes, errors, or missing maintainer decisions.
- A new problem registry, proof repository, or Vela-owned source of truth.
- Fake partner or integration logos, especially Econlib.

## Design Principles

- Authority is visible at every decision boundary: Formal Conjectures owns declarations, PR state, CI, and maintainer decisions.
- Evidence stays inspectable: show exact source identities, environments, roots, hashes, and typed outcomes close to each claim.
- Unknown is a first-class state: errors, unavailable evidence, staleness, and unfilled maintainer disposition remain distinct.
- Reduce maintainer reading time: exact contribution records, strong information hierarchy, progressive detail, and direct upstream links.
- Preserve provenance without creating a silo: the board is a disposable advisory projection over source-owned records.

## First-Screen Contract

The public root is a concise brand/landing surface. It names the program, states
the evidence and human-decision claim, shows the actual live deployment, and
offers **Open the review workbench** as its primary action. It must not imitate
the workbench with fabricated metrics or substitute marketing claims for
inspectable artifacts.

At `/workbench/`, the first screen is the information-rich **Review queue**. It
immediately states what the table is for, places ready-for-review work first,
and exposes familiar search, filters, grouped tables, CI state, approvals,
queue age, and advisory audit evidence. The **Contribution evidence** tab consumes the shared toolkit reports. Evidence, method, and
fidelity views support the workbench; they do not replace it.

## Program Boundaries

- The FC toolkit supplies live report validation; the Vela-related pilot remains historical context.
- Formal Conjectures is the first source-owned deployment and remains canonical and decisive.
- LeanEval and Comparator provide reproducible execution evidence with typed outcomes.
- problems.science supplies public orientation and contribution context, not authority.
- Econlib is only a possible future opt-in deployment after its source contract is agreed. It is not a current integration or partner.

## Accessibility & Inclusion

Target WCAG 2.2 AA. Do not rely on color alone for outcome or freshness states; preserve keyboard focus, readable contrast, semantic headings and tables, reduced-motion compatibility, and useful layouts from narrow mobile screens through large review monitors.
