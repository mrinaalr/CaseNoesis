"""The CaseNoesis extraction engine.

A record's text goes in. Readers each write their own assertions with a
character span. The span gate checks every span against the text. The resolver
counts votes by evidence family and stores only what the evidence supports;
the rest goes to a review queue. Resolved values are written back as a
CASE/UCO graph through the pinned SDK and validated.

See `Architecture design.md`, section 5.
"""

ENGINE_VERSION = "1.0.0"
