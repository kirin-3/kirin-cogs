import asyncio
import os
import sys
import time

import aiohttp


# Mock redbot before importing our module
class MockConfig:
    pass


class MockAppCommands:
    @staticmethod
    def describe(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class Choice:
        def __class_getitem__(cls, item):
            return item


class MockContext:
    pass


class MockCommands:
    class Cog:
        pass

    Context = MockContext

    @staticmethod
    def hybrid_command(*args, **kwargs):
        def decorator(func):
            def autocomplete(*args, **kwargs):
                def inner_dec(inner_func):
                    return inner_func

                return inner_dec

            func.autocomplete = autocomplete
            return func

        return decorator

    @staticmethod
    def dynamic_cooldown(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def is_owner():
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def command(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def group(*args, **kwargs):
        def decorator(func):
            def command(*args, **kwargs):
                def inner_dec(inner_func):
                    return inner_func

                return inner_dec

            func.command = command
            return func

        return decorator

    @staticmethod
    def guild_only(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def admin_or_permissions(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class BucketType:
        user = "user"

    class Range:
        def __class_getitem__(cls, item):
            return int


class MockBot:
    class Red:
        pass


class MockRedbotCore:
    Config = MockConfig
    app_commands = MockAppCommands
    commands = MockCommands
    bot = MockBot


class MockRedbot:
    core = MockRedbotCore


import types

sys.modules["redbot"] = types.ModuleType("redbot")
sys.modules["redbot.core"] = types.ModuleType("redbot.core")
sys.modules["redbot.core.commands"] = types.ModuleType("redbot.core.commands")
sys.modules["redbot.core.bot"] = types.ModuleType("redbot.core.bot")

sys.modules["redbot"].core = sys.modules["redbot.core"]
sys.modules["redbot.core"].commands = sys.modules["redbot.core.commands"]
sys.modules["redbot.core.commands"].Cog = MockCommands.Cog
sys.modules["redbot.core.commands"].Context = MockContext
sys.modules["redbot.core.commands"].hybrid_command = MockCommands.hybrid_command
sys.modules["redbot.core.commands"].dynamic_cooldown = MockCommands.dynamic_cooldown
sys.modules["redbot.core.commands"].BucketType = MockCommands.BucketType
sys.modules["redbot.core.commands"].Range = MockCommands.Range
sys.modules["redbot.core.commands"].is_owner = MockCommands.is_owner
sys.modules["redbot.core.commands"].command = MockCommands.command
sys.modules["redbot.core.commands"].group = MockCommands.group
sys.modules["redbot.core.commands"].guild_only = MockCommands.guild_only
sys.modules["redbot.core.commands"].admin_or_permissions = MockCommands.admin_or_permissions
sys.modules["redbot.core"].Config = MockConfig
sys.modules["redbot.core"].app_commands = MockAppCommands
sys.modules["redbot.core.bot"].Red = MockBot.Red

sys.modules["modal"] = types.ModuleType("modal")

# Add the parent directory to the path so we can import unicornimage
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from unicornimage.views import LoraListView


async def event_loop_monitor(interval=0.005):
    """Monitor the event loop for blocking."""
    max_block = 0
    total_block = 0
    blocks = 0

    try:
        while True:
            start = time.perf_counter()
            await asyncio.sleep(interval)
            duration = time.perf_counter() - start

            # If it took significantly longer than the sleep interval, it was blocked
            block_time = duration - interval
            if block_time > 0.005:  # 5ms threshold
                max_block = max(max_block, block_time)
                total_block += block_time
                blocks += 1

    except asyncio.CancelledError:
        return {"max_block": max_block, "total_block": total_block, "blocks": blocks}


def busy_wait(seconds):
    end_time = time.time() + seconds
    while time.time() < end_time:
        pass


async def run_benchmark():
    # Setup dummy data and files
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unicornimage", "lorapreviews")
    os.makedirs(test_dir, exist_ok=True)

    # Create some large dummy files to simulate slow I/O
    dummy_loras = {}
    for i in range(100):
        key = f"lora_{i}"
        dummy_loras[key] = {"name": f"LoRA {i}", "description": "Test", "base": "SD1.5"}

        # Write a 10MB dummy file
        with open(os.path.join(test_dir, f"{key}.png"), "wb") as f:
            f.write(os.urandom(10 * 1024 * 1024))

    print(f"Created {len(dummy_loras)} dummy files (10MB each) for testing.")

    # Run the operation
    async with aiohttp.ClientSession() as session:
        view = LoraListView(dummy_loras, session)
        view.items_per_page = 20  # load all

        # Warm up disk cache
        page_items = view.lora_list[0:100]
        await view.fetch_images(page_items)

        # Start monitor
        monitor_task = asyncio.create_task(event_loop_monitor())
        start_time = time.perf_counter()

        # Fetch images (this is the function we're testing)
        await view.fetch_images(page_items)

        end_time = time.perf_counter()

    # Stop monitor
    monitor_task.cancel()
    monitor_stats = await monitor_task

    print("\n--- Benchmark Results ---")
    print(f"Total execution time: {end_time - start_time:.4f} seconds")
    print(f"Event loop blocked: {monitor_stats['blocks']} times")
    print(f"Max block duration: {monitor_stats['max_block'] * 1000:.2f} ms")
    print(f"Total block duration: {monitor_stats['total_block'] * 1000:.2f} ms")

    # Clean up dummy files
    for i in range(100):
        try:
            os.remove(os.path.join(test_dir, f"lora_{i}.png"))
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_benchmark())
