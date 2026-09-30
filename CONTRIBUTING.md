# Contributing to GleanWise

Thanks for wanting to help. This document covers how contributions are
licensed and what you need to do before we can merge your work.

## License of contributions

By submitting a contribution you agree that it is licensed to the project under
the **GNU Affero General Public License v3 or later** (`AGPL-3.0-or-later`), the
same license as the rest of the repository (see [LICENSE](LICENSE)).

## Contributor License Agreement (CLA)

We also require an Individual [Contributor License Agreement](CLA.md). The CLA
Assistant bot will ask you to sign on your first pull request. Sign by
commenting:

```text
I have read the CLA Document and I hereby sign the CLA
```

**Why a CLA?** You keep the copyright in your work. The CLA additionally grants
the project owner the right to distribute your contribution under the AGPL
**and**, when needed, under a separate commercial license. That dual-license
option is how organizations that cannot meet the AGPL’s network-source rules
can still use GleanWise legally (see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)).
A share of that commercial revenue is pledged back to contributors
([REVENUE-SHARING.md](REVENUE-SHARING.md)). Without the CLA, offering that
commercial path (and the revenue share) would not be practical.

The CLA file is marked **DRAFT: pending legal review**. Treat the substance as
the intended agreement until counsel signs off.

## Development

See the root [README.md](README.md) for setup, tests, and the monorepo layout.

Before opening a PR:

1. Run the relevant checks (`pnpm` / `uv` gates described in the README).
2. Confirm new source files carry the SPDX header
   (`SPDX-License-Identifier: AGPL-3.0-or-later` and the copyright line).
   `python scripts/check_license_headers.py` must pass.
3. Sign the CLA when the bot asks.

## Conduct

Be respectful. Harassment and personal attacks are not acceptable.
