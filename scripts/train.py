#!/usr/bin/env python3
"""
Pandora Graph ML Training CLI.

Trains GraphSAGE and/or TransE models, registers them in PostgreSQL,
and exports updated embeddings to Qdrant.

Usage:
    # Train GraphSAGE on concept-concept relationships
    python scripts/train.py --model graphsage --edge-type Concept__RELATED_TO__Concept

    # Train TransE on method genealogy
    python scripts/train.py --model transe --edge-type Method__VARIANT_OF__Method

    # Train all priority edge types
    python scripts/train.py --all

    # Refresh all embeddings after training
    python scripts/train.py --embed-only

    # Evaluate active models
    python scripts/train.py --eval-only
"""
import argparse
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from loguru import logger

PRIORITY_EDGE_TYPES = [
    "Concept__RELATED_TO__Concept",
    "Paper__CITES__Paper",
    "Domain__SUBDOMAIN_OF__Domain",
    "Method__VARIANT_OF__Method",
]


async def run_training(
    model_type: str,
    edge_type: str,
    hidden_dim: int = 256,
    num_layers: int = 3,
    embedding_dim: int = 200,
    epochs: int = 50,
) -> dict:
    """Run a single model training job."""
    from knowledge_graph.client import setup_schema
    from vector_store.client import setup_collections

    logger.info(f"Initializing services...")
    await setup_schema()
    await setup_collections()

    if model_type == "graphsage":
        from graph_ml.models.graphsage import GraphSAGEConfig
        from graph_ml.training.pipeline import train_graphsage

        config = GraphSAGEConfig(
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            epochs=epochs,
            target_edge_type=edge_type,
        )
        logger.info(f"Training GraphSAGE | edge={edge_type} | dim={hidden_dim} | epochs={epochs}")
        start = time.time()
        result = await train_graphsage(config)
        duration = time.time() - start

    elif model_type in ("transe", "rotate"):
        from knowledge_graph.client import run_query
        from graph_ml.models.transe import TransEConfig, RotatE
        from graph_ml.training.pipeline import train_transe

        src_type = edge_type.split("__")[0]
        count_result = await run_query(f"MATCH (n:{src_type}) RETURN count(n) AS cnt")
        num_entities = count_result[0]["cnt"] if count_result else 10000

        config = TransEConfig(
            num_entities=num_entities,
            num_relations=1,
            embedding_dim=embedding_dim,
            epochs=epochs,
        )
        logger.info(f"Training TransE | edge={edge_type} | dim={embedding_dim} | epochs={epochs} | entities={num_entities}")
        start = time.time()
        result = await train_transe(config, edge_type)
        duration = time.time() - start

    else:
        logger.error(f"Unknown model type: {model_type}")
        return {"error": f"unknown model type: {model_type}"}

    result["duration_s"] = int(duration)
    logger.success(f"Training complete in {duration:.0f}s: {result}")
    return result


async def run_embedding_refresh(node_type: str | None = None):
    """Refresh embeddings for all nodes or a specific type."""
    from graph_ml.tasks.ml_tasks import _refresh_embeddings_async
    from knowledge_graph.client import setup_schema
    from vector_store.client import setup_collections

    await setup_schema()
    await setup_collections()

    logger.info(f"Starting embedding refresh (node_type={node_type or 'all'})...")
    result = await _refresh_embeddings_async(node_type)
    logger.success(f"Embedding refresh complete: {result}")
    return result


async def run_eval():
    """Print current model registry metrics."""
    import asyncpg
    from core.config import get_settings
    settings = get_settings()

    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    try:
        conn = await asyncpg.connect(dsn)
        rows = await conn.fetch(
            """
            SELECT model_name, model_type, relation_type,
                   test_mrr, hits_at_1, hits_at_10, is_active, trained_at
            FROM ml_models
            ORDER BY trained_at DESC NULLS LAST
            LIMIT 20
            """
        )
        await conn.close()

        if not rows:
            logger.warning("No models in registry. Train a model first.")
            return

        print("\n" + "="*80)
        print("PANDORA MODEL REGISTRY")
        print("="*80)
        print(f"{'Model':<40} {'Type':<12} {'MRR':>6} {'H@1':>6} {'H@10':>6} {'Active'}")
        print("-"*80)
        for r in rows:
            active = "✓" if r["is_active"] else ""
            print(
                f"{r['model_name'][:38]:<40} "
                f"{r['model_type']:<12} "
                f"{(r['test_mrr'] or 0)*100:>5.1f}% "
                f"{(r['hits_at_1'] or 0)*100:>5.1f}% "
                f"{(r['hits_at_10'] or 0)*100:>5.1f}% "
                f"{active}"
            )
        print("="*80 + "\n")
    except Exception as e:
        logger.error(f"Could not connect to DB: {e}")


async def main():
    parser = argparse.ArgumentParser(
        description="Pandora Graph ML Training CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model",      choices=["graphsage", "transe", "rotate"], help="Model type to train")
    parser.add_argument("--edge-type",  default="Concept__RELATED_TO__Concept",    help="Edge type to train on")
    parser.add_argument("--hidden-dim", type=int, default=256,                     help="GraphSAGE hidden dim")
    parser.add_argument("--num-layers", type=int, default=3,                       help="GraphSAGE layers")
    parser.add_argument("--embed-dim",  type=int, default=200,                     help="TransE embedding dim")
    parser.add_argument("--epochs",     type=int, default=50,                      help="Training epochs")
    parser.add_argument("--all",        action="store_true",                       help="Train all priority edge types")
    parser.add_argument("--embed-only", action="store_true",                       help="Only refresh embeddings")
    parser.add_argument("--node-type",  help="Node type for embedding refresh (default: all)")
    parser.add_argument("--eval-only",  action="store_true",                       help="Print model registry and exit")
    args = parser.parse_args()

    if args.eval_only:
        await run_eval()
        return

    if args.embed_only:
        await run_embedding_refresh(args.node_type)
        return

    if args.all:
        logger.info(f"Training all priority edge types: {PRIORITY_EDGE_TYPES}")
        model_type = args.model or "graphsage"
        for edge_type in PRIORITY_EDGE_TYPES:
            await run_training(
                model_type=model_type,
                edge_type=edge_type,
                hidden_dim=args.hidden_dim,
                num_layers=args.num_layers,
                embedding_dim=args.embed_dim,
                epochs=args.epochs,
            )
        # Refresh embeddings after all training
        await run_embedding_refresh()
        await run_eval()
        return

    if not args.model:
        parser.print_help()
        sys.exit(1)

    await run_training(
        model_type=args.model,
        edge_type=args.edge_type,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        embedding_dim=args.embed_dim,
        epochs=args.epochs,
    )

    if input("\nRefresh embeddings now? [y/N] ").lower() == "y":
        await run_embedding_refresh()

    await run_eval()


if __name__ == "__main__":
    asyncio.run(main())
