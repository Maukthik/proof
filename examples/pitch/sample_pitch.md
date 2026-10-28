Files in email, approvals in Slack and invoices in a spreadsheet: that's exactly the mess I built ClientDesk to replace.

ClientDesk is a client portal for small agencies, built with Next.js 16 (App Router, Server Actions), TypeScript, Prisma and PostgreSQL:

- Role-based access for owners, team and clients: clients see only their own projects and files, and approve deliverables or request changes. Every query goes through one scoping layer, so a client can never see another client's work.
- Clients pay invoices by card through Stripe Checkout. Both the webhook and the return from Checkout settle the payment, and the update is idempotent, so nothing is ever marked paid twice.
- Email goes out for invitations, new invoices, review requests and payments.

For automated tests it has Vitest unit tests; for you I'd add end-to-end tests of the approve-and-pay flow. I haven't deployed it to Vercel or AWS yet, but it's a standard Next.js app, so deployment would be set up in the first week.

Could I show you a 15-minute demo, walking through your studio's workflow?
