import asyncio
import time
import random
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.application.current import get_app

FUNNY_QUOTES = [
    "Oink oink! Time is money!",
    "I smell truffles... no, wait, that's just a high ROI!",
    "Are you still there, or did you declare bankruptcy?",
    "My snout is pointing towards high ROI!",
    "A penny saved is... well, just a penny. Go big!",
    "Indubitably, the numbers speak for themselves.",
    "Let us not be bearish on my patience, my friend.",
    "Sniffing around for some alpha, are we?",
]

PIG_FRAMES = [
    "(oo)",
    "(-o)",
    "(o-)",
    "(oo)",
    "(~o~)",
]

EAR_FRAMES = [
    "    ◢◣       ◢◣   ",
    "    ◥◤       ◥◤   ",
]


class PigState:
    def __init__(self):
        self.frame_idx = 0
        self.ear_idx = 0
        self.quote = ""
        self.last_activity = time.time()

    def get_prompt(self, prompt_text: str = "You: "):
        pig_color = "ansimagenta"  # Closest to pink
        quote_color = "ansiyellow"

        snout = PIG_FRAMES[self.frame_idx]
        ears = EAR_FRAMES[self.ear_idx]

        # Center the snout properly based on length
        snout_len = len(snout)
        left_pad = (8 - snout_len) // 2
        right_pad = 8 - snout_len - left_pad
        snout_line = " " * left_pad + snout + " " * right_pad

        pig_art = f"""
<{pig_color}>{ears}</{pig_color}>
<{pig_color}>   ┌┴┴───────┴┴┐   </{pig_color}>
<{pig_color}>   │  $     $  │   </{pig_color}>
<{pig_color}>   │  {snout_line} │   </{pig_color}>
<{pig_color}>   │   ╘═══╛   │   </{pig_color}>
<{pig_color}>   └───────────┘   </{pig_color}>
"""
        res = pig_art
        if self.quote:
            res += f"<{quote_color}>[Sir Pennyworth]: {self.quote}</{quote_color}>\n"
        res += f"<ansiyellow><b>{prompt_text}</b></ansiyellow>"
        return HTML(res)


pig_state = PigState()


async def bg_task():
    """Background task to update the pig's animation frame and show idle quotes."""
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        idle_time = now - pig_state.last_activity

        # Animate every 0.5 seconds
        if int(now * 2) % 2 == 0:
            pig_state.frame_idx = random.randint(0, len(PIG_FRAMES) - 1)
            # Only occasionally flap ears
            if random.random() > 0.8:
                pig_state.ear_idx = 1
            else:
                pig_state.ear_idx = 0
        else:
            pig_state.frame_idx = 0
            pig_state.ear_idx = 0

        # Say something every 8 seconds of idle
        if idle_time > 8:
            if int(idle_time) % 8 == 0:
                pig_state.quote = random.choice(FUNNY_QUOTES)
        else:
            pig_state.quote = ""

        try:
            app = get_app()
            if app:
                app.invalidate()
        except Exception:
            pass


async def get_input_with_pig(
    session: PromptSession = None, prompt_text: str = "You: ", is_password: bool = False
) -> str:
    """Gets user input while Sir Pennyworth animates in the background."""
    # If not a TTY (e.g., in some CI or test environments), fallback to standard input
    if not sys.stdin.isatty():
        print(prompt_text, end="", flush=True)
        return sys.stdin.readline().strip("\n")

    if session is None:
        session = PromptSession()

    task = asyncio.create_task(bg_task())
    try:
        pig_state.last_activity = time.time()
        ans = await session.prompt_async(
            lambda: pig_state.get_prompt(prompt_text), is_password=is_password
        )
        pig_state.last_activity = time.time()
        return ans
    except EOFError:
        return "exit"
    except KeyboardInterrupt:
        return "exit"
    finally:
        task.cancel()
