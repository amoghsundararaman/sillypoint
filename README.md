# Sillypoint

A cricket analytics platform with a learned foundation model for ball-by-ball event sequences.

## What this is

Sillypoint combines two things rarely shipped together in cricket analytics:

1. **CrickFormer** — a transformer-based foundation model trained on Cricsheet's ball-by-ball data, learning representations of players, contexts, and match situations from next-ball outcome prediction. Used to derive a *learned* pressure index (vs. the closed-form indices common in the literature), player similarity, and counterfactual simulation.
2. **An agentic natural-language interface** — text-to-SQL over the structured data, RAG over commentary, and tool use over the model's outputs, delivered as a live web platform and Chrome extension.

## Project status

🚧 Under active development. This is a solo research and engineering project.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (coming soon).

## Reproducibility

- Data: pinned Cricsheet snapshot (see `data/raw/README.md`)
- Models: tracked via MLflow in `mlruns/`
- Temporal splits: train on matches before cutoff date, test on matches after. No random splits.
- Daily research log: [`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md)

## License

TBD — likely MIT for code, CC BY for any released datasets, with attribution to Cricsheet (CC BY 3.0).

## Acknowledgements

- [Cricsheet](https://cricsheet.org) — ball-by-ball data under CC BY 3.0