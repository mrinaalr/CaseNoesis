# CaseNoesis

**CaseNoesis** aggregates, structures, and analyzes case data across the full range of modern offense types to understand how platform affordances are misused and crime types evolve alongside technology.

## Origin & Framework

The theoretical foundation for this project is **["Affordances for Harm: How Offenders Misuse Platform Capabilities to Exploit Children, and Where to Intervene"](https://mrinaalr.github.io/website/Affordance%2C%20Misuse%2C%20Harm%2C%20Kill%20Chain.pdf)**

AfH develops a formal affordance–misuse–harm framework (φ/η/ψ mapping) and validates it against a corpus of ICAC enforcement cases. CaseNoesis is the empirical test of whether that framework generalizes across offense types beyond the one it was orginally derived from.

## Scope

- Multi-offense-category ingestion and processing pipeline (fraud, cyber-enabled crime, trafficking, and others to be defined as the project develops)
- Interfaced via MCP, command-line tools, and public dashboard
- Local database and external API integrations
- Runnable via localhost for collaborators and cloners

## Status

Early stage. Ingestion architecture and offense-category taxonomy are under active development. No public data release yet.

## Data & Ethics

Case data is drawn exclusively from publicly available enforcement records (press releases, court filings). 


## Contributing

Contributors can help by:
- Proposing offense categories and taxonomy structure
- Ingestion pipeline design for new offense categories
- Code implementation

---

*CaseNoesis builds on ideas developed in [CaseLinker](https://github.com/mrinaalr/CaseLinker), a CSEA-focused case analysis platform. The relationship is one of shared DNA, not shared codebase. CaseNoesis's ingestion and processing layers are being built independently for cross-domain use.*