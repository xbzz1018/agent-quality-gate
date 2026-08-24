import argparse
import asyncio

from temporalio.client import Client


async def cancel(target_host: str, workflow_id: str) -> None:
    client = await Client.connect(target_host)
    await client.get_workflow_handle(workflow_id).cancel()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cancel one explicitly named Temporal workflow")
    parser.add_argument("workflow_id")
    parser.add_argument("--target-host", default="127.0.0.1:7233")
    args = parser.parse_args()
    asyncio.run(cancel(args.target_host, args.workflow_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
