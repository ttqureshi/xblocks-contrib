0001 Purpose of This Repo
#########################

Status
******

**Draft**

Context
*******

XBlocks are currently embedded within the edx-platform. Over time, this has led to increased complexity and difficulties in maintaining and updating the platform, particularly as the platform has evolved.

Decision
********

The XBlocks will be extracted from the edx-platform and placed in this repository.

Consequences
************

- Easier refactoring, testing, and development of XBlocks.
- Simplified edx-platform leading to potential performance improvements and reduced complexity.
- Potential challenges in synchronizing changes across multiple repositories.
- xblock Sass and JS can be removed from the legacy edx-platform static assets build.

References
**********

.. _edx-platform xblocks extraction: https://openedx.atlassian.net/wiki/x/A4Dn-/
