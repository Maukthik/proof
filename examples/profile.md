## Headline
Full-stack developer - Next.js client portals and AI developer tools

## About
I build web apps and developer tools that handle the parts small teams worry about: payments that never double-charge, clients who only see their own data, and code changes that don't quietly break things.

ClientDesk is a client portal for agencies, built with Next.js, TypeScript, Prisma and PostgreSQL. Clients review and approve deliverables and pay invoices through Stripe; owners, team members and clients each get their own permissions, and every query goes through one scoping layer.

Doppel is a GitHub check that runs every pull request against main in sandboxes and proves each regression, using NVIDIA Nemotron models to generate test users and judge changes. On a 30-PR benchmark it caught 17/20 regressions, and tests plus Doppel caught 20/20.

I'm looking for freelance work on SaaS web apps, Stripe integrations, and LLM-powered tools for developers. If you have a project like that, send me a message with what you need.

## Skills
Next.js, TypeScript, React, Python, Stripe, PostgreSQL, Prisma, LLM agents, GitHub Actions, CI/CD, multi-tenant SaaS, REST APIs, regression testing, Tailwind CSS

## Resume bullets
### ClientDesk
- Built a multi-tenant client portal (Next.js 16, TypeScript, Prisma, PostgreSQL) where agencies share deliverables, collect approvals and send invoices.
- Integrated Stripe Checkout and Stripe Connect with an idempotent webhook flow, so a payment is recorded exactly once.
- Designed role-based access for owners, team members and clients, with every query scoped through one data-access layer.

### Doppel
- Built a GitHub Action that runs every pull request against main in Nebius sandboxes and reports each behaviour change as evidence.
- Used NVIDIA Nemotron models to generate test users and judge changes against the PR description.
- Caught 17/20 regressions on a 30-PR benchmark (20/20 together with the existing tests), with 0 false differences in zero-setup runs on real open-source apps.
