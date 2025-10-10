0002 Handling Pointer Tags for Extracted XBlocks
####################################################

Date
****
2025-10-10

Status
******
**Draft**

Context
*******

In the Open edX ecosystem, course content is represented in **OLX (Open Learning XML)**.  
OLX supports **two organizational formats** for defining blocks:

1. **Inline Format** - The block's full definition is written inline within its tag attributes.
2. **Pointer Tag Format** - The block's definition is stored separately, and the tag only contains a `url_name` attribute pointing to that definition file.

**Example - Inline Format**

.. code-block:: xml

   <vertical display_name="LTI">
     <lti url_name="lti_789b78a45ec7"
          button_text="Launch third-party stuff"
          display_name="LTI Testing"
          has_score="true"
          weight="20.0"/>
   </vertical>

**Example - Pointer Tag Format**

.. code-block:: xml

   <vertical display_name="LTI">
     <lti url_name="e73666f5807e47cbbd161d0d3aa5132b"/>
   </vertical>

Here, the ``<lti/>`` tag is a **pointer tag** because its configuration is stored separately at:

.. code-block:: xml

   lti/e73666f5807e47cbbd161d0d3aa5132b.xml

   <lti button_text="Launch third-party stuff"
        display_name="LTI Testing"
        has_score="true"
        weight="20.0"/>

Both formats are supported by edx-platform's `XmlMixin`, which handles:

- **Parsing:** detecting pointer tags and loading their definitions from the pointed-to file.
- **Exporting:** serializing blocks in pointer format.

However, this was disrupted when **built-in XBlocks** (such as `WordCloud`, `Annotatable`, `LTI`, `HTML`, `Poll`, `Video`, `Problem`) were **extracted from edx-platform** into a new repository: **xblocks-contrib**.

The key architectural change was that **extracted XBlocks no longer depend on `XmlMixin`** and instead inherit directly from the base `XBlock` class — following the *pure XBlock* pattern.  
This transition removed pointer-tag handling functionality for those blocks.

Problem
-------

When extracted XBlocks are enabled (e.g., via `USE_EXTRACTED_<BLOCK_NAME>_BLOCK` settings) and a course containing pointer tag definitions is imported:

- The import path calls **XBlock.core's** ``parse_xml``, which only understands inline definitions.
- Since it does not recognize pointer tags, the system fails to load full definitions from referenced files.
- As a result, **empty XBlocks with default configurations** are created.

This issue was introduced when pointer-tag parsing logic from `XmlMixin` was no longer applied to extracted XBlocks.

Attempts & Exploration
----------------------

Multiple approaches were explored to restore pointer-tag support:

1. **Add pointer-tag parsing to `XBlock.core.parse_xml`**  
   - Attempted in `openedx/XBlock#830`.  
   - This would modify XBlock core to detect pointer nodes and load their definitions.  
   - Rejected to avoid changing the upstream XBlock API and core parsing logic.

2. **Implement pointer loading in edx-platform runtime (parent containers)**  
   - Explored via PR `openedx/edx-platform#37133`.  
   - The idea was to have parent container blocks (e.g., `VerticalBlock`, `SequentialBlock`) recognize child pointer tags and load their definitions.  
   - This approach worked but required extending the same support to **external container XBlocks**, which would necessitate new interfaces in the XBlock API — introducing further complexity.

3. **Alternative architectural approaches considered:**

   a. *Interface in XBlock core (containers)* –  
      Add pointer resolution logic to all container blocks in XBlock core.

   b. *Interface in XBlock core (leaf blocks)* –  
      Extend leaf blocks themselves with an interface to resolve pointers.

   c. *XML Preprocessing step in edx-platform* –  
      Before parsing, resolve all pointer tags into inline XML;  
      during export, re-convert inline definitions back into pointer tags.

Decision
--------

To quickly restore correct import/export behavior **without modifying XBlock core or edx-platform internals**,  
we will implement **Approach #2: `PointerTagMixin` in xblocks-contrib**.

Each extracted XBlock that requires pointer-tag support will:

- Include a custom `parse_xml` method, replicating the essential pointer-handling logic previously provided by `XmlMixin`.
- Handle both inline and pointer-tag formats locally.
- Export to pointer-tag format as before.

This approach offers immediate compatibility with existing course OLX structures while isolating the fix within `xblocks-contrib`.

Rationale
---------

- **Preserves stability** – No need to modify XBlock core or edx-platform runtime, both of which are widely used and sensitive to change.
- **Quick to implement** – Adding `parse_xml` logic per block or through a lightweight mixin is faster than large-scale architectural changes.
- **Non-breaking** – Existing courses using either inline or pointer-tag formats will import/export correctly once this support is added.
- **Incremental path forward** – This solution restores functionality now while allowing future refactoring toward cleaner architectural options (e.g., XML preprocessing).

Consequences
------------

**Positive**

- Extracted XBlocks (in `xblocks-contrib`) will again support both inline and pointer-tag OLX formats.
- No upstream changes required in XBlock or edx-platform.
- Existing courses remain compatible across built-in and extracted block configurations.

**Negative**

- **Architectural duplication:** Pointer-tag parsing logic will live in multiple leaf blocks or within a shared mixin, repeating what `XmlMixin` already handled.
- **Less elegant design:** The solution is pragmatic rather than ideal; pointer semantics remain tied to individual blocks instead of being centralized.
- **Future refactor required:** Long-term maintainability will benefit from migrating toward a unified preprocessing or container-based solution.

Alternatives Considered
-----------------------

1. **Core Interface (Containers or Leaf Blocks)**  
   - Would unify pointer-tag logic within XBlock core.
   - Rejected for now due to the scope and cross-repo impact.

2. **XML Preprocessing Step in edx-platform**  
   - Architecturally cleaner (resolve all pointer tags before XBlock parsing).  
   - Rejected as a longer-term project not suited for immediate release needs.

Implementation Plan
-------------------

1. Add a new `PointerTagMixin` in `xblocks_contrib` providing:
   - `parse_xml` method to detect and resolve pointer tags.
   - `add_xml_to_node` for proper export serialization.

2. Update extracted XBlocks (e.g., LTI, WordCloud, Annotatable, Poll, etc.) to:
   - Inherit from `PointerTagMixin`.
   - Support both pointer and inline OLX definitions.

3. Add tests verifying:
   - Import from both pointer-tag and inline formats.
   - Export fidelity between formats.

4. Document the mixin behavior and add developer guidance.

Future Work
-----------

Longer-term architectural improvements to consider:

- Introduce a **preprocessing layer** in edx-platform’s OLX pipeline to fully centralize pointer resolution (Approach #3).  
- Define a **standard XBlock API interface** for pointer-tag handling (Approach #1a/1b).  
- Gradually deprecate block-level pointer logic once a centralized mechanism exists.

References
----------

- `openedx/XBlock#830` – Initial attempt to add pointer-tag parsing to XBlock core  
- `openedx/edx-platform#37133` – Runtime-based pointer resolution PR  
- `xblocks_contrib` – Repository containing extracted XBlocks and new `PointerTagMixin`

Authors
-------

- Tayyab Tahir  
- Open edX Architecture Working Group  

Reviewers
----------

- Open edX XBlock Maintainers  
- edx-platform Runtime Owners  
- xblocks-contrib Maintainers
