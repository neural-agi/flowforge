"""Argparse CLI for the FlowForge MVP."""

import argparse
import json
import logging
from dataclasses import asdict
from uuid import UUID

from .repository import IdempotencyConflictError, WorkflowRepository
from .worker import Worker
from .workflows.order_fulfillment import (
    ORDER_FULFILLMENT,
    get_workflow_definition,
    validate_input,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flowforge")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start a workflow")
    start.add_argument("--workflow", required=True)
    start.add_argument("--idempotency-key", required=True)
    start.add_argument("--input", required=True)

    worker = commands.add_parser("worker", help="execute workflow steps")
    mode = worker.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--until-idle", action="store_true")
    worker.add_argument("--worker-id")
    worker.add_argument("--max-steps", type=int)

    for name in ("status", "history"):
        command = commands.add_parser(name)
        command.add_argument("workflow_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = WorkflowRepository()
    try:
        if args.command == "start":
            if args.workflow != ORDER_FULFILLMENT:
                raise ValueError(f"unknown workflow: {args.workflow}")
            payload = validate_input(json.loads(args.input))
            definition = get_workflow_definition(args.workflow)
            workflow = repository.create_workflow(
                definition.name,
                definition.version,
                args.idempotency_key,
                payload,
                definition.specifications(payload),
            )
            print(f"workflow_id={workflow.id} status={workflow.status} next_step=reserve_inventory")
        elif args.command == "worker":
            if args.max_steps is not None and not args.until_idle:
                raise ValueError("--max-steps requires --until-idle")
            worker = Worker(repository, args.worker_id)
            processed = (
                1
                if worker.run_once()
                else 0
                if args.once
                else worker.run_until_idle(args.max_steps)
            )
            print(f"processed_steps={processed}")
        elif args.command == "status":
            summary = repository.get_status_summary(UUID(args.workflow_id))
            if summary is None:
                raise ValueError("workflow not found")
            print(json.dumps(summary, default=str, indent=2))
        else:
            events = repository.get_history(UUID(args.workflow_id))
            print(json.dumps([asdict(event) for event in events], default=str, indent=2))
    except (ValueError, json.JSONDecodeError, IdempotencyConflictError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
